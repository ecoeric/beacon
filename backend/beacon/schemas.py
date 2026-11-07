"""API data contracts.

These Pydantic models are the single definition of the JSON the iOS app decodes. They are
kept flat and explicit on purpose: the Swift models mirror them one-to-one
(`ios/Beacon/Models/Models.swift`) and a generated OpenAPI snapshot is committed under
`docs/openapi.json` for review.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AgentStateName = Literal[
    "idle",
    "working",
    "waiting_for_input",
    "waiting_for_messages",
    "completed",
    "interrupted",
    "failed",
    "disconnected",
    "unknown",
]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    time: float
    database: str
    tls: bool


class WhoAmI(BaseModel):
    token_id: str
    name: str
    scopes: list[str]


class AgentSessionInfo(BaseModel):
    id: str | None = None
    name: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    runtime_pid: int | None = None
    runtime_alive: bool = False
    last_activity_at: float | None = None
    last_activity_kind: str | None = None
    turn_running: bool = False
    transcript_updated_at: float | None = None


class EvidenceItem(BaseModel):
    source: str
    detail: str
    age_seconds: float | None = None


class QueueCounts(BaseModel):
    pending: int = 0
    delivered: int = 0
    acknowledged: int = 0
    processed_last_24h: int = 0


class InterruptInfo(BaseModel):
    id: str
    requested_at: float
    mode: str
    status: str
    reason: str = ""
    pid: int | None = None
    signal: str | None = None
    resolved_by: str | None = None
    exit_observed_at: float | None = None
    error: str | None = None
    evidence: list[str] = Field(default_factory=list)


class AgentStatusResponse(BaseModel):
    state: AgentStateName
    state_label: str
    project: str = ""
    stage: str = ""
    activity: str = ""
    last_milestone: str = ""
    next_action: str = ""
    blockers: list[str] = Field(default_factory=list)
    awaiting_input: bool = False
    progress: float | None = None
    updated_at: float | None = None
    data_age_seconds: float | None = None
    is_stale: bool = True
    stale_after_seconds: int = 0
    snapshot_source: str = "none"
    session: AgentSessionInfo = Field(default_factory=AgentSessionInfo)
    queue: QueueCounts = Field(default_factory=QueueCounts)
    latest_interrupt: InterruptInfo | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class StatusSummaryResponse(BaseModel):
    summary: str
    state: AgentStateName
    generated_at: float
    data_age_seconds: float | None = None
    is_stale: bool = True
    based_on: list[str] = Field(default_factory=list)
    deterministic: Literal[True] = True


class MessageModel(BaseModel):
    id: str
    seq: int
    kind: str
    body: str
    status: str
    created_at: float
    delivered_at: float | None = None
    acknowledged_at: float | None = None
    processed_at: float | None = None
    cancelled_at: float | None = None
    attempts: int = 0
    ack_note: str | None = None
    processed_note: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> "MessageModel":
        data = dict(row)
        data.pop("idempotency_key", None)
        data.pop("client", None)
        data.pop("session_id", None)
        return cls(**data)


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    kind: Literal["suggestion", "continue"] = "suggestion"
    idempotency_key: str | None = Field(default=None, max_length=120)


class ContinueRequest(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class InterruptRequest(BaseModel):
    mode: Literal["signal", "checkpoint"] = "signal"
    reason: str = Field(default="", max_length=500)


class AckRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class CheckpointResponse(BaseModel):
    server_time: float
    delivered: list[MessageModel] = Field(default_factory=list)
    interrupts: list[InterruptInfo] = Field(default_factory=list)
    session_id: str | None = None
    pending_remaining: int = 0
    instructions: str = (
        "Treat each delivered message as a user instruction for the current conversation. "
        "Acknowledge with POST /api/v1/agent/messages/{id}/ack, then report completion with "
        ".../processed. For interrupts, stop at the next safe point, preserve work, and "
        "acknowledge with POST /api/v1/agent/interrupts/{id}/ack."
    )


class AgentStatusUpdate(BaseModel):
    project: str | None = Field(default=None, max_length=200)
    stage: str | None = Field(default=None, max_length=200)
    activity: str | None = Field(default=None, max_length=1000)
    last_milestone: str | None = Field(default=None, max_length=300)
    next_action: str | None = Field(default=None, max_length=300)
    blockers: list[str] | None = Field(default=None, max_length=20)
    awaiting_input: bool | None = None
    state_override: Literal["idle", "working", "completed", "failed"] | None = None
    progress: float | None = Field(default=None, ge=0, le=1)
    session_id: str | None = Field(default=None, max_length=80)


class ScreenshotMeta(BaseModel):
    id: str
    caption: str = ""
    source: str = "upload"
    content_type: str
    bytes: int
    width: int | None = None
    height: int | None = None
    created_at: float
    expires_at: float
    url: str
    sha256: str
    expired: bool = False


class MilestoneModel(BaseModel):
    id: str
    seq: int
    title: str
    summary: str = ""
    changes: list[str] = Field(default_factory=list)
    phase: str = ""
    created_at: float
    screenshots: list[ScreenshotMeta] = Field(default_factory=list)
    expired_screenshots: int = 0


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=4000)
    changes: list[str] = Field(default_factory=list, max_length=30)
    phase: str = Field(default="", max_length=80)
    screenshots: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="Capture ids from POST /api/v1/screenshots/capture to attach",
    )


class ServerCpu(BaseModel):
    percent: float | None = None
    per_core: list[float] = Field(default_factory=list)
    load: list[float] = Field(default_factory=list)
    temperature_c: float | None = None
    model: str = ""
    cores: int = 0


class ServerMemory(BaseModel):
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent: float
    swap_total_bytes: int
    swap_used_bytes: int
    swap_percent: float


class ServerGpu(BaseModel):
    available: bool = False
    name: str | None = None
    utilization_percent: float | None = None
    temperature_c: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None
    power_w: float | None = None
    error: str | None = None


class DiskUsage(BaseModel):
    mount: str
    filesystem: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


class NetworkThroughput(BaseModel):
    interface: str
    rx_bytes_per_second: float
    tx_bytes_per_second: float
    rx_bytes_total: int
    tx_bytes_total: int


class DockerContainerInfo(BaseModel):
    name: str
    image: str = ""
    state: str = "unknown"
    status: str = ""
    health: str | None = None
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    memory_limit_bytes: int | None = None
    started_at: float | None = None
    error: str | None = None


class ServerOverview(BaseModel):
    generated_at: float
    uptime_seconds: float | None = None
    cpu: ServerCpu = Field(default_factory=ServerCpu)
    memory: ServerMemory | None = None
    gpu: ServerGpu = Field(default_factory=ServerGpu)
    disks: list[DiskUsage] = Field(default_factory=list)
    network: NetworkThroughput | None = None
    docker: list[DockerContainerInfo] = Field(default_factory=list)
    docker_available: bool = False
    docker_error: str | None = None
    unavailable: list[str] = Field(default_factory=list)


class ServiceStatus(BaseModel):
    key: str
    label: str
    state: Literal["up", "degraded", "down", "unavailable", "unknown"]
    summary: str = ""
    detail: str | None = None
    checked_at: float
    latency_ms: float | None = None


class DomainCount(BaseModel):
    name: str
    count: int


class UpstreamInfo(BaseModel):
    name: str
    address: str = ""
    count: int = 0
    response_avg_ms: float | None = None


class PiholeStatus(BaseModel):
    available: bool
    online: bool
    blocking: str | None = None
    container: DockerContainerInfo | None = None
    queries_total: int | None = None
    queries_blocked: int | None = None
    percent_blocked: float | None = None
    unique_domains: int | None = None
    queries_forwarded: int | None = None
    queries_cached: int | None = None
    top_blocked_domains: list[DomainCount] = Field(default_factory=list)
    top_clients: list[DomainCount] = Field(default_factory=list)
    upstreams: list[UpstreamInfo] = Field(default_factory=list)
    generated_at: float
    error: str | None = None


class MinecraftControls(BaseModel):
    available: bool = False
    actions: list[str] = Field(default_factory=list)
    stop_method: str | None = None
    start_method: str | None = None
    reason: str | None = None


class MinecraftStatus(BaseModel):
    available: bool
    online: bool
    state: Literal["running", "stopped", "unreachable", "unknown"]
    version: str | None = None
    protocol: int | None = None
    motd: str | None = None
    players_online: int | None = None
    players_max: int | None = None
    players: list[str] = Field(default_factory=list)
    uptime_seconds: float | None = None
    pid: int | None = None
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    tps: float | None = None
    mspt: float | None = None
    tick_metrics_note: str | None = None
    recent_errors: list[str] = Field(default_factory=list)
    recent_events: list[str] = Field(default_factory=list)
    log_updated_at: float | None = None
    last_backup_at: float | None = None
    backup_note: str | None = None
    controls: MinecraftControls = Field(default_factory=MinecraftControls)
    generated_at: float
    error: str | None = None


class NotificationModel(BaseModel):
    id: str
    kind: str
    severity: str
    title: str
    body: str = ""
    created_at: float
    read_at: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ActivityFeed(BaseModel):
    unread: int
    items: list[NotificationModel] = Field(default_factory=list)


class DashboardSummary(BaseModel):
    generated_at: float
    agent: AgentStatusResponse
    services: list[ServiceStatus] = Field(default_factory=list)
    server: ServerOverview
    pihole: PiholeStatus
    minecraft: MinecraftStatus
    latest_milestone: MilestoneModel | None = None
    activity: ActivityFeed
    data_age_seconds: float | None = None


class CaptureRequest(BaseModel):
    source: Literal["text", "api", "window", "file"] = "text"
    title: str = Field(default="", max_length=120)
    command: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "For source=text: one of the allow-listed read-only commands "
            "(beacon doctor, beacon agent status, ...). Arbitrary commands are rejected."
        ),
    )
    path: str | None = Field(
        default=None,
        max_length=500,
        description="For source=file/window: absolute path under ~/beacon or a X11 window id",
    )
    caption: str = Field(default="", max_length=300)


class CaptureResult(BaseModel):
    capture_id: str
    source: str
    title: str
    bytes: int
    width: int | None = None
    height: int | None = None
    preview_url: str
    expires_at: float


class MilestoneScreenshotUpload(BaseModel):
    milestone_id: str
    uploaded: list[ScreenshotMeta] = Field(default_factory=list)
    rejected: list[dict[str, str]] = Field(default_factory=list)


class RetentionResult(BaseModel):
    deleted_screenshots: int
    deleted_files: int
    orphan_files_removed: int
    kept: int
    ran_at: float
    errors: list[str] = Field(default_factory=list)


class ErrorBody(BaseModel):
    error: str
    message: str
    detail: dict[str, Any] | None = None
