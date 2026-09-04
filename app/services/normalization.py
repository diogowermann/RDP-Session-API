from dataclasses import dataclass
from datetime import datetime

from app.schemas import (
    AgentEnvelope,
    AgentSnapshot,
    EventType,
    SnapshotState,
    V2AgentEnvelope,
    V2AgentSnapshot,
)
from app.timeutils import normalize_boot_time


@dataclass(frozen=True)
class NormalizedEvent:
    type: EventType
    provider_session_id: str
    provider_event_id: str
    username: str
    domain: str | None
    source_ip: str | None
    source_port: int | None
    occurred_at: datetime
    legacy_event_id: int | None = None
    legacy_record_id: int | None = None
    legacy_session_id: int | None = None
    legacy_channel: str | None = None


@dataclass(frozen=True)
class NormalizedEnvelope:
    contract_version: int
    agent_version: str
    platform: str
    protocol: str
    boot_id: str
    agent_time_utc: datetime
    events: tuple[NormalizedEvent, ...]
    boot_time_utc: datetime | None = None


@dataclass(frozen=True)
class NormalizedSnapshotSession:
    provider_session_id: str
    username: str
    domain: str | None
    state: SnapshotState
    logon_at: datetime | None
    source_ip: str | None
    source_port: int | None = None
    legacy_session_id: int | None = None


@dataclass(frozen=True)
class NormalizedSnapshot:
    contract_version: int
    agent_version: str
    platform: str
    protocol: str
    boot_id: str
    agent_time_utc: datetime
    hostname: str | None
    fqdn: str | None
    os_version: str | None
    sessions: tuple[NormalizedSnapshotSession, ...]
    boot_time_utc: datetime | None = None


def v1_boot_id(value: datetime) -> str:
    return normalize_boot_time(value).strftime("%Y-%m-%d %H:%M:%S")


def normalize_v1_envelope(envelope: AgentEnvelope) -> NormalizedEnvelope:
    return NormalizedEnvelope(
        contract_version=1,
        agent_version=envelope.agent_version,
        platform="windows",
        protocol="RDP",
        boot_id=v1_boot_id(envelope.boot_time_utc),
        boot_time_utc=envelope.boot_time_utc,
        agent_time_utc=envelope.agent_time_utc,
        events=tuple(
            NormalizedEvent(
                type=event.type,
                provider_session_id=str(event.session_id),
                provider_event_id=str(event.record_id),
                username=event.username,
                domain=event.domain,
                source_ip=event.source_ip,
                source_port=event.source_port,
                occurred_at=event.occurred_at,
                legacy_event_id=event.event_id,
                legacy_record_id=event.record_id,
                legacy_session_id=event.session_id,
                legacy_channel=event.channel,
            )
            for event in envelope.events
        ),
    )


def normalize_v2_envelope(envelope: V2AgentEnvelope) -> NormalizedEnvelope:
    return NormalizedEnvelope(
        contract_version=2,
        agent_version=envelope.agent_version,
        platform=envelope.platform.value,
        protocol=envelope.protocol.value,
        boot_id=envelope.boot_id,
        agent_time_utc=envelope.agent_time_utc,
        events=tuple(
            NormalizedEvent(
                type=event.type,
                provider_session_id=event.provider_session_id,
                provider_event_id=event.provider_event_id,
                username=event.username,
                domain=event.domain,
                source_ip=event.source_ip,
                source_port=event.source_port,
                occurred_at=event.occurred_at,
            )
            for event in envelope.events
        ),
    )


def normalize_v1_snapshot(snapshot: AgentSnapshot) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        contract_version=1,
        agent_version=snapshot.agent_version,
        platform="windows",
        protocol="RDP",
        boot_id=v1_boot_id(snapshot.boot_time_utc),
        boot_time_utc=snapshot.boot_time_utc,
        agent_time_utc=snapshot.agent_time_utc,
        hostname=snapshot.hostname,
        fqdn=snapshot.fqdn,
        os_version=snapshot.os_version,
        sessions=tuple(
            NormalizedSnapshotSession(
                provider_session_id=str(observed.session_id),
                username=observed.username,
                domain=observed.domain,
                state=observed.state,
                logon_at=observed.logon_at,
                source_ip=observed.source_ip,
                legacy_session_id=observed.session_id,
            )
            for observed in snapshot.sessions
        ),
    )


def normalize_v2_snapshot(snapshot: V2AgentSnapshot) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        contract_version=2,
        agent_version=snapshot.agent_version,
        platform=snapshot.platform.value,
        protocol=snapshot.protocol.value,
        boot_id=snapshot.boot_id,
        agent_time_utc=snapshot.agent_time_utc,
        hostname=snapshot.hostname,
        fqdn=snapshot.fqdn,
        os_version=snapshot.os_version,
        sessions=tuple(
            NormalizedSnapshotSession(
                provider_session_id=observed.provider_session_id,
                username=observed.username,
                domain=observed.domain,
                state=observed.state,
                logon_at=observed.logon_at,
                source_ip=observed.source_ip,
                source_port=observed.source_port,
            )
            for observed in snapshot.sessions
        ),
    )
