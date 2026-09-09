from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.models import CorrelationEvidence, CorrelationJob, RdpSession, SessionEvent
from app.services.correlation import (
    NetworkResolverClient,
    ResolverUnavailable,
    correlation_metrics,
    discover_correlation_jobs,
    process_correlation_jobs,
)
from tests.conftest import TestingSessionLocal


class StaticResolver:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, datetime]] = []

    def resolve(self, *, source_ip: str, observed_at: datetime) -> dict:
        self.calls.append((source_ip, observed_at))
        return self.payload


class UnavailableResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, *, source_ip: str, observed_at: datetime) -> dict:
        self.calls += 1
        raise ResolverUnavailable("resolver_http_503", "resolver unavailable")


def _ingest_logon(client, agent_headers, *, source_ip: str = "192.0.2.10") -> None:
    response = client.post(
        "/api/v1/agent/events",
        headers=agent_headers,
        json={
            "contract_version": 1,
            "agent_version": "0.3.0",
            "boot_time_utc": "2026-09-09T10:00:00Z",
            "agent_time_utc": "2026-09-09T13:00:05Z",
            "events": [
                {
                    "event_id": 21,
                    "record_id": 9001,
                    "type": "LOGON",
                    "session_id": 42,
                    "username": "alice",
                    "domain": "EXAMPLE",
                    "source_ip": source_ip,
                    "source_port": 53001,
                    "occurred_at": "2026-09-09T13:00:00Z",
                }
            ],
        },
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "duplicates": 0}


def _matched_payload() -> dict:
    return {
        "ip_address": "192.0.2.10",
        "at": "2026-09-09T13:00:00Z",
        "method": "network_observation",
        "candidate_count": 1,
        "unlinked_observation_count": 0,
        "evidence": [
            {
                "id": 7,
                "device_id": 264,
                "source": "dhcp",
                "confidence": "deterministic",
            }
        ],
        "status": "MATCHED",
        "confidence": "deterministic",
        "reason_code": "single_temporal_device_candidate",
        "device": {
            "id": 264,
            "uuid": "4b839496-9434-4180-8bdd-4d8bf3b07b00",
            "computer_name": "PC-01",
            "platform": "windows",
            "observation_ids": [7],
            "sources": ["dhcp"],
        },
        "asset_resolution": {
            "status": "MATCHED",
            "asset": {
                "snipe_asset_id": 1,
                "asset_tag": "ASSET-0001",
                "confidence": "human_validated",
                "link_reason": "reimage_reassociation",
            },
            "link_ids": [31],
        },
        "candidates": [],
    }


def _unresolved_payload() -> dict:
    return {
        "ip_address": "192.0.2.10",
        "at": "2026-09-09T13:00:00Z",
        "method": "network_observation",
        "candidate_count": 0,
        "unlinked_observation_count": 0,
        "evidence": [],
        "status": "UNRESOLVED",
        "confidence": "none",
        "reason_code": "no_network_observation",
        "device": None,
        "asset_resolution": {"status": "UNRESOLVED", "asset": None, "link_ids": []},
        "candidates": [],
    }


def test_discovery_creates_one_idempotent_job_for_persisted_source_event(client, agent_headers):
    _ingest_logon(client, agent_headers)
    now = datetime(2026, 9, 9, 13, 1, 0)

    with TestingSessionLocal() as db:
        first = discover_correlation_jobs(db, batch_size=100, now=now)
        db.commit()
        assert first == {
            "events_scanned": 1,
            "jobs_created": 1,
            "already_queued": 0,
            "events_without_session": 0,
        }

        event = db.scalar(select(SessionEvent))
        job = db.scalar(select(CorrelationJob))
        session = db.scalar(select(RdpSession))
        assert event is not None and event.correlation_status == "PENDING"
        assert job is not None and job.session_event_id == event.id
        assert session is not None and job.session_id == session.id
        assert job.source_ip == "192.0.2.10"
        assert job.observed_at == datetime(2026, 9, 9, 13, 0, 0)

        second = discover_correlation_jobs(db, batch_size=100, now=now)
        assert second["jobs_created"] == 0
        assert db.query(CorrelationJob).count() == 1


