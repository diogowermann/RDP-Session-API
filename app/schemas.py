from datetime import datetime
from enum import Enum
from ipaddress import ip_address

from pydantic import BaseModel, Field, field_validator, model_validator


class EventType(str, Enum):
    LOGON = "LOGON"
    LOGOFF = "LOGOFF"
    DISCONNECT = "DISCONNECT"
    RECONNECT = "RECONNECT"


class SnapshotState(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONNECTED = "DISCONNECTED"


class RemoteProtocol(str, Enum):
    RDP = "RDP"
    SSH = "SSH"


class AgentPlatform(str, Enum):
    WINDOWS = "windows"
    LINUX = "linux"


def require_timezone(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must include an explicit UTC offset")
    return value


def normalize_source_ip(value: object) -> str | None:
    """Return a canonical usable IP or None without rejecting the payload."""
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.upper() == "LOCAL":
        return None

    try:
        address = ip_address(text)
    except ValueError:
        return None

    if address.is_loopback or address.is_unspecified:
        return None
    return str(address)


def normalize_source_port(value: object) -> int | None:
    """Normalize an optional source port without making telemetry invalid."""
    if value is None or value == "":
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if port < 1 or port > 65535:
        return None
    return port


class AgentEvent(BaseModel):
    event_id: int
    record_id: int = Field(ge=0)
    type: EventType
    session_id: int = Field(ge=0)
    username: str = Field(min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    source_ip: str | None = Field(default=None, max_length=45)
    source_port: int | None = None
    occurred_at: datetime
    channel: str = Field(
        default="Microsoft-Windows-TerminalServices-LocalSessionManager/Operational",
        min_length=1,
        max_length=255,
    )

    _source_ip_normalized = field_validator("source_ip", mode="before")(normalize_source_ip)
    _source_port_normalized = field_validator("source_port", mode="before")(normalize_source_port)
    _occurred_has_timezone = field_validator("occurred_at")(require_timezone)


class AgentEnvelope(BaseModel):
    contract_version: int = 1
    agent_version: str = Field(min_length=1, max_length=32)
    boot_time_utc: datetime
    agent_time_utc: datetime
    events: list[AgentEvent] = Field(min_length=1, max_length=500)

    _timestamps_have_timezone = field_validator("boot_time_utc", "agent_time_utc")(require_timezone)

    @field_validator("contract_version")
    @classmethod
    def only_contract_v1(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported contract version")
        return value


class SnapshotSession(BaseModel):
    session_id: int = Field(ge=0)
    username: str = Field(min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    state: SnapshotState
    logon_at: datetime | None = None
    source_ip: str | None = Field(default=None, max_length=45)

    _source_ip_normalized = field_validator("source_ip", mode="before")(normalize_source_ip)
    _logon_has_timezone = field_validator("logon_at")(require_timezone)


class AgentSnapshot(BaseModel):
    contract_version: int = 1
    agent_version: str = Field(min_length=1, max_length=32)
    boot_time_utc: datetime
    agent_time_utc: datetime
    hostname: str | None = Field(default=None, max_length=255)
    fqdn: str | None = Field(default=None, max_length=255)
    os_version: str | None = Field(default=None, max_length=128)
    sessions: list[SnapshotSession] = Field(default_factory=list, max_length=500)

    _timestamps_have_timezone = field_validator("boot_time_utc", "agent_time_utc")(require_timezone)

    @field_validator("contract_version")
    @classmethod
    def only_contract_v1(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported contract version")
        return value


class V2AgentEvent(BaseModel):
    type: EventType
    provider_session_id: str = Field(min_length=1, max_length=255)
    provider_event_id: str = Field(min_length=1, max_length=512)
    username: str = Field(min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    source_ip: str | None = Field(default=None, max_length=45)
    source_port: int | None = None
    occurred_at: datetime

    _source_ip_normalized = field_validator("source_ip", mode="before")(normalize_source_ip)
    _source_port_normalized = field_validator("source_port", mode="before")(normalize_source_port)
    _occurred_has_timezone = field_validator("occurred_at")(require_timezone)


class V2AgentEnvelope(BaseModel):
    contract_version: int = 2
    agent_version: str = Field(min_length=1, max_length=32)
    platform: AgentPlatform
    protocol: RemoteProtocol
    boot_id: str = Field(min_length=1, max_length=255)
    agent_time_utc: datetime
    events: list[V2AgentEvent] = Field(min_length=1, max_length=500)

    _agent_time_has_timezone = field_validator("agent_time_utc")(require_timezone)

    @field_validator("contract_version")
    @classmethod
    def only_contract_v2(cls, value: int) -> int:
        if value != 2:
            raise ValueError("unsupported contract version")
        return value

    @model_validator(mode="after")
    def validate_protocol_event_semantics(self) -> "V2AgentEnvelope":
        if self.protocol == RemoteProtocol.SSH:
            invalid = [event.type.value for event in self.events if event.type not in (EventType.LOGON, EventType.LOGOFF)]
            if invalid:
                raise ValueError("SSH v2 currently supports LOGON and LOGOFF events only")
        return self


class V2SnapshotSession(BaseModel):
    provider_session_id: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    state: SnapshotState
    logon_at: datetime | None = None
    source_ip: str | None = Field(default=None, max_length=45)
    source_port: int | None = None

    _source_ip_normalized = field_validator("source_ip", mode="before")(normalize_source_ip)
    _source_port_normalized = field_validator("source_port", mode="before")(normalize_source_port)
    _logon_has_timezone = field_validator("logon_at")(require_timezone)


class V2AgentSnapshot(BaseModel):
    contract_version: int = 2
    agent_version: str = Field(min_length=1, max_length=32)
    platform: AgentPlatform
    protocol: RemoteProtocol
    boot_id: str = Field(min_length=1, max_length=255)
    agent_time_utc: datetime
    hostname: str | None = Field(default=None, max_length=255)
    fqdn: str | None = Field(default=None, max_length=255)
    os_version: str | None = Field(default=None, max_length=128)
    sessions: list[V2SnapshotSession] = Field(default_factory=list, max_length=500)

    _agent_time_has_timezone = field_validator("agent_time_utc")(require_timezone)

    @field_validator("contract_version")
    @classmethod
    def only_contract_v2(cls, value: int) -> int:
        if value != 2:
            raise ValueError("unsupported contract version")
        return value


class IngestResult(BaseModel):
    accepted: int
    duplicates: int


class SnapshotResult(BaseModel):
    observed: int
    created: int
    updated: int
    closed: int


class ServerItem(BaseModel):
    id: str
    hostname: str | None
    fqdn: str | None
    os_version: str | None
    agent_version: str | None
    enabled: bool
    last_seen_at: datetime | None
    last_snapshot_at: datetime | None
    last_boot_at: datetime | None


class ServerSummary(BaseModel):
    server: ServerItem
    active_users: int
    active_sessions: int
    disconnected_sessions: int
    open_sessions: int


class SessionItem(BaseModel):
    id: str
    server_id: str
    windows_session_id: int
    username: str
    domain: str | None
    state: str
    logon_at: datetime | None
    logoff_at: datetime | None
    duration_minutes: int | None
    disconnect_count: int
    end_reason: str | None


class SessionPage(BaseModel):
    items: list[SessionItem]
    limit: int
    offset: int


class LogonAlertItem(BaseModel):
    alert_id: str
    server_id: str
    hostname: str
    principal: str
    username: str
    domain: str | None
    logon_at: datetime
    alert_value: int = Field(default=1, ge=1, le=1)


class V2ServerItem(BaseModel):
    id: str
    hostname: str | None
    fqdn: str | None
    os_version: str | None
    agent_version: str | None
    platform: str | None
    enabled: bool
    last_seen_at: datetime | None
    last_snapshot_at: datetime | None
    last_boot_id: str | None


class V2SessionItem(BaseModel):
    id: str
    server_id: str
    protocol: str
    platform: str
    provider_session_id: str
    username: str
    domain: str | None
    state: str
    logon_at: datetime | None
    logoff_at: datetime | None
    duration_minutes: int | None
    disconnect_count: int
    end_reason: str | None
    initial_source_ip: str | None
    last_source_ip: str | None
    correlation_status: str | None


class V2SessionPage(BaseModel):
    items: list[V2SessionItem]
    limit: int
    offset: int


class V2LogonAlertItem(BaseModel):
    alert_id: str
    server_id: str
    hostname: str
    protocol: str
    platform: str
    principal: str
    username: str
    domain: str | None
    source_ip: str | None
    logon_at: datetime
    alert_value: int = Field(default=1, ge=1, le=1)
