from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RdpSession, Server
from app.schemas import AgentEvent, EventType
from app.services.normalization import NormalizedEvent, v1_boot_id
from app.timeutils import duration_minutes, normalize_boot_time, to_utc_naive


OPEN_STATES = ("ACTIVE", "DISCONNECTED")


def _same_user(session: RdpSession, username: str, domain: str | None) -> bool:
    return session.username.casefold() == username.casefold() and (session.domain or "").casefold() == (domain or "").casefold()


def _apply_connected_source(session: RdpSession, source_ip: str | None, *, allow_initial: bool) -> None:
    if source_ip is None:
        return
    if allow_initial and session.initial_source_ip is None:
        session.initial_source_ip = source_ip
    session.last_source_ip = source_ip


def _legacy_session_id(provider_session_id: str, legacy_session_id: int | None) -> int:
    if legacy_session_id is not None:
        return legacy_session_id
    try:
        parsed = int(provider_session_id)
    except (TypeError, ValueError):
        return 0
    if parsed < 0 or parsed > 2_147_483_647:
        return 0
    return parsed


def _compat_boot_time(boot_time: datetime | None, event_time: datetime) -> datetime:
    if boot_time is not None:
        return normalize_boot_time(boot_time)
    return to_utc_naive(event_time)


def find_open_session_common(
    db: Session,
    *,
    server_id: str,
    protocol: str,
    boot_id: str,
    provider_session_id: str,
    username: str,
    domain: str | None,
) -> RdpSession | None:
    candidates = db.scalars(
        select(RdpSession).where(
            RdpSession.server_id == server_id,
            RdpSession.protocol == protocol,
            RdpSession.boot_id == boot_id,
            RdpSession.provider_session_id == provider_session_id,
            RdpSession.state.in_(OPEN_STATES),
        )
    ).all()
    return next((session for session in candidates if _same_user(session, username, domain)), None)




def find_latest_session_common(
    db: Session,
    *,
    server_id: str,
    protocol: str,
    boot_id: str,
    provider_session_id: str,
    username: str,
    domain: str | None,
) -> RdpSession | None:
    candidates = db.scalars(
        select(RdpSession)
        .where(
            RdpSession.server_id == server_id,
            RdpSession.protocol == protocol,
            RdpSession.boot_id == boot_id,
            RdpSession.provider_session_id == provider_session_id,
        )
        .order_by(RdpSession.created_at.desc(), RdpSession.id.desc())
    ).all()
    return next((session for session in candidates if _same_user(session, username, domain)), None)


def find_open_session(
    db: Session,
    *,
    server_id: str,
    boot_time: datetime,
    windows_session_id: int,
    username: str,
    domain: str | None,
) -> RdpSession | None:
    return find_open_session_common(
        db,
        server_id=server_id,
        protocol="RDP",
        boot_id=v1_boot_id(boot_time),
        provider_session_id=str(windows_session_id),
        username=username,
        domain=domain,
    )


def close_previous_boot_sessions_common(
    db: Session,
    server: Server,
    *,
    boot_id: str,
    observed_at: datetime,
    boot_time: datetime | None = None,
) -> int:
    previous_boot_id = server.last_boot_id
    normalized_boot_time = normalize_boot_time(boot_time) if boot_time is not None else None

    same_legacy_boot = (
        normalized_boot_time is not None
        and server.last_boot_at is not None
        and normalize_boot_time(server.last_boot_at) == normalized_boot_time
    )
    if previous_boot_id is None or previous_boot_id == boot_id or same_legacy_boot:
        if same_legacy_boot and previous_boot_id != boot_id:
            legacy_open_sessions = db.scalars(
                select(RdpSession).where(
                    RdpSession.server_id == server.id,
                    RdpSession.state.in_(OPEN_STATES),
                    RdpSession.boot_time == normalized_boot_time,
                )
            ).all()
            for session in legacy_open_sessions:
                session.boot_id = boot_id
        server.last_boot_id = boot_id
        if normalized_boot_time is not None:
            server.last_boot_at = normalized_boot_time
        return 0

    closed_at = normalized_boot_time or to_utc_naive(observed_at)
    open_sessions = db.scalars(
        select(RdpSession).where(
            RdpSession.server_id == server.id,
            RdpSession.state.in_(OPEN_STATES),
            RdpSession.boot_id != boot_id,
        )
    ).all()
    for session in open_sessions:
        session.state = "CLOSED"
        session.logoff_at = closed_at
        session.end_reason = "REBOOT"
        if session.logon_at is not None:
            session.duration_minutes = duration_minutes(session.logon_at, closed_at)

    server.last_boot_id = boot_id
    if normalized_boot_time is not None:
        server.last_boot_at = normalized_boot_time
    return len(open_sessions)


