from sqlalchemy import select

from app.models import RdpSession, SessionEvent
from tests.conftest import TestingSessionLocal


def test_v1_event_payload_remains_valid_with_additive_schema(client, agent_headers):
    response = client.post(
        "/api/v1/agent/events",
        headers=agent_headers,
        json={
            "contract_version": 1,
            "agent_version": "0.2.0",
            "boot_time_utc": "2026-09-04T09:00:00Z",
            "agent_time_utc": "2026-09-04T09:05:00Z",
            "events": [
                {
                    "event_id": 21,
                    "record_id": 9001,
                    "type": "LOGON",
                    "session_id": 8,
                    "username": "alice",
                    "domain": "EXAMPLE",
                    "occurred_at": "2026-09-04T09:01:00Z",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "duplicates": 0}

    with TestingSessionLocal() as db:
        event = db.scalar(select(SessionEvent))
        session = db.scalar(select(RdpSession))

        assert event is not None
        assert event.protocol == "RDP"
        assert event.source_ip is None
        assert event.source_port is None
        assert event.correlation_status is None

        assert session is not None
        assert session.protocol == "RDP"
        assert session.initial_source_ip is None
        assert session.last_source_ip is None
        assert session.correlation_status is None


def test_v1_snapshot_payload_remains_valid_with_additive_schema(client, agent_headers):
    response = client.post(
        "/api/v1/agent/snapshot",
        headers=agent_headers,
        json={
            "contract_version": 1,
            "agent_version": "0.2.0",
            "boot_time_utc": "2026-09-04T09:00:00Z",
            "agent_time_utc": "2026-09-04T09:05:00Z",
            "hostname": "SRV-RDS01",
            "sessions": [
                {
                    "session_id": 9,
                    "username": "bob",
                    "domain": "EXAMPLE",
                    "state": "ACTIVE",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"observed": 1, "created": 1, "updated": 0, "closed": 0}

    with TestingSessionLocal() as db:
        session = db.scalar(select(RdpSession))
        assert session is not None
        assert session.protocol == "RDP"
        assert session.initial_source_ip is None
        assert session.last_source_ip is None
        assert session.correlation_status is None
