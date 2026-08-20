from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    LOGON = "LOGON"
    LOGOFF = "LOGOFF"
    DISCONNECT = "DISCONNECT"
    RECONNECT = "RECONNECT"


class SnapshotState(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONNECTED = "DISCONNECTED"


def require_timezone(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must include an explicit UTC offset")
    return value


class AgentEvent(BaseModel):
    event_id: int
    record_id: int = Field(ge=0)
    type: EventType
    session_id: int = Field(ge=0)
    username: str = Field(min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    occurred_at: datetime
    channel: str = Field(
        default="Microsoft-Windows-TerminalServices-LocalSessionManager/Operational",
        min_length=1,
        max_length=255,
    )

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


class IngestResult(BaseModel):
    accepted: int
    duplicates: int


class SnapshotResult(BaseModel):
    observed: int
    created: int
    updated: int
    closed: int