def test_matched_result_freezes_evidence_and_updates_event_and_session(client, agent_headers):
    _ingest_logon(client, agent_headers)
    now = datetime(2026, 9, 9, 13, 1, 0)
    resolver = StaticResolver(_matched_payload())

    with TestingSessionLocal() as db:
        discover_correlation_jobs(db, batch_size=100, now=now)
        result = process_correlation_jobs(
            db,
            resolver,
            batch_size=100,
            max_attempts=5,
            retry_base_seconds=60,
            now=now,
        )
        db.commit()

        assert result["matched"] == 1
        assert len(resolver.calls) == 1
        job = db.scalar(select(CorrelationJob))
        event = db.scalar(select(SessionEvent))
        session = db.scalar(select(RdpSession))
        evidence = db.scalar(select(CorrelationEvidence))

        assert job is not None and job.status == "MATCHED" and job.attempt_count == 1
        assert event is not None and event.correlation_status == "MATCHED"
        assert session is not None and session.correlation_status == "MATCHED"
        assert evidence is not None
        assert evidence.status == "MATCHED"
        assert evidence.source_device_id == "4b839496-9434-4180-8bdd-4d8bf3b07b00"
        assert evidence.integration_record_id == "31"
        assert evidence.asset_tag == "ASSET-0001"
        assert evidence.method == "network_observation"
        assert evidence.confidence == 1.0
        assert evidence.reason_code == "single_temporal_device_candidate"
        assert evidence.evidence_snapshot == _matched_payload()


def test_existing_evidence_is_never_rewritten_by_later_resolver_state(client, agent_headers):
    _ingest_logon(client, agent_headers)
    now = datetime(2026, 9, 9, 13, 1, 0)

    with TestingSessionLocal() as db:
        discover_correlation_jobs(db, batch_size=100, now=now)
        first_resolver = StaticResolver(_matched_payload())
        process_correlation_jobs(
            db,
            first_resolver,
            batch_size=100,
            max_attempts=5,
            retry_base_seconds=60,
            now=now,
        )
        db.commit()

        job = db.scalar(select(CorrelationJob))
        event = db.scalar(select(SessionEvent))
        assert job is not None and event is not None
        job.status = "PENDING"
        job.next_attempt_at = now + timedelta(minutes=1)
        event.correlation_status = None
        db.commit()

        later_resolver = StaticResolver(_unresolved_payload())
        result = process_correlation_jobs(
            db,
            later_resolver,
            batch_size=100,
            max_attempts=5,
            retry_base_seconds=60,
            now=now + timedelta(minutes=1),
        )
        db.commit()

        assert result["idempotent_existing_evidence"] == 1
        assert later_resolver.calls == []
        evidence = db.scalar(select(CorrelationEvidence))
        session = db.scalar(select(RdpSession))
        assert evidence is not None and evidence.status == "MATCHED"
        assert evidence.evidence_snapshot == _matched_payload()
        assert job.status == "MATCHED"
        assert event.correlation_status == "MATCHED"
        assert session is not None and session.correlation_status == "MATCHED"


def test_unresolved_is_terminal_and_not_retried(client, agent_headers):
    _ingest_logon(client, agent_headers)
    now = datetime(2026, 9, 9, 13, 1, 0)
    resolver = StaticResolver(_unresolved_payload())

    with TestingSessionLocal() as db:
        discover_correlation_jobs(db, batch_size=100, now=now)
        result = process_correlation_jobs(
            db,
            resolver,
            batch_size=100,
            max_attempts=5,
            retry_base_seconds=60,
            now=now,
        )
        db.commit()

        assert result["unresolved"] == 1
        job = db.scalar(select(CorrelationJob))
        evidence = db.scalar(select(CorrelationEvidence))
        assert job is not None and job.status == "UNRESOLVED" and job.next_attempt_at is None
        assert evidence is not None and evidence.status == "UNRESOLVED"
        assert evidence.reason_code == "no_network_observation"
        assert evidence.confidence == 0.0

        again = process_correlation_jobs(
            db,
            resolver,
            batch_size=100,
            max_attempts=5,
            retry_base_seconds=60,
            now=now + timedelta(hours=1),
        )
        assert again["jobs_selected"] == 0
        assert len(resolver.calls) == 1