def close_previous_boot_sessions(db: Session, server: Server, boot_time: datetime) -> int:
    return close_previous_boot_sessions_common(
        db,
        server,
        boot_id=v1_boot_id(boot_time),
        observed_at=boot_time,
        boot_time=boot_time,
    )


def apply_normalized_event(
    db: Session,
    *,
    server: Server,
    platform: str,
    protocol: str,
    boot_id: str,
    boot_time: datetime | None,
    event: NormalizedEvent,
) -> None:
    session = find_open_session_common(
        db,
        server_id=server.id,
        protocol=protocol,
        boot_id=boot_id,
        provider_session_id=event.provider_session_id,
        username=event.username,
        domain=event.domain,
    )

    event_time = to_utc_naive(event.occurred_at)

    if event.type == EventType.LOGON:
        if session is None:
            latest = find_latest_session_common(
                db,
                server_id=server.id,
                protocol=protocol,
                boot_id=boot_id,
                provider_session_id=event.provider_session_id,
                username=event.username,
                domain=event.domain,
            )
            if latest is not None and latest.state == "CLOSED" and latest.logoff_at is not None and event_time <= latest.logoff_at:
                return
            session = RdpSession(
                server_id=server.id,
                protocol=protocol,
                platform=platform,
                provider_session_id=event.provider_session_id,
                boot_id=boot_id,
                windows_session_id=_legacy_session_id(event.provider_session_id, event.legacy_session_id),
                username=event.username,
                domain=event.domain,
                boot_time=_compat_boot_time(boot_time, event.occurred_at),
                state="ACTIVE",
                logon_at=event_time,
                last_connected_at=event_time,
                initial_source_ip=event.source_ip,
                last_source_ip=event.source_ip,
            )
            db.add(session)
        else:
            session.state = "ACTIVE"
            session.logon_at = session.logon_at or event_time
            if event.source_ip is not None and session.initial_source_ip is None:
                session.initial_source_ip = event.source_ip
            if session.last_connected_at is None or event_time >= session.last_connected_at:
                session.last_connected_at = event_time
                if event.source_ip is not None:
                    session.last_source_ip = event.source_ip
        return

    if session is None:
        return

    if event.type == EventType.DISCONNECT:
        if session.last_connected_at is not None and event_time < session.last_connected_at:
            return
        if session.last_disconnected_at is None or event_time >= session.last_disconnected_at:
            session.state = "DISCONNECTED"
            session.last_disconnected_at = event_time
            session.disconnect_count += 1
    elif event.type == EventType.RECONNECT:
        if session.last_disconnected_at is not None and event_time < session.last_disconnected_at:
            return
        if session.last_connected_at is None or event_time >= session.last_connected_at:
            session.state = "ACTIVE"
            session.last_connected_at = event_time
            _apply_connected_source(session, event.source_ip, allow_initial=False)
    elif event.type == EventType.LOGOFF:
        if session.logon_at is not None and event_time < session.logon_at:
            return
        session.state = "CLOSED"
        session.logoff_at = event_time
        session.end_reason = "LOGOFF"
        if session.logon_at is not None:
            session.duration_minutes = duration_minutes(session.logon_at, event.occurred_at)


def apply_event(db: Session, *, server: Server, boot_time: datetime, event: AgentEvent) -> None:
    normalized = NormalizedEvent(
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
    apply_normalized_event(
        db,
        server=server,
        platform="windows",
        protocol="RDP",
        boot_id=v1_boot_id(boot_time),
        boot_time=boot_time,
        event=normalized,
    )
