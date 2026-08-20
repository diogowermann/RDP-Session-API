from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RdpSession, Server
from app.schemas import AgentEvent, EventType
from app.timeutils import duration_minutes, to_utc_naive


OPEN_STATES = ("ACTIVE", "DISCONNECTED")


def _same_user(session: RdpSession, username: str, domain: str | None) -> bool:
    return session.username.casefold() == username.casefold() and (session.domain or "").casefold() == (domain or "").casefold()


def find_open_session(
    db: Session,
    *,
    server_id: str,
    boot_time: datetime,
    windows_session_id: int,
    username: str,
    domain: str | None,
) -> RdpSession | None:
    candidates = db.scalars(
        select(RdpSession).where(
            RdpSession.server_id == server_id,
            RdpSession.boot_time == to_utc_naive(boot_time),
            RdpSession.windows_session_id == windows_session_id,
            RdpSession.state.in_(OPEN_STATES),
        )
    ).all()
    return next((session for session in candidates if _same_user(session, username, domain)), None)


def close_previous_boot_sessions(db: Session, server: Server, boot_time: datetime) -> int:
    boot_time = to_utc_naive(boot_time)
    if server.last_boot_at is None or server.last_boot_at == boot_time:
        server.last_boot_at = boot_time
        return 0

    open_sessions = db.scalars(
        select(RdpSession).where(
            RdpSession.server_id == server.id,
            RdpSession.state.in_(OPEN_STATES),
            RdpSession.boot_time != boot_time,
        )
    ).all()
    for session in open_sessions:
        session.state = "CLOSED"
        session.logoff_at = boot_time
        session.end_reason = "REBOOT"
        if session.logon_at is not None:
            session.duration_minutes = duration_minutes(session.logon_at, boot_time)

    server.last_boot_at = boot_time
    return len(open_sessions)


def apply_event(db: Session, *, server: Server, boot_time: datetime, event: AgentEvent) -> None:
    session = find_open_session(
        db,
        server_id=server.id,
        boot_time=boot_time,
        windows_session_id=event.session_id,
        username=event.username,
        domain=event.domain,
    )

    if event.type == EventType.LOGON:
        if session is None:
            session = RdpSession(
                server_id=server.id,
                windows_session_id=event.session_id,
                username=event.username,
                domain=event.domain,
                boot_time=to_utc_naive(boot_time),
                state="ACTIVE",
                logon_at=to_utc_naive(event.occurred_at),
                last_connected_at=to_utc_naive(event.occurred_at),
            )
            db.add(session)
        else:
            session.state = "ACTIVE"
            session.logon_at = session.logon_at or to_utc_naive(event.occurred_at)
            session.last_connected_at = to_utc_naive(event.occurred_at)
        return

    if session is None:
        return

    if event.type == EventType.DISCONNECT:
        session.state = "DISCONNECTED"
        session.last_disconnected_at = to_utc_naive(event.occurred_at)
        session.disconnect_count += 1
    elif event.type == EventType.RECONNECT:
        session.state = "ACTIVE"
        session.last_connected_at = to_utc_naive(event.occurred_at)
    elif event.type == EventType.LOGOFF:
        session.state = "CLOSED"
        session.logoff_at = to_utc_naive(event.occurred_at)
        session.end_reason = "LOGOFF"
        if session.logon_at is not None:
            session.duration_minutes = duration_minutes(session.logon_at, event.occurred_at)
