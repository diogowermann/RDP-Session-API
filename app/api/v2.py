from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RdpSession, Server, SessionEvent
from app.schemas import (
    IngestResult,
    RemoteProtocol,
    SnapshotResult,
    V2AgentEnvelope,
    V2AgentSnapshot,
    V2LogonAlertItem,
    V2ServerItem,
    V2SessionItem,
    V2SessionPage,
)
from app.security import authenticate_agent, authenticate_query_api
from app.services.event_ingestion import ingest_v2_events
from app.services.reconciliation import reconcile_v2_snapshot
from app.timeutils import as_utc, duration_minutes, to_utc_naive, utc_now

router = APIRouter(tags=["v2"])


def _server_item(server: Server) -> V2ServerItem:
    return V2ServerItem(
        id=server.id,
        hostname=server.hostname,
        fqdn=server.fqdn,
        os_version=server.os_version,
        agent_version=server.agent_version,
        platform=server.platform,
        enabled=server.enabled,
        last_seen_at=as_utc(server.last_seen_at),
        last_snapshot_at=as_utc(server.last_snapshot_at),
        last_boot_id=server.last_boot_id,
    )


def _session_item(session: RdpSession, now: datetime | None = None) -> V2SessionItem:
    calculated_duration = session.duration_minutes
    if session.state != "CLOSED" and session.logon_at is not None:
        calculated_duration = duration_minutes(session.logon_at, now or utc_now())
    return V2SessionItem(
        id=session.id,
        server_id=session.server_id,
        protocol=session.protocol,
        platform=session.platform,
        provider_session_id=session.provider_session_id or str(session.windows_session_id),
        username=session.username,
        domain=session.domain,
        state=session.state,
        logon_at=as_utc(session.logon_at),
        logoff_at=as_utc(session.logoff_at),
        duration_minutes=calculated_duration,
        disconnect_count=session.disconnect_count,
        end_reason=session.end_reason,
        initial_source_ip=session.initial_source_ip,
        last_source_ip=session.last_source_ip,
        correlation_status=session.correlation_status,
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "contract": "v2"}


@router.post("/agent/events", response_model=IngestResult)
def post_events(
    payload: V2AgentEnvelope,
    server: Server = Depends(authenticate_agent),
    db: Session = Depends(get_db),
) -> IngestResult:
    return ingest_v2_events(db, server=server, envelope=payload)


@router.post("/agent/snapshot", response_model=SnapshotResult)
def post_snapshot(
    payload: V2AgentSnapshot,
    server: Server = Depends(authenticate_agent),
    db: Session = Depends(get_db),
) -> SnapshotResult:
    return reconcile_v2_snapshot(db, server=server, snapshot=payload)


@router.get("/servers", response_model=list[V2ServerItem], dependencies=[Depends(authenticate_query_api)])
def list_servers(db: Session = Depends(get_db)) -> list[V2ServerItem]:
    servers = db.scalars(select(Server).order_by(Server.hostname, Server.id)).all()
    return [_server_item(server) for server in servers]


@router.get(
    "/sessions/active",
    response_model=list[V2SessionItem],
    dependencies=[Depends(authenticate_query_api)],
)
def active_sessions(
    server_id: str | None = Query(default=None),
    protocol: RemoteProtocol | None = Query(default=None),
    username: str | None = Query(default=None, min_length=1, max_length=255),
    db: Session = Depends(get_db),
) -> list[V2SessionItem]:
    statement = select(RdpSession).where(RdpSession.state == "ACTIVE")
    if server_id is not None:
        statement = statement.where(RdpSession.server_id == server_id)
    if protocol is not None:
        statement = statement.where(RdpSession.protocol == protocol.value)
    if username is not None:
        statement = statement.where(func.lower(RdpSession.username) == username.lower())
    sessions = db.scalars(statement.order_by(RdpSession.logon_at, RdpSession.id)).all()
    now = utc_now()
    return [_session_item(session, now=now) for session in sessions]


@router.get(
    "/sessions/history",
    response_model=V2SessionPage,
    dependencies=[Depends(authenticate_query_api)],
)
def session_history(
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    server_id: str | None = Query(default=None),
    protocol: RemoteProtocol | None = Query(default=None),
    username: str | None = Query(default=None, min_length=1, max_length=255),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> V2SessionPage:
    statement = select(RdpSession).where(RdpSession.state == "CLOSED")
    if from_at is not None:
        statement = statement.where(RdpSession.logon_at >= to_utc_naive(from_at))
    if to_at is not None:
        statement = statement.where(RdpSession.logon_at <= to_utc_naive(to_at))
    if server_id is not None:
        statement = statement.where(RdpSession.server_id == server_id)
    if protocol is not None:
        statement = statement.where(RdpSession.protocol == protocol.value)
    if username is not None:
        statement = statement.where(func.lower(RdpSession.username) == username.lower())
    sessions = db.scalars(
        statement.order_by(RdpSession.logon_at.desc(), RdpSession.id).limit(limit).offset(offset)
    ).all()
    return V2SessionPage(items=[_session_item(session) for session in sessions], limit=limit, offset=offset)


@router.get(
    "/alerts/logons",
    response_model=list[V2LogonAlertItem],
    dependencies=[Depends(authenticate_query_api)],
)
def recent_logon_alerts(
    lookback_minutes: int = Query(default=5, ge=1, le=60),
    protocol: RemoteProtocol | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[V2LogonAlertItem]:
    cutoff = utc_now() - timedelta(minutes=lookback_minutes)
    statement = (
        select(SessionEvent, Server)
        .join(Server, Server.id == SessionEvent.server_id)
        .where(
            SessionEvent.event_type == "LOGON",
            SessionEvent.received_at >= cutoff,
            Server.enabled.is_(True),
        )
    )
    if protocol is not None:
        statement = statement.where(SessionEvent.protocol == protocol.value)
    rows = db.execute(statement.order_by(SessionEvent.received_at, SessionEvent.id)).all()

    return [
        V2LogonAlertItem(
            alert_id=event.id,
            server_id=server.id,
            hostname=server.hostname or server.fqdn or server.id,
            protocol=event.protocol,
            platform=event.platform,
            principal=f"{event.domain}\\{event.username}" if event.domain else event.username,
            username=event.username,
            domain=event.domain,
            source_ip=event.source_ip,
            logon_at=as_utc(event.occurred_at),
            alert_value=1,
        )
        for event, server in rows
    ]
