import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Server, SessionEvent
from app.schemas import AgentEnvelope, IngestResult
from app.services.session_state import apply_event, close_previous_boot_sessions
from app.timeutils import to_utc_naive, utc_now


def event_fingerprint(server_id: str, envelope: AgentEnvelope, event) -> str:
    value = "|".join(
        [
            server_id,
            event.channel,
            str(event.record_id),
            str(event.event_id),
            str(event.session_id),
            envelope.boot_time_utc.isoformat(),
            event.occurred_at.isoformat(),
        ]
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ingest_events(db: Session, *, server: Server, envelope: AgentEnvelope) -> IngestResult:
    close_previous_boot_sessions(db, server, envelope.boot_time_utc)
    server.agent_version = envelope.agent_version
    server.last_seen_at = utc_now()

    accepted = 0
    duplicates = 0
    for event in sorted(envelope.events, key=lambda item: (item.occurred_at, item.record_id)):
        fingerprint = event_fingerprint(server.id, envelope, event)
        existing = db.scalar(select(SessionEvent.id).where(SessionEvent.event_fingerprint == fingerprint))
        if existing is not None:
            duplicates += 1
            continue

        db.add(
            SessionEvent(
                server_id=server.id,
                event_type=event.type.value,
                event_channel=event.channel,
                event_id=event.event_id,
                event_record_id=event.record_id,
                windows_session_id=event.session_id,
                username=event.username,
                domain=event.domain,
                boot_time=to_utc_naive(envelope.boot_time_utc),
                occurred_at=to_utc_naive(event.occurred_at),
                event_fingerprint=fingerprint,
                payload_version=envelope.contract_version,
            )
        )
        apply_event(db, server=server, boot_time=envelope.boot_time_utc, event=event)
        db.flush()
        accepted += 1

    db.commit()
    return IngestResult(accepted=accepted, duplicates=duplicates)
