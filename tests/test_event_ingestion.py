from sqlalchemy import select

from app.models import RdpSession, SessionEvent, Server
from tests.conftest import TestingSessionLocal


def _payload():
    return {
        "contract_version": 1,
        "agent_version": "0.1.0",
        "boot_time_utc": "2026-08-20T08:00:00Z",
        "agent_time_utc": "2026-08-20T11:00:00Z",
        "events": [
            {
                "event_id": 21,
                "record_id": 100,
                "type": "LOGON",
                "session_id": 4,
                "username": "alice",
                "domain": "EXAMPLE",
                "occurred_at": "2026-08-20T08:10:00Z",
            },
            {
                "event_id": 24,
                "record_id": 101,
                "type": "DISCONNECT",
                "session_id": 4,
                "username": "alice",
                "domain": "EXAMPLE",
                "occurred_at": "2026-08-20T09:00:00Z",
            },
            {
                "event_id": 25,
                "record_id": 102,
                "type": "RECONNECT",
                "session_id": 4,
                "username": "alice",
                "domain": "EXAMPLE",
                "occurred_at": "2026-08-20T09:30:00Z",
            },
            {
                "event_id": 23,
                "record_id": 103,
                "type": "LOGOFF",
                "session_id": 4,
                "username": "alice",
                "domain": "EXAMPLE",
                "occurred_at": "2026-08-20T10:50:00Z",
            },
        ],
    }


def test_event_sequence_builds_one_closed_session(client, agent_headers):
    response = client.post("/api/v1/agent/events", headers=agent_headers, json=_payload())
    assert response.status_code == 200
    assert response.json() == {"accepted": 4, "duplicates": 0}

    with TestingSessionLocal() as db:
        events = db.scalars(select(SessionEvent)).all()
        sessions = db.scalars(select(RdpSession)).all()
        assert len(events) == 4
        assert len(sessions) == 1
        session = sessions[0]
        assert session.state == "CLOSED"
        assert session.disconnect_count == 1
        assert session.duration_minutes == 160
        assert session.end_reason == "LOGOFF"


def test_replayed_batch_is_idempotent(client, agent_headers):
    first = client.post("/api/v1/agent/events", headers=agent_headers, json=_payload())
    second = client.post("/api/v1/agent/events", headers=agent_headers, json=_payload())
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"accepted": 0, "duplicates": 4}

    with TestingSessionLocal() as db:
        assert len(db.scalars(select(SessionEvent)).all()) == 4
        assert len(db.scalars(select(RdpSession)).all()) == 1


def test_fractional_boot_time_does_not_create_false_reboot_across_batches(client, agent_headers):
    logon = {
        "contract_version": 1,
        "agent_version": "0.1.0",
        "boot_time_utc": "2026-07-16T10:37:02.781250Z",
        "agent_time_utc": "2026-08-21T14:11:39Z",
        "events": [
            {
                "event_id": 21,
                "record_id": 200,
                "type": "LOGON",
                "session_id": 10,
                "username": "alice",
                "domain": "EXAMPLE",
                "occurred_at": "2026-08-21T14:02:56Z",
            }
        ],
    }
    transition = {
        "contract_version": 1,
        "agent_version": "0.1.0",
        "boot_time_utc": "2026-07-16T10:37:02.781250Z",
        "agent_time_utc": "2026-08-21T14:21:18Z",
        "events": [
            {
                "event_id": 24,
                "record_id": 201,
                "type": "DISCONNECT",
                "session_id": 10,
                "username": "alice",
                "domain": "EXAMPLE",
                "occurred_at": "2026-08-21T14:20:00Z",
            },
            {
                "event_id": 25,
                "record_id": 202,
                "type": "RECONNECT",
                "session_id": 10,
                "username": "alice",
                "domain": "EXAMPLE",
                "occurred_at": "2026-08-21T14:20:30Z",
            },
        ],
    }

    first = client.post("/api/v1/agent/events", headers=agent_headers, json=logon)
    assert first.status_code == 200

    # Emulate a MariaDB DATETIME column that persisted the same boot time only
    # to whole-second precision before the next Agent batch arrives.
    with TestingSessionLocal() as db:
        server = db.scalar(select(Server))
        server.last_boot_at = server.last_boot_at.replace(microsecond=0)
        session = db.scalar(select(RdpSession))
        session.boot_time = session.boot_time.replace(microsecond=0)
        db.commit()

    second = client.post("/api/v1/agent/events", headers=agent_headers, json=transition)
    assert second.status_code == 200
    assert second.json() == {"accepted": 2, "duplicates": 0}

    with TestingSessionLocal() as db:
        session = db.scalar(select(RdpSession))
        assert session.state == "ACTIVE"
        assert session.disconnect_count == 1
        assert session.end_reason is None
        assert session.logoff_at is None
