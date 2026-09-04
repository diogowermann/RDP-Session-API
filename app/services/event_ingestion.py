import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Server, SessionEvent
from app.schemas import AgentEnvelope, IngestResult, V2AgentEnvelope
from app.services.normalization import (
    NormalizedEnvelope,
    NormalizedEvent,
    normalize_v1_envelope,
    normalize_v2_envelope,
)
from app.services.session_state import apply_normalized_event, close_previous_boot_sessions_common
from app.timeutils import normalize_boot_time, to_utc_naive, utc_now


def event_fingerprint(server_id: str, envelope: AgentEnvelope, event) -> str:
    """Preserve the v1 fingerprint exactly for replay compatibility."""
    value = "|".join(
        [
            server_id,
            event.channel,
            str(event.record_id),
            str(event.event_id),
            str(event.session_id),
            normalize_boot_time(envelope.boot_time_utc).isoformat(),
            event.occurred_at.isoformat(),
        ]
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalized_event_fingerprint(server_id: str, envelope: NormalizedEnvelope, event: NormalizedEvent) -> str:
    if envelope.contract_version == 1 and all(
        value is not None
        for value in (
            event.legacy_channel,
            event.legacy_record_id,
            event.legacy_event_id,
            event.legacy_session_id,
            envelope.boot_time_utc,
        )
    ):
        value = "|".join(
            [
                server_id,
                str(event.legacy_channel),
                str(event.legacy_record_id),
                str(event.legacy_event_id),
                str(event.legacy_session_id),
                normalize_boot_time(envelope.boot_time_utc).isoformat(),
                event.occurred_at.isoformat(),
            ]
        )
    else:
        value = "|".join(
            [
                server_id,
                envelope.platform,
                envelope.protocol,
                envelope.boot_id,
                event.provider_event_id,
                event.type.value,
                event.provider_session_id,
            ]
        )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _legacy_int(value: str, fallback: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    if parsed < 0 or parsed > 2_147_483_647:
        return fallback
    return parsed


def _compat_boot_time(envelope: NormalizedEnvelope, event: NormalizedEvent) -> datetime:
    if envelope.boot_time_utc is not None:
        return normalize_boot_time(envelope.boot_time_utc)
    return to_utc_naive(event.occurred_at)


def ingest_normalized_events(
    db: Session,
    *,
    server: Server,
    envelope: NormalizedEnvelope,
) -> IngestResult:
    close_previous_boot_sessions_common(
        db,
        server,
        boot_id=envelope.boot_id,
        observed_at=envelope.agent_time_utc,
        boot_time=envelope.boot_time_utc,
    )
    server.agent_version = envelope.agent_version
    server.platform = envelope.platform
    server.last_seen_at = utc_now()

    accepted = 0
    duplicates = 0
    for event in sorted(envelope.events, key=lambda item: (item.occurred_at, item.provider_event_id)):
        fingerprint = normalized_event_fingerprint(server.id, envelope, event)
        existing = db.scalar(select(SessionEvent.id).where(SessionEvent.event_fingerprint == fingerprint))
        if existing is not None:
            duplicates += 1
            continue

        db.add(
            SessionEvent(
                server_id=server.id,
                protocol=envelope.protocol,
                platform=envelope.platform,
                provider_session_id=event.provider_session_id,
                provider_event_id=event.provider_event_id,
                boot_id=envelope.boot_id,
                event_type=event.type.value,
                event_channel=event.legacy_channel or f"v2:{envelope.protocol.lower()}",
                event_id=event.legacy_event_id if event.legacy_event_id is not None else 0,
                event_record_id=(
                    event.legacy_record_id
                    if event.legacy_record_id is not None
                    else _legacy_int(event.provider_event_id)
                ),
                windows_session_id=(
                    event.legacy_session_id
                    if event.legacy_session_id is not None
                    else _legacy_int(event.provider_session_id)
                ),
                username=event.username,
                domain=event.domain,
                boot_time=_compat_boot_time(envelope, event),
                occurred_at=to_utc_naive(event.occurred_at),
                source_ip=event.source_ip,
                source_port=event.source_port,
                event_fingerprint=fingerprint,
                payload_version=envelope.contract_version,
            )
        )
        apply_normalized_event(
            db,
            server=server,
            platform=envelope.platform,
            protocol=envelope.protocol,
            boot_id=envelope.boot_id,
            boot_time=envelope.boot_time_utc,
            event=event,
        )
        db.flush()
        accepted += 1

    db.commit()
    return IngestResult(accepted=accepted, duplicates=duplicates)


def ingest_events(db: Session, *, server: Server, envelope: AgentEnvelope) -> IngestResult:
    return ingest_normalized_events(db, server=server, envelope=normalize_v1_envelope(envelope))


def ingest_v2_events(db: Session, *, server: Server, envelope: V2AgentEnvelope) -> IngestResult:
    return ingest_normalized_events(db, server=server, envelope=normalize_v2_envelope(envelope))
