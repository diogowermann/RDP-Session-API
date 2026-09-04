from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CorrelationEvidence, RdpSession, Server, SessionEvent
from app.schemas import (
    IngestResult,
    RemoteProtocol,
    RemoteSessionState,
    SnapshotResult,
    V2AgentEnvelope,
    V2AgentSnapshot,
    V2CorrelationEvidenceItem,
    V2LogonAlertItem,
    V2ServerItem,
    V2SessionDetail,
    V2SessionEventItem,
    V2SessionListItem,
    V2SessionPage,
    V2SessionTimeline,
    normalize_source_ip,
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


def _session_item(session: RdpSession, server: Server, now: datetime | None = None) -> V2SessionListItem:
    calculated_duration = session.duration_minutes
    if session.state != "CLOSED" and session.logon_at is not None:
        calculated_duration = duration_minutes(session.logon_at, now or utc_now())
    return V2SessionListItem(
        id=session.id,
        server_id=session.server_id,
        protocol=session.protocol,
        platform=session.platform,
        provider_session_id=session.provider_session_id or str(session.windows_session_id),
        boot_id=session.boot_id,
        hostname=server.hostname or server.fqdn or server.id,
        fqdn=server.fqdn,
        username=session.username,
        domain=session.domain,
        state=session.state,
        logon_at=as_utc(session.logon_at),
        logoff_at=as_utc(session.logoff_at),
        last_connected_at=as_utc(session.last_connected_at),
        last_disconnected_at=as_utc(session.last_disconnected_at),
        duration_minutes=calculated_duration,
        disconnect_count=session.disconnect_count,
        end_reason=session.end_reason,
        initial_source_ip=session.initial_source_ip,
        last_source_ip=session.last_source_ip,
        correlation_status=session.correlation_status,
    )


def _evidence_item(evidence: CorrelationEvidence) -> V2CorrelationEvidenceItem:
    return V2CorrelationEvidenceItem(
        id=evidence.id,
        status=evidence.status,
        source_ip=evidence.source_ip,
        observed_at=as_utc(evidence.observed_at),
        source_device_id=evidence.source_device_id,
        integration_record_id=evidence.integration_record_id,
        asset_tag=evidence.asset_tag,
        method=evidence.method,
        confidence=evidence.confidence,
        reason_code=evidence.reason_code,
        created_at=as_utc(evidence.created_at),
    )


def _history_filters(
    *,
    from_at: datetime | None,
    to_at: datetime | None,
    server_id: str | None,
    hostname: str | None,
    protocol: RemoteProtocol | None,
    state: RemoteSessionState | None,
    username: str | None,
    provider_session_id: str | None,
    source_ip: str | None,
    correlation_status: str | None,
) -> list:
    filters = []

    normalized_from = to_utc_naive(from_at) if from_at is not None else None
    normalized_to = to_utc_naive(to_at) if to_at is not None else None
    if normalized_from is not None and normalized_to is not None and normalized_from > normalized_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'from' must be before or equal to 'to'",
        )

    if normalized_from is not None:
        filters.append(RdpSession.logon_at >= normalized_from)
    if normalized_to is not None:
        filters.append(RdpSession.logon_at <= normalized_to)
    if server_id is not None:
        filters.append(RdpSession.server_id == server_id)
    if hostname is not None:
        lowered_hostname = hostname.lower()
        filters.append(
            or_(
                func.lower(Server.hostname).contains(lowered_hostname),
                func.lower(Server.fqdn).contains(lowered_hostname),
            )
        )
    if protocol is not None:
        filters.append(RdpSession.protocol == protocol.value)
    if state is not None:
        filters.append(RdpSession.state == state.value)
    if username is not None:
        filters.append(func.lower(RdpSession.username) == username.lower())
    if provider_session_id is not None:
        filters.append(RdpSession.provider_session_id == provider_session_id)
    if source_ip is not None:
        normalized_source = normalize_source_ip(source_ip)
        if normalized_source is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="source_ip must be a usable IPv4 or IPv6 address",
            )
        filters.append(
            or_(
                RdpSession.initial_source_ip == normalized_source,
                RdpSession.last_source_ip == normalized_source,
            )
        )
    if correlation_status is not None:
        normalized_status = correlation_status.strip().upper()
        if normalized_status == "NONE":
            filters.append(RdpSession.correlation_status.is_(None))
        else:
            filters.append(func.upper(RdpSession.correlation_status) == normalized_status)

    return filters


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
    response_model=list[V2SessionListItem],
    dependencies=[Depends(authenticate_query_api)],
)
def active_sessions(
    server_id: str | None = Query(default=None),
    protocol: RemoteProtocol | None = Query(default=None),
    username: str | None = Query(default=None, min_length=1, max_length=255),
    db: Session = Depends(get_db),
) -> list[V2SessionListItem]:
    statement = (
        select(RdpSession, Server)
        .join(Server, Server.id == RdpSession.server_id)
        .where(RdpSession.state == "ACTIVE")
    )
    if server_id is not None:
        statement = statement.where(RdpSession.server_id == server_id)
    if protocol is not None:
        statement = statement.where(RdpSession.protocol == protocol.value)
    if username is not None:
        statement = statement.where(func.lower(RdpSession.username) == username.lower())
    rows = db.execute(statement.order_by(RdpSession.logon_at, RdpSession.id)).all()
    now = utc_now()
    return [_session_item(session, server, now=now) for session, server in rows]


