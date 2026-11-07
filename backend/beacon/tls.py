"""Local TLS material: a private ECDSA CA plus a server certificate.

Rationale: the iPhone talks to this host over the LAN, so there is no public CA. Beacon
generates its own CA, signs a leaf certificate for the LAN IP + hostname, and the iOS app
validates the chain against the CA certificate bundled in the app (``ios/Beacon/Resources/ca.crt``)
plus an optional SPKI pin. Apple requires TLS leaf certificates to be valid for at most 398
days, so the leaf is issued for 397 days; the CA is valid for 10 years.

Private keys are written with mode 0600 and never leave ``data/tls``.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_FILENAME = "ca.crt"
CA_KEY_FILENAME = "ca.key"
SERVER_CERT_FILENAME = "server.crt"
SERVER_KEY_FILENAME = "server.key"


@dataclass
class TlsMaterial:
    ca_cert: Path
    ca_key: Path
    server_cert: Path
    server_key: Path
    pin: str
    dns_names: list[str]
    ip_addresses: list[str]
    not_valid_after: str


def tls_dir(settings) -> Path:
    return settings.tls_cert.parent


def spki_pin(cert_path: Path) -> str:
    """Base64url(SHA-256(SubjectPublicKeyInfo)) — the value the app pins."""
    certificate = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    spki = certificate.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(spki).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def certificate_info(cert_path: Path) -> dict:
    certificate = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    try:
        san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns = [str(name) for name in san.get_values_for_type(x509.DNSName)]
        ips = [str(name) for name in san.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        dns, ips = [], []
    return {
        "subject": certificate.subject.rfc4514_string(),
        "issuer": certificate.issuer.rfc4514_string(),
        "not_before": certificate.not_valid_before_utc.isoformat(),
        "not_after": certificate.not_valid_after_utc.isoformat(),
        "dns_names": dns,
        "ip_addresses": ips,
        "spki_pin": spki_pin(cert_path),
    }


def _write_key(path: Path, key) -> None:
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    os.chmod(path, 0o600)


def _write_cert(path: Path, certificate) -> None:
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    os.chmod(path, 0o644)


def generate(
    settings,
    *,
    force: bool = False,
    extra_dns: list[str] | None = None,
    extra_ips: list[str] | None = None,
) -> TlsMaterial:
    directory = tls_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    ca_cert_path = directory / CA_FILENAME
    ca_key_path = directory / CA_KEY_FILENAME
    server_cert_path = settings.tls_cert
    server_key_path = settings.tls_key

    existing = [path for path in (ca_cert_path, ca_key_path, server_cert_path, server_key_path) if path.exists()]
    if existing and not force:
        raise FileExistsError(
            "TLS material already exists (" + ", ".join(path.name for path in existing) + "); use --force to rotate"
        )
    for path in existing:
        path.unlink()

    ca_key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    ca_name = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Beacon local CA"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Beacon Local Root CA"),
        ]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = ec.generate_private_key(ec.SECP256R1())
    hostname = os.uname().nodename
    dns_names = sorted({hostname, "localhost", *(extra_dns or [])})
    ip_strings = sorted({settings.bind, "127.0.0.1", *(extra_ips or [])})
    ip_addresses = [ipaddress.ip_address(value) for value in ip_strings]
    san = x509.SubjectAlternativeName(
        [x509.DNSName(name) for name in dns_names] + [x509.IPAddress(ip) for ip in ip_addresses]
    )
    server_name = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Beacon"),
            x509.NameAttribute(NameOID.COMMON_NAME, settings.bind),
        ]
    )
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        # Apple: TLS leaf certificates must not exceed 398 days.
        .not_valid_after(now + dt.timedelta(days=397))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(san, critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write_key(ca_key_path, ca_key)
    _write_cert(ca_cert_path, ca_cert)
    _write_key(server_key_path, server_key)
    _write_cert(server_cert_path, server_cert)

    return TlsMaterial(
        ca_cert=ca_cert_path,
        ca_key=ca_key_path,
        server_cert=server_cert_path,
        server_key=server_key_path,
        pin=spki_pin(server_cert_path),
        dns_names=dns_names,
        ip_addresses=ip_strings,
        not_valid_after=server_cert.not_valid_after_utc.isoformat(),
    )


def ca_fingerprint(settings) -> str | None:
    path = tls_dir(settings) / CA_FILENAME
    if not path.exists():
        return None
    certificate = x509.load_pem_x509_certificate(path.read_bytes())
    return ":".join(f"{byte:02X}" for byte in certificate.fingerprint(hashes.SHA256()))
