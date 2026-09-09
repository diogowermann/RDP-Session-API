from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_engine
from app.models import CorrelationEvidence, CorrelationJob, RdpSession, SessionEvent
from app.timeutils import utc_now

CORRELATION_TERMINAL_STATUSES = ("MATCHED", "AMBIGUOUS", "UNRESOLVED")
CORRELATION_QUEUE_STATUSES = ("PENDING", "RETRY")


class CorrelationResolver(Protocol):
    def resolve(self, *, source_ip: str, observed_at: datetime) -> dict[str, Any]: ...


class ResolverError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ResolverUnavailable(ResolverError):
    pass


class ResolverProtocolError(ResolverError):
    pass


class ResolverConfigurationError(ResolverError):
    pass


def _resolver_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


class NetworkResolverClient:
    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized_base = (base_url or "").strip().rstrip("/")
        normalized_key = (api_key or "").strip()
        if not normalized_base:
            raise ResolverConfigurationError("resolver_base_url_missing", "resolver base URL is not configured")
        if not normalized_key:
            raise ResolverConfigurationError("resolver_api_key_missing", "resolver API key is not configured")

        self._client = httpx.Client(
            base_url=normalized_base,
            headers={"X-API-Key": normalized_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    def __enter__(self) -> "NetworkResolverClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def resolve(self, *, source_ip: str, observed_at: datetime) -> dict[str, Any]:
        try:
            response = self._client.get(
                "/api/v1/devices/resolve-network",
                params={"ip": source_ip, "at": _resolver_timestamp(observed_at)},
            )
        except httpx.RequestError as exc:
            raise ResolverUnavailable("resolver_transport_error", "network resolver is unavailable") from exc

        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise ResolverUnavailable(
                f"resolver_http_{response.status_code}",
                f"network resolver returned HTTP {response.status_code}",
            )
        if response.status_code in {401, 403, 404}:
            raise ResolverConfigurationError(
                f"resolver_http_{response.status_code}",
                f"network resolver configuration rejected the request with HTTP {response.status_code}",
            )
        if response.status_code != 200:
            raise ResolverProtocolError(
                f"resolver_http_{response.status_code}",
                f"network resolver returned HTTP {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ResolverProtocolError("resolver_invalid_json", "network resolver returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ResolverProtocolError("resolver_invalid_payload", "network resolver returned a non-object payload")

        resolution_status = str(payload.get("status") or "").upper()
        if resolution_status not in CORRELATION_TERMINAL_STATUSES:
            raise ResolverProtocolError(
                "resolver_invalid_status",
                f"network resolver returned unsupported status {resolution_status!r}",
            )
        if resolution_status == "MATCHED":
            device = payload.get("device")
            if not isinstance(device, dict) or not str(device.get("uuid") or "").strip():
                raise ResolverProtocolError(
                    "resolver_matched_without_device",
                    "MATCHED resolver response did not include a device UUID",
                )
        return payload


def _same_principal(session: RdpSession, event: SessionEvent) -> bool:
    return session.username.casefold() == event.username.casefold() and (session.domain or "").casefold() == (
        event.domain or ""
    ).casefold()


def _session_for_event(db: Session, event: SessionEvent) -> RdpSession | None:
    filters = [
        RdpSession.server_id == event.server_id,
        RdpSession.protocol == event.protocol,
    ]
    if event.provider_session_id is not None:
        filters.append(RdpSession.provider_session_id == event.provider_session_id)
    else:
        filters.append(RdpSession.windows_session_id == event.windows_session_id)
    if event.boot_id is not None:
        filters.append(RdpSession.boot_id == event.boot_id)
    else:
        filters.append(RdpSession.boot_time == event.boot_time)

    candidates = db.scalars(
        select(RdpSession)
        .where(*filters)
        .order_by(RdpSession.logon_at.desc(), RdpSession.created_at.desc(), RdpSession.id.desc())
    ).all()
    for session in candidates:
        if not _same_principal(session, event):
            continue
        if session.logon_at is not None and event.occurred_at < session.logon_at:
            continue
        if session.logoff_at is not None and event.occurred_at > session.logoff_at:
            continue
        return session
    return None


def _job_id_for_event(event_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"remote-session-correlation-job:{event_id}"))


def _evidence_id_for_event(event_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"remote-session-correlation-evidence:{event_id}"))


def discover_correlation_jobs(
    db: Session,
    *,
    batch_size: int,
    now: datetime | None = None,
) -> dict[str, int]:
    observed_at = now or utc_now()
    events = db.scalars(
        select(SessionEvent)
        .where(
            SessionEvent.source_ip.is_not(None),
            SessionEvent.correlation_status.is_(None),
        )
        .order_by(SessionEvent.occurred_at, SessionEvent.received_at, SessionEvent.id)
        .limit(batch_size)
    ).all()

    created = 0
    already_queued = 0
    without_session = 0
    for event in events:
        if event.source_ip is None:
            continue
        session = _session_for_event(db, event)
        if session is None:
            without_session += 1
            continue

        job_id = _job_id_for_event(event.id)
        existing = db.get(CorrelationJob, job_id)
        if existing is not None:
            event.correlation_status = existing.status if existing.status in CORRELATION_TERMINAL_STATUSES else "PENDING"
            already_queued += 1
            continue

        db.add(
            CorrelationJob(
                id=job_id,
                session_id=session.id,
                session_event_id=event.id,
                source_ip=event.source_ip,
                observed_at=event.occurred_at,
                status="PENDING",
                attempt_count=0,
                next_attempt_at=observed_at,
            )
        )
        event.correlation_status = "PENDING"
        created += 1

    db.flush()
    return {
        "events_scanned": len(events),
        "jobs_created": created,
        "already_queued": already_queued,
        "events_without_session": without_session,
    }


def _confidence_score(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    normalized = str(value or "").strip().casefold()
    scores = {
        "deterministic": 1.0,
        "high": 0.9,
        "medium": 0.5,
        "low": 0.25,
        "none": 0.0,
    }
    return scores.get(normalized)


def _evidence_from_payload(
    *,
    job: CorrelationJob,
    payload: dict[str, Any],
    created_at: datetime,
) -> CorrelationEvidence:
    resolution_status = str(payload.get("status") or "").upper()
    if resolution_status not in CORRELATION_TERMINAL_STATUSES:
        raise ResolverProtocolError("resolver_invalid_status", "resolver status is not terminal")

    device = payload.get("device") if isinstance(payload.get("device"), dict) else {}
    device_uuid = str(device.get("uuid") or "").strip() or None
    if resolution_status == "MATCHED" and device_uuid is None:
        raise ResolverProtocolError("resolver_matched_without_device", "MATCHED response did not include device UUID")
    if device_uuid is not None and len(device_uuid) > 36:
        raise ResolverProtocolError("resolver_device_id_too_long", "resolved device UUID exceeds storage contract")

    asset_resolution = payload.get("asset_resolution") if isinstance(payload.get("asset_resolution"), dict) else {}
    asset = asset_resolution.get("asset") if isinstance(asset_resolution.get("asset"), dict) else {}
    link_ids = asset_resolution.get("link_ids") if isinstance(asset_resolution.get("link_ids"), list) else []
    integration_record_id = str(link_ids[0]) if asset_resolution.get("status") == "MATCHED" and len(link_ids) == 1 else None
    asset_tag = str(asset.get("asset_tag") or "").strip() or None

    return CorrelationEvidence(
        id=_evidence_id_for_event(job.session_event_id or job.id),
        session_id=job.session_id,
        session_event_id=job.session_event_id,
        status=resolution_status,
        source_ip=job.source_ip,
        observed_at=job.observed_at,
        source_device_id=device_uuid,
        integration_record_id=integration_record_id,
        asset_tag=asset_tag,
        method=str(payload.get("method") or "").strip() or None,
        confidence=_confidence_score(payload.get("confidence")),
        reason_code=str(payload.get("reason_code") or "").strip() or None,
        evidence_snapshot=payload,
        created_at=created_at,
    )


def _update_session_status_if_latest(db: Session, session: RdpSession, evidence: CorrelationEvidence) -> None:
    latest = db.scalar(
        select(CorrelationEvidence)
        .where(CorrelationEvidence.session_id == session.id)
        .order_by(CorrelationEvidence.observed_at.desc(), CorrelationEvidence.created_at.desc(), CorrelationEvidence.id.desc())
        .limit(1)
    )
    if latest is not None and latest.id == evidence.id:
        session.correlation_status = evidence.status


def _retry_delay_seconds(*, attempt_count: int, base_seconds: int) -> int:
    exponent = max(0, attempt_count - 1)
    return min(3600, base_seconds * (2**exponent))


def process_correlation_jobs(
    db: Session,
    resolver: CorrelationResolver,
    *,
    batch_size: int,
    max_attempts: int,
    retry_base_seconds: int,
    now: datetime | None = None,
) -> dict[str, int]:
    attempted_at = now or utc_now()
    jobs = db.scalars(
        select(CorrelationJob)
        .where(
            CorrelationJob.status.in_(CORRELATION_QUEUE_STATUSES),
            or_(CorrelationJob.next_attempt_at.is_(None), CorrelationJob.next_attempt_at <= attempted_at),
        )
        .order_by(CorrelationJob.observed_at, CorrelationJob.created_at, CorrelationJob.id)
        .limit(batch_size)
    ).all()

    outcomes = {
        "jobs_selected": len(jobs),
        "matched": 0,
        "ambiguous": 0,
        "unresolved": 0,
        "retried": 0,
        "failed": 0,
        "idempotent_existing_evidence": 0,
    }

    for job in jobs:
        event = db.get(SessionEvent, job.session_event_id) if job.session_event_id is not None else None
        session = db.get(RdpSession, job.session_id)
        if session is None:
            job.status = "FAILED"
            job.last_error_code = "session_missing"
            job.next_attempt_at = None
            if event is not None:
                event.correlation_status = "FAILED"
            outcomes["failed"] += 1
            continue

        evidence_id = _evidence_id_for_event(job.session_event_id or job.id)
        existing_evidence = db.get(CorrelationEvidence, evidence_id)
        if existing_evidence is not None:
            job.status = existing_evidence.status
            job.last_error_code = None
            job.next_attempt_at = None
            if event is not None:
                event.correlation_status = existing_evidence.status
            _update_session_status_if_latest(db, session, existing_evidence)
            outcomes["idempotent_existing_evidence"] += 1
            continue

        job.attempt_count += 1
        job.last_attempt_at = attempted_at
        try:
            payload = resolver.resolve(source_ip=job.source_ip, observed_at=job.observed_at)
            evidence = _evidence_from_payload(job=job, payload=payload, created_at=attempted_at)
        except ResolverUnavailable as exc:
            job.last_error_code = exc.code
            if job.attempt_count >= max_attempts:
                job.status = "FAILED"
                job.next_attempt_at = None
                if event is not None:
                    event.correlation_status = "FAILED"
                outcomes["failed"] += 1
            else:
                job.status = "RETRY"
                job.next_attempt_at = attempted_at + timedelta(
                    seconds=_retry_delay_seconds(
                        attempt_count=job.attempt_count,
                        base_seconds=retry_base_seconds,
                    )
                )
                if event is not None:
                    event.correlation_status = "PENDING"
                outcomes["retried"] += 1
            continue
        except ResolverProtocolError as exc:
            job.status = "FAILED"
            job.last_error_code = exc.code
            job.next_attempt_at = None
            if event is not None:
                event.correlation_status = "FAILED"
            outcomes["failed"] += 1
            continue

        db.add(evidence)
        db.flush()
        job.status = evidence.status
        job.last_error_code = None
        job.next_attempt_at = None
        if event is not None:
            event.correlation_status = evidence.status
        _update_session_status_if_latest(db, session, evidence)
        outcomes[evidence.status.casefold()] += 1

    db.flush()
    return outcomes


def correlation_metrics(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    observed_at = now or utc_now()
    rows = db.execute(
        select(CorrelationJob.status, func.count(CorrelationJob.id)).group_by(CorrelationJob.status)
    ).all()
    counts = {str(status).upper(): int(count) for status, count in rows}

    pending_jobs = counts.get("PENDING", 0)
    retry_jobs = counts.get("RETRY", 0)
    matched = counts.get("MATCHED", 0)
    ambiguous = counts.get("AMBIGUOUS", 0)
    unresolved = counts.get("UNRESOLVED", 0)
    failed = counts.get("FAILED", 0)
    terminal_jobs = matched + ambiguous + unresolved

    oldest_queue_at = db.scalar(
        select(func.min(CorrelationJob.created_at)).where(CorrelationJob.status.in_(CORRELATION_QUEUE_STATUSES))
    )
    oldest_pending_age_seconds = None
    if oldest_queue_at is not None:
        oldest_pending_age_seconds = max(0, int((observed_at - oldest_queue_at).total_seconds()))

    terminal_timings = db.execute(
        select(CorrelationJob.created_at, CorrelationJob.updated_at).where(
            CorrelationJob.status.in_(CORRELATION_TERMINAL_STATUSES)
        )
    ).all()
    terminal_latencies = [
        max(0.0, (updated_at - created_at).total_seconds())
        for created_at, updated_at in terminal_timings
        if created_at is not None and updated_at is not None
    ]

    return {
        "queue_depth": pending_jobs + retry_jobs,
        "pending_jobs": pending_jobs,
        "retry_jobs": retry_jobs,
        "failed_jobs": failed,
        "matched": matched,
        "ambiguous": ambiguous,
        "unresolved": unresolved,
        "terminal_jobs": terminal_jobs,
        "match_rate": (matched / terminal_jobs) if terminal_jobs else None,
        "oldest_pending_age_seconds": oldest_pending_age_seconds,
        "average_terminal_latency_seconds": (
            sum(terminal_latencies) / len(terminal_latencies) if terminal_latencies else None
        ),
        "evidence_rows": int(db.scalar(select(func.count(CorrelationEvidence.id))) or 0),
    }


def run_correlation_cycle(settings: Settings) -> dict[str, Any]:
    if not settings.correlation_enabled:
        return {
            "status": "disabled",
            "feature_flag_enabled": False,
            "writes_performed": 0,
            "external_writes_performed": 0,
        }

    with NetworkResolverClient(
        base_url=settings.resolver_base_url,
        api_key=settings.resolver_api_key,
        timeout_seconds=settings.resolver_timeout_seconds,
    ) as resolver:
        with Session(get_engine()) as db:
            discovery = discover_correlation_jobs(
                db,
                batch_size=settings.correlation_batch_size,
            )
            processing = process_correlation_jobs(
                db,
                resolver,
                batch_size=settings.correlation_batch_size,
                max_attempts=settings.correlation_max_attempts,
                retry_base_seconds=settings.correlation_retry_base_seconds,
            )
            db.commit()
            metrics = correlation_metrics(db)

    return {
        "status": "completed",
        "feature_flag_enabled": True,
        "discovery": discovery,
        "processing": processing,
        "metrics": metrics,
        "external_writes_performed": 0,
    }
