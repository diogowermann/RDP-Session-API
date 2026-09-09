from pydantic import BaseModel


class V2CorrelationMetrics(BaseModel):
    feature_flag_enabled: bool
    queue_depth: int
    pending_jobs: int
    retry_jobs: int
    failed_jobs: int
    matched: int
    ambiguous: int
    unresolved: int
    terminal_jobs: int
    match_rate: float | None
    oldest_pending_age_seconds: int | None
    average_terminal_latency_seconds: float | None
    evidence_rows: int
