from sqlalchemy import select

from app.models import RdpSession
from tests.conftest import TestingSessionLocal


def test_snapshot_creates_and_then_closes_missing_session(client, agent_headers):
    first = client.post(
        "/api/v1/agent/snapshot",
        headers=agent_headers,
        json={
            "contract_version": 1,
            "agent_version": "0.1.0",
            "boot_time_utc": "2026-08-20T08:00:00Z",
            "agent_time_utc": "2026-08-20T09:00:00Z",
            "hostname": "SRV-RDS01",
            "fqdn": "srv-rds01.example.test",
            "os_version": "Windows Server",
            "sessions": [
                {
                    "session_id": 7,
                    "username": "alice",
                    "domain": "EXAMPLE",
                    "state": "ACTIVE",
                    "logon_at": "2026-08-20T08:30:00Z",
                }
            ],
        },
    )
    assert first.status_code == 200
    assert first.json() == {"observed": 1, "created": 1, "updated": 0, "closed": 0}

    second = client.post(
        "/api/v1/agent/snapshot",
        headers=agent_headers,
        json={
            "contract_version": 1,
            "agent_version": "0.1.0",
            "boot_time_utc": "2026-08-20T08:00:00Z",
            "agent_time_utc": "2026-08-20T09:10:00Z",
            "hostname": "SRV-RDS01",
            "sessions": [],
        },
    )
    assert second.status_code == 200
    assert second.json() == {"observed": 0, "created": 0, "updated": 0, "closed": 1}

    with TestingSessionLocal() as db:
        session = db.scalar(select(RdpSession))
        assert session is not None
        assert session.state == "CLOSED"
        assert session.end_reason == "RECONCILIATION"
        assert session.duration_minutes == 40


def test_snapshot_reconciliation_tolerates_database_boot_time_truncation(client, agent_headers):
    first = client.post(
        "/api/v1/agent/snapshot",
        headers=agent_headers,
        json={
            "contract_version": 1,
            "agent_version": "0.2.0",
            "boot_time_utc": "2026-08-20T08:00:00.987654Z",
            "agent_time_utc": "2026-08-20T09:00:00Z",
            "hostname": "SRV-RDS01",
            "sessions": [
                {
                    "session_id": 7,
                    "username": "alice",
                    "domain": "EXAMPLE",
                    "state": "ACTIVE",
                }
            ],
        },
    )
    assert first.status_code == 200
    assert first.json() == {"observed": 1, "created": 1, "updated": 0, "closed": 0}

    with TestingSessionLocal() as db:
        session = db.scalar(select(RdpSession))
        assert session is not None
        session.boot_time = session.boot_time.replace(microsecond=0)
        db.commit()

    second = client.post(
        "/api/v1/agent/snapshot",
        headers=agent_headers,
        json={
            "contract_version": 1,
            "agent_version": "0.2.0",
            "boot_time_utc": "2026-08-20T08:00:00.987654Z",
            "agent_time_utc": "2026-08-20T09:10:00Z",
            "hostname": "SRV-RDS01",
            "sessions": [],
        },
    )
    assert second.status_code == 200
    assert second.json() == {"observed": 0, "created": 0, "updated": 0, "closed": 1}

    with TestingSessionLocal() as db:
        session = db.scalar(select(RdpSession))
        assert session is not None
        assert session.state == "CLOSED"
        assert session.end_reason == "RECONCILIATION"
