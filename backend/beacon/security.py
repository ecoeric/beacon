"""Token authentication, scope checks, audit trail and throttling.

Design notes
------------
* Tokens are 32 random bytes (base64url). Only the SHA-256 digest is stored in SQLite.
  The plaintext is written once to ``data/secrets/<name>.token`` with mode 0600 so the
  operator (and the iOS keychain provisioning step) can copy it; nothing can recover it later.
* Scopes are hierarchical for human clients: ``admin`` > ``action`` > ``read``.
  The ``agent`` scope is orthogonal and only unlocks agent runtime endpoints.
* No session cookies, no passwords, no OAuth: a single bearer header keeps the iOS client
  simple and auditable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .db import Database, new_id, now

READ = "read"
ACTION = "action"
ADMIN = "admin"
AGENT = "agent"

ALL_SCOPES = (READ, ACTION, ADMIN, AGENT)
_IMPLIED: dict[str, set[str]] = {
    READ: {READ},
    ACTION: {READ, ACTION},
    ADMIN: {READ, ACTION, ADMIN},
    AGENT: {READ, AGENT},
}


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TokenInfo:
    id: str
    name: str
    scopes: frozenset[str]

    def allows(self, required: str) -> bool:
        for scope in self.scopes:
            if required in _IMPLIED.get(scope, {scope}):
                return True
        return False


def normalise_scopes(raw: str) -> frozenset[str]:
    requested = {part.strip().lower() for part in raw.split(",") if part.strip()}
    unknown = requested - set(ALL_SCOPES)
    if unknown:
        raise ValueError(f"unknown scopes: {', '.join(sorted(unknown))}")
    if not requested:
        raise ValueError("at least one scope is required")
    return frozenset(requested)


def create_token(
    db: Database,
    secrets_dir: Path,
    name: str,
    scopes: str,
) -> tuple[str, TokenInfo]:
    scope_set = normalise_scopes(scopes)
    raw = secrets.token_urlsafe(32)
    token_id = new_id()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO token(id, name, scopes, token_sha256, created_at) VALUES (?,?,?,?,?)",
            (token_id, name, ",".join(sorted(scope_set)), hash_token(raw), now()),
        )
    secrets_dir.mkdir(parents=True, exist_ok=True)
    secret_path = secrets_dir / f"{name}.token"
    secret_path.write_text(raw + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return raw, TokenInfo(id=token_id, name=name, scopes=scope_set)


_last_used_flush: dict[str, float] = {}
_last_used_lock = threading.Lock()
LAST_USED_FLUSH_SECONDS = 60.0


def reset_security_state_for_tests() -> None:
    with _last_used_lock:
        _last_used_flush.clear()


def verify_token(db: Database, raw: str | None) -> TokenInfo | None:
    if not raw:
        return None
    digest = hash_token(raw)
    row = db.query_one(
        "SELECT id, name, scopes, token_sha256 FROM token "
        "WHERE token_sha256=? AND revoked_at IS NULL",
        (digest,),
    )
    if row is None:
        return None
    # Constant-time comparison of the stored digest (defence in depth; the lookup above is
    # already by digest).
    if not hmac.compare_digest(row["token_sha256"], digest):
        return None
    # Throttle this write: it runs on an authenticated request path and SQLite has a single
    # writer, so a burst of dashboard polls must not serialise on it.
    current = time.monotonic()
    with _last_used_lock:
        last = _last_used_flush.get(row["id"], 0.0)
        should_write = current - last >= LAST_USED_FLUSH_SECONDS
        if should_write:
            _last_used_flush[row["id"]] = current
    if should_write:
        db.execute(
            "UPDATE token SET last_used_at=? WHERE id=? AND (last_used_at IS NULL OR last_used_at < ?)",
            (now(), row["id"], now() - 30),
        )
    scopes = frozenset(part for part in str(row["scopes"]).split(",") if part)
    return TokenInfo(id=row["id"], name=row["name"], scopes=scopes)


def revoke_token(db: Database, name: str) -> bool:
    row = db.query_one("SELECT id FROM token WHERE name=?", (name,))
    if row is None:
        return False
    db.execute("UPDATE token SET revoked_at=? WHERE id=?", (now(), row["id"]))
    return True


def list_tokens(db: Database) -> list[dict]:
    rows = db.query(
        "SELECT id, name, scopes, created_at, last_used_at, revoked_at FROM token ORDER BY created_at"
    )
    return [dict(row) for row in rows]


def audit(
    db: Database,
    *,
    actor: str,
    action: str,
    target: str = "",
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    db.execute(
        "INSERT INTO audit(at, actor, action, target, detail, ip) VALUES (?,?,?,?,?,?)",
        (
            now(),
            actor,
            action,
            target,
            json.dumps(detail or {}, separators=(",", ":")),
            ip,
        ),
    )


class RateLimiter:
    """In-memory sliding-window limiter. Process-local by design (single API instance)."""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, *, limit: int, window_seconds: float) -> tuple[bool, float]:
        current = time.monotonic()
        hits = [h for h in self._hits.get(key, []) if current - h < window_seconds]
        if len(hits) >= limit:
            retry_after = window_seconds - (current - hits[0])
            self._hits[key] = hits
            return False, max(0.0, retry_after)
        hits.append(current)
        self._hits[key] = hits
        return True, 0.0
