from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RdpSession, Server
from app.schemas import ServerItem, ServerSummary, SessionItem, SessionPage
from app.security import authenticate_query_api
from app.timeutils import as_utc, duration_minutes, to_utc_naive, utc_now

router = APIRouter(
    prefix="/servers",
    tags=["servers"],
    dependencies=[Depends(authenticate_query_api)],
)


def _get_server(db: Session, server_id: str) -> Server:
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="server not found")
    return server


def _server_item(server: Server) -> ServerItem:
    return ServerItem(
        id=server.id,
        hostname=server.hostname,
        fqdn=server.fqdn,
        os_version=server.os_version,
        agent_version=server.agent_version,
        enabled=server.enabled,
        last_seen_at=as_utc(server.last_seen_at),
        last_snapshot_at=as_utc(server.last_snapshot_at),
        last_boot_at=as_utc(server.last_boot_at),
    )


def _session_item(session: RdpSession, now: datetime | None = None) -> SessionItem:
    calculated_duration = session.duration_minutes
    if session.state != "CLOSED" and session.logon_at is not None:
        calculated_duration = duration_minutes(session.logon_at, now or utc_now())
    return SessionItem(
        id=session.id,
        server_id=session.server_id,
        windows_session_id=session.windows_session_id,
        username=session.username,
        domain=session.domain,
        state=session.state,
        logon_at=as_utc(session.logon_at),
        logoff_at=as_utc(session.logoff_at),
        duration_minutes=calculated_duration,
        disconnect_count=session.disconnect_count,
        end_reason=session.end_reason,
    )


@router.get("", response_model=list[ServerItem])
def list_servers(db: Session = Depends(get_db)) -> list[ServerItem]:
    servers = db.scalars(select(Server).order_by(Server.hostname, Server.id)).all()
    return [_server_item(server) for server in servers]


@router.get("/{server_id}/summary", response_model=ServerSummary)
def server_summary(server_id: str, db: Session = Depends(get_db)) -> ServerSummary:
    server = _get_server(db, server_id)
    sessions = db.scalars(
        select(RdpSession).where(
            RdpSession.server_id == server_id,
            RdpSession.state.in_(["ACTIVE", "DISCONNECTED"]),
        )
    ).all()
    active = [session for session in sessions if session.state == "ACTIVE"]
    disconnected = [session for session in sessions if session.state == "DISCONNECTED"]
    active_users = {(session.domain or "", session.username) for session in active}
    return ServerSummary(
        server=_server_item(server),
        active_users=len(active_users),
        active_sessions=len(active),
        disconnected_sessions=len(disconnected),
        open_sessions=len(sessions),
    )


@router.get("/{server_id}/sessions/active", response_model=list[SessionItem])
def active_sessions(server_id: str, db: Session = Depends(get_db)) -> list[SessionItem]:
    _get_server(db, server_id)
    sessions = db.scalars(
        select(RdpSession)
        .where(RdpSession.server_id == server_id, RdpSession.state == "ACTIVE")
        .order_by(RdpSession.logon_at, RdpSession.id)
    ).all()
    now = utc_now()
    return [_session_item(session, now=now) for session in sessions]


@router.get("/{server_id}/sessions/history", response_model=SessionPage)
def session_history(
    server_id: str,
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    username: str | None = Query(default=None, min_length=1, max_length=255),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SessionPage:
    _get_server(db, server_id)
    statement = select(RdpSession).where(
        RdpSession.server_id == server_id,
        RdpSession.state == "CLOSED",
    )
    if from_at is not None:
        statement = statement.where(RdpSession.logon_at >= to_utc_naive(from_at))
    if to_at is not None:
        statement = statement.where(RdpSession.logon_at <= to_utc_naive(to_at))
    if username is not None:
        statement = statement.where(func.lower(RdpSession.username) == username.lower())
    sessions = db.scalars(
        statement.order_by(RdpSession.logon_at.desc(), RdpSession.id).limit(limit).offset(offset)
    ).all()
    return SessionPage(items=[_session_item(session) for session in sessions], limit=limit, offset=offset)