@router.get(
    "/sessions/history",
    response_model=V2SessionPage,
    dependencies=[Depends(authenticate_query_api)],
)
def session_history(
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    server_id: str | None = Query(default=None),
    hostname: str | None = Query(default=None, min_length=1, max_length=255),
    protocol: RemoteProtocol | None = Query(default=None),
    state: RemoteSessionState | None = Query(default=None),
    username: str | None = Query(default=None, min_length=1, max_length=255),
    provider_session_id: str | None = Query(default=None, min_length=1, max_length=255),
    source_ip: str | None = Query(default=None, min_length=1, max_length=45),
    correlation_status: str | None = Query(default=None, min_length=1, max_length=16),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> V2SessionPage:
    filters = _history_filters(
        from_at=from_at,
        to_at=to_at,
        server_id=server_id,
        hostname=hostname,
        protocol=protocol,
        state=state,
        username=username,
        provider_session_id=provider_session_id,
        source_ip=source_ip,
        correlation_status=correlation_status,
    )

    total = db.scalar(
        select(func.count(RdpSession.id))
        .select_from(RdpSession)
        .join(Server, Server.id == RdpSession.server_id)
        .where(*filters)
    ) or 0

    rows = db.execute(
        select(RdpSession, Server)
        .join(Server, Server.id == RdpSession.server_id)
        .where(*filters)
        .order_by(RdpSession.logon_at.desc(), RdpSession.id)
        .limit(limit)
        .offset(offset)
    ).all()

    now = utc_now()
    return V2SessionPage(
        items=[_session_item(session, server, now=now) for session, server in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=V2SessionDetail,
    dependencies=[Depends(authenticate_query_api)],
)
def session_detail(session_id: str, db: Session = Depends(get_db)) -> V2SessionDetail:
    session = db.get(RdpSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")

    server = db.get(Server, session.server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session server not found")

    evidence = db.scalars(
        select(CorrelationEvidence)
        .where(CorrelationEvidence.session_id == session.id)
        .order_by(CorrelationEvidence.observed_at, CorrelationEvidence.id)
    ).all()

    return V2SessionDetail(
        session=_session_item(session, server),
        server=_server_item(server),
        correlation_evidence=[_evidence_item(item) for item in evidence],
    )


@router.get(
    "/sessions/{session_id}/timeline",
    response_model=V2SessionTimeline,
    dependencies=[Depends(authenticate_query_api)],
)
def session_timeline(session_id: str, db: Session = Depends(get_db)) -> V2SessionTimeline:
    session = db.get(RdpSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")

    provider_session_id = session.provider_session_id or str(session.windows_session_id)
    event_filters = [
        SessionEvent.server_id == session.server_id,
        SessionEvent.protocol == session.protocol,
        SessionEvent.provider_session_id == provider_session_id,
    ]
    if session.boot_id is not None:
        event_filters.append(SessionEvent.boot_id == session.boot_id)
    if session.logon_at is not None:
        event_filters.append(SessionEvent.occurred_at >= session.logon_at)
    if session.logoff_at is not None:
        event_filters.append(SessionEvent.occurred_at <= session.logoff_at)

    events = db.scalars(
        select(SessionEvent)
        .where(*event_filters)
        .order_by(SessionEvent.occurred_at, SessionEvent.received_at, SessionEvent.id)
    ).all()
    evidence = db.scalars(
        select(CorrelationEvidence)
        .where(CorrelationEvidence.session_id == session.id)
        .order_by(CorrelationEvidence.observed_at, CorrelationEvidence.id)
    ).all()

    return V2SessionTimeline(
        session_id=session.id,
        events=[
            V2SessionEventItem(
                id=event.id,
                event_type=event.event_type,
                protocol=event.protocol,
                platform=event.platform,
                provider_event_id=event.provider_event_id,
                source_ip=event.source_ip,
                source_port=event.source_port,
                occurred_at=as_utc(event.occurred_at),
                received_at=as_utc(event.received_at),
                correlation_status=event.correlation_status,
            )
            for event in events
        ],
        correlation_evidence=[_evidence_item(item) for item in evidence],
    )


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
