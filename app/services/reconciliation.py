from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RdpSession, Server
from app.schemas import AgentSnapshot, SnapshotResult, V2AgentSnapshot
from app.services.normalization import (
    NormalizedSnapshot,
    NormalizedSnapshotSession,
    normalize_v1_snapshot,
    normalize_v2_snapshot,
)
from app.services.session_state import OPEN_STATES, close_previous_boot_sessions_common, find_open_session_common
from app.timeutils import duration_minutes, normalize_boot_time, to_utc_naive, utc_now


def _legacy_session_id(observed: NormalizedSnapshotSession) -> int:
    if observed.legacy_session_id is not None:
        return observed.legacy_session_id
    try:
        parsed = int(observed.provider_session_id)
    except (TypeError, ValueError):
        return 0
    if parsed < 0 or parsed > 2_147_483_647:
        return 0
    return parsed


def _compat_boot_time(snapshot: NormalizedSnapshot, observed: NormalizedSnapshotSession):
    if snapshot.boot_time_utc is not None:
        return normalize_boot_time(snapshot.boot_time_utc)
    if observed.logon_at is not None:
        return to_utc_naive(observed.logon_at)
    return to_utc_naive(snapshot.agent_time_utc)


def reconcile_normalized_snapshot(
    db: Session,
    *,
    server: Server,
    snapshot: NormalizedSnapshot,
) -> SnapshotResult:
    closed = close_previous_boot_sessions_common(
        db,
        server,
        boot_id=snapshot.boot_id,
        observed_at=snapshot.agent_time_utc,
        boot_time=snapshot.boot_time_utc,
    )

    server.hostname = snapshot.hostname or server.hostname
    server.fqdn = snapshot.fqdn or server.fqdn
    server.os_version = snapshot.os_version or server.os_version
    server.agent_version = snapshot.agent_version
    server.platform = snapshot.platform
    server.last_seen_at = utc_now()
    server.last_snapshot_at = to_utc_naive(snapshot.agent_time_utc)

    seen_session_ids: set[str] = set()
    created = 0
    updated = 0

    for observed in snapshot.sessions:
        session = find_open_session_common(
            db,
            server_id=server.id,
            protocol=snapshot.protocol,
            boot_id=snapshot.boot_id,
            provider_session_id=observed.provider_session_id,
            username=observed.username,
            domain=observed.domain,
        )
        if session is None:
            session = RdpSession(
                server_id=server.id,
                protocol=snapshot.protocol,
                platform=snapshot.platform,
                provider_session_id=observed.provider_session_id,
                boot_id=snapshot.boot_id,
                windows_session_id=_legacy_session_id(observed),
                username=observed.username,
                domain=observed.domain,
                boot_time=_compat_boot_time(snapshot, observed),
                state=observed.state.value,
                logon_at=to_utc_naive(observed.logon_at) if observed.logon_at else None,
                last_connected_at=(
                    to_utc_naive(observed.logon_at)
                    if observed.logon_at and observed.state.value == "ACTIVE"
                    else None
                ),
                last_disconnected_at=(
                    to_utc_naive(snapshot.agent_time_utc)
                    if observed.state.value == "DISCONNECTED"
                    else None
                ),
                initial_source_ip=observed.source_ip,
                last_source_ip=observed.source_ip,
            )
            db.add(session)
            db.flush()
            created += 1
        else:
            if session.state != observed.state.value:
                session.state = observed.state.value
                if observed.state.value == "ACTIVE":
                    session.last_connected_at = to_utc_naive(snapshot.agent_time_utc)
                else:
                    session.last_disconnected_at = to_utc_naive(snapshot.agent_time_utc)
            session.logon_at = session.logon_at or (
                to_utc_naive(observed.logon_at) if observed.logon_at else None
            )
            if observed.source_ip is not None:
                session.last_source_ip = observed.source_ip
            updated += 1
        seen_session_ids.add(session.id)

    open_sessions = db.scalars(
        select(RdpSession).where(
            RdpSession.server_id == server.id,
            RdpSession.protocol == snapshot.protocol,
            RdpSession.platform == snapshot.platform,
            RdpSession.boot_id == snapshot.boot_id,
            RdpSession.state.in_(OPEN_STATES),
        )
    ).all()
    for session in open_sessions:
        if session.id in seen_session_ids:
            continue
        session.state = "CLOSED"
        session.logoff_at = to_utc_naive(snapshot.agent_time_utc)
        session.end_reason = "RECONCILIATION"
        if session.logon_at is not None:
            session.duration_minutes = duration_minutes(session.logon_at, snapshot.agent_time_utc)
        closed += 1

    db.commit()
    return SnapshotResult(observed=len(snapshot.sessions), created=created, updated=updated, closed=closed)


def reconcile_snapshot(db: Session, *, server: Server, snapshot: AgentSnapshot) -> SnapshotResult:
    return reconcile_normalized_snapshot(db, server=server, snapshot=normalize_v1_snapshot(snapshot))


def reconcile_v2_snapshot(db: Session, *, server: Server, snapshot: V2AgentSnapshot) -> SnapshotResult:
    return reconcile_normalized_snapshot(db, server=server, snapshot=normalize_v2_snapshot(snapshot))