def test_unavailable_resolver_retries_with_backoff_then_fails(client, agent_headers):
    _ingest_logon(client, agent_headers)
    now = datetime(2026, 9, 9, 13, 1, 0)
    resolver = UnavailableResolver()

    with TestingSessionLocal() as db:
        discover_correlation_jobs(db, batch_size=100, now=now)
        first = process_correlation_jobs(
            db,
            resolver,
            batch_size=100,
            max_attempts=2,
            retry_base_seconds=60,
            now=now,
        )
        db.commit()

        job = db.scalar(select(CorrelationJob))
        assert first["retried"] == 1
        assert job is not None
        assert job.status == "RETRY"
        assert job.attempt_count == 1
        assert job.next_attempt_at == now + timedelta(seconds=60)
        assert job.last_error_code == "resolver_http_503"

        not_due = process_correlation_jobs(
            db,
            resolver,
            batch_size=100,
            max_attempts=2,
            retry_base_seconds=60,
            now=now + timedelta(seconds=30),
        )
        assert not_due["jobs_selected"] == 0

        second = process_correlation_jobs(
            db,
            resolver,
            batch_size=100,
            max_attempts=2,
            retry_base_seconds=60,
            now=now + timedelta(seconds=60),
        )
        db.commit()

        assert second["failed"] == 1
        assert job.status == "FAILED"
        assert job.attempt_count == 2
        assert job.next_attempt_at is None
        assert db.scalar(select(CorrelationEvidence)) is None
        event = db.scalar(select(SessionEvent))
        assert event is not None and event.correlation_status == "FAILED"
        assert resolver.calls == 2


def test_network_resolver_client_sends_secret_header_and_exact_timestamp_without_exposing_it():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["api_key"] = request.headers.get("X-API-Key")
        seen["ip"] = request.url.params.get("ip")
        seen["at"] = request.url.params.get("at")
        return httpx.Response(200, json=_matched_payload())

    transport = httpx.MockTransport(handler)
    with NetworkResolverClient(
        base_url="https://resolver.example.test",
        api_key="dedicated-test-key",
        timeout_seconds=5,
        transport=transport,
    ) as resolver:
        payload = resolver.resolve(
            source_ip="192.0.2.10",
            observed_at=datetime(2026, 9, 9, 13, 0, 0),
        )

    assert payload["status"] == "MATCHED"
    assert seen == {
        "api_key": "dedicated-test-key",
        "ip": "192.0.2.10",
        "at": "2026-09-09T13:00:00Z",
    }


def test_correlation_metrics_endpoint_exposes_queue_and_match_rate(client, agent_headers):
    _ingest_logon(client, agent_headers)
    now = datetime(2026, 9, 9, 13, 1, 0)

    with TestingSessionLocal() as db:
        discover_correlation_jobs(db, batch_size=100, now=now)
        process_correlation_jobs(
            db,
            StaticResolver(_matched_payload()),
            batch_size=100,
            max_attempts=5,
            retry_base_seconds=60,
            now=now,
        )
        db.commit()
        metrics = correlation_metrics(db, now=now + timedelta(seconds=10))
        assert metrics["matched"] == 1
        assert metrics["terminal_jobs"] == 1
        assert metrics["match_rate"] == 1.0
        assert metrics["queue_depth"] == 0
        assert metrics["evidence_rows"] == 1

    unauthorized = client.get("/api/v2/correlation/metrics")
    assert unauthorized.status_code == 401

    response = client.get(
        "/api/v2/correlation/metrics",
        headers={"X-API-Key": "test-query-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["feature_flag_enabled"] is False
    assert body["matched"] == 1
    assert body["match_rate"] == 1.0
    assert body["queue_depth"] == 0
