from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.correlation_schemas import V2CorrelationMetrics
from app.database import get_db
from app.security import authenticate_query_api
from app.services.correlation import correlation_metrics

router = APIRouter(tags=["v2", "correlation"])


@router.get(
    "/correlation/metrics",
    response_model=V2CorrelationMetrics,
    dependencies=[Depends(authenticate_query_api)],
)
def get_correlation_metrics(db: Session = Depends(get_db)) -> V2CorrelationMetrics:
    metrics = correlation_metrics(db)
    return V2CorrelationMetrics(
        feature_flag_enabled=get_settings().correlation_enabled,
        **metrics,
    )
