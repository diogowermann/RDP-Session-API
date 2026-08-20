from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Server
from app.schemas import AgentEnvelope, AgentSnapshot, IngestResult, SnapshotResult
from app.security import authenticate_agent
from app.services.event_ingestion import ingest_events
from app.services.reconciliation import reconcile_snapshot

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/events", response_model=IngestResult)
def post_events(
    payload: AgentEnvelope,
    server: Server = Depends(authenticate_agent),
    db: Session = Depends(get_db),
) -> IngestResult:
    return ingest_events(db, server=server, envelope=payload)


@router.post("/snapshot", response_model=SnapshotResult)
def post_snapshot(
    payload: AgentSnapshot,
    server: Server = Depends(authenticate_agent),
    db: Session = Depends(get_db),
) -> SnapshotResult:
    return reconcile_snapshot(db, server=server, snapshot=payload)
