from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Server, SessionEvent
from app.schemas import LogonAlertItem
from app.security import authenticate_query_api
from app.timeutils import as_utc, utc_now

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    dependencies=[Depends(authenticate_query_api)],
)


@router.get("/logons", response_model=list[LogonAlertItem])
def recent_logon_alerts(
    lookback_minutes: int = Query(default=5, ge=1, le=60),
    db: Session = Depends(get_db),
) -> list[LogonAlertItem]:
    """Return recently received LOGON events as one alert instance per event.

    The feed is intentionally based on immutable raw events instead of current
    session state. A short-lived session can therefore still be observed by
    Grafana after it has already logged off, while event idempotency prevents
    duplicate alert instances when an Agent replays a spool batch.
    """
    cutoff = utc_now() - timedelta(minutes=lookback_minutes)
    rows = db.execute(
        select(SessionEvent, Server)
        .join(Server, Server.id == SessionEvent.server_id)
        .where(
            SessionEvent.event_type == "LOGON",
            SessionEvent.received_at >= cutoff,
            Server.enabled.is_(True),
        )
        .order_by(SessionEvent.received_at, SessionEvent.id)
    ).all()

    return [
        LogonAlertItem(
            alert_id=event.id,
            server_id=server.id,
            hostname=server.hostname or server.fqdn or server.id,
            principal=f"{event.domain}\\{event.username}" if event.domain else event.username,
            username=event.username,
            domain=event.domain,
            logon_at=as_utc(event.occurred_at),
            alert_value=1,
        )
        for event, server in rows
    ]
