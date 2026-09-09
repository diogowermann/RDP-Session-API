from datetime import datetime

from sqlalchemy import select

from app.models import CorrelationEvidence, CorrelationJob, RdpSession, SessionEvent
from app.services.correlation import discover_correlation_jobs, process_correlation_jobs
from tests.conftest import TestingSessionLocal


class AmbiguousResolver:
    def resolve(self, *, source_ip: str, observed_at: datetime) -> dict:
        return {
            "ip_address": source_ip,
            "at": "2026-09-09T13:00:00Z",
            "method": "network_observation",
            "candidate_count": 2,
            "unlinked_observation_count": 0,
            "evidence": [],
            "status": "AMBIGUOUS",
            "confidence": "none",
            "reason_code": "multiple_temporal_device_candidates",
            "device": None,
            "asset_resolution": {"status": "UNRESOLVED", "asset": None, "link_ids": []},
            "candidates": [
                {"id": 101, "uuid": "11111111-1111-1111-1111-111111111111"},
                {"id": 202, "uuid": "22222222-2222-2222-2222-222222222222"},
            ],
        }


def test_ambiguous_result_is_terminal_and_never_picks_a_device(client, agent_headers):
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
                    "record_id": 9101,
                    "type": "LOGON",
                    "session_id": 43,
                    "username": "bob",
                    "domain": "EXAMPLE",
                    "source_ip": "192.0.2.20",
                    "occurred_at": "2026-09-09T13:00:00Z",
                }
            ],
        },
    )
    assert response.status_code == 200

    now = datetime(2026, 9, 9, 13, 1, 0)
    with TestingSessionLocal() as db:
        discover_correlation_jobs(db, batch_size=100, now=now)
        result = process_correlation_jobs(
            db,
            AmbiguousResolver(),
            batch_size=100,
            max_attempts=5,
            retry_base_seconds=60,
            now=now,
        )
        db.commit()

        assert result["ambiguous"] == 1
        job = db.scalar(select(CorrelationJob))
        event = db.scalar(select(SessionEvent))
        session = db.scalar(select(RdpSession))
        evidence = db.scalar(select(CorrelationEvidence))

        assert job is not None and job.status == "AMBIGUOUS" and job.next_attempt_at is None
        assert event is not None and event.correlation_status == "AMBIGUOUS"
        assert session is not None and session.correlation_status == "AMBIGUOUS"
        assert evidence is not None
        assert evidence.status == "AMBIGUOUS"
        assert evidence.source_device_id is None
        assert evidence.integration_record_id is None
        assert evidence.asset_tag is None
        assert evidence.reason_code == "multiple_temporal_device_candidates"
        assert evidence.evidence_snapshot["candidate_count"] == 2
