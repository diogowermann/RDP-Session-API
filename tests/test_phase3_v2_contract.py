from sqlalchemy import select

from app.main import app
from app.models import RdpSession, SessionEvent
from tests.conftest import TestingSessionLocal


QUERY_HEADERS = {"X-API-Key": "test-query-key"}


def test_v2_health_and_openapi(client):
    response = client.get("/api/v2/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "contract": "v2"}

    schema = app.openapi()
    assert "/api/v1/agent/events" in schema["paths"]
    assert "/api/v2/agent/events" in schema["paths"]
    assert "/api/v2/agent/snapshot" in schema["paths"]
    assert "/api/v2/sessions/active" in schema["paths"]
    assert "/api/v2/sessions/history" in schema["paths"]
    assert "/api/v2/alerts/logons" in schema["paths"]


def test_v2_ssh_lifecycle_is_generic_and_idempotent(client, agent_headers):
    logon = {
        "contract_version": 2,
        "agent_version": "0.1.0",
        "platform": "linux",
        "protocol": "SSH",
        "boot_id": "linux-boot-001",
        "agent_time_utc": "2026-09-04T13:00:05Z",
        "events": [
            {
                "type": "LOGON",
                "provider_session_id": "pts/2",
                "provider_event_id": "journal-cursor-001",
                "username": "alice",
                "source_ip": "192.0.2.20",
                "source_port": 53122,
                "occurred_at": "2026-09-04T13:00:00Z",
            }
        ],
    }

    response = client.post("/api/v2/agent/events", headers=agent_headers, json=logon)
    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "duplicates": 0}

    replay = client.post("/api/v2/agent/events", headers=agent_headers, json=logon)
    assert replay.status_code == 200
    assert replay.json() == {"accepted": 0, "duplicates": 1}

    active = client.get("/api/v2/sessions/active?protocol=SSH", headers=QUERY_HEADERS)
    assert active.status_code == 200
    assert len(active.json()) == 1
    assert active.json()[0]["protocol"] == "SSH"
    assert active.json()[0]["platform"] == "linux"
    assert active.json()[0]["provider_session_id"] == "pts/2"
    assert active.json()[0]["initial_source_ip"] == "192.0.2.20"

    logoff = {
        **logon,
        "agent_time_utc": "2026-09-04T13:05:05Z",
        "events": [
            {
                "type": "LOGOFF",
                "provider_session_id": "pts/2",
                "provider_event_id": "journal-cursor-002",
                "username": "alice",
                "occurred_at": "2026-09-04T13:05:00Z",
            }
        ],
    }
    response = client.post("/api/v2/agent/events", headers=agent_headers, json=logoff)
    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "duplicates": 0}

    history = client.get("/api/v2/sessions/history?protocol=SSH", headers=QUERY_HEADERS)
    assert history.status_code == 200
    assert len(history.json()["items"]) == 1
    assert history.json()["items"][0]["state"] == "CLOSED"

    with TestingSessionLocal() as db:
        events = db.scalars(select(SessionEvent).order_by(SessionEvent.occurred_at)).all()
        assert len(events) == 2
        assert all(event.protocol == "SSH" for event in events)
        assert all(event.platform == "linux" for event in events)
        assert events[0].provider_session_id == "pts/2"
        assert events[0].provider_event_id == "journal-cursor-001"
        session = db.scalar(select(RdpSession))
        assert session is not None
        assert session.provider_session_id == "pts/2"
        assert session.boot_id == "linux-boot-001"
        assert session.state == "CLOSED"


def test_v2_rejects_protocol_invalid_ssh_transition(client, agent_headers):
    payload = {
        "contract_version": 2,
        "agent_version": "0.1.0",
        "platform": "linux",
        "protocol": "SSH",
        "boot_id": "linux-boot-001",
        "agent_time_utc": "2026-09-04T13:00:05Z",
        "events": [
            {
                "type": "RECONNECT",
                "provider_session_id": "pts/2",
                "provider_event_id": "journal-cursor-003",
                "username": "alice",
                "occurred_at": "2026-09-04T13:00:00Z",
            }
        ],
    }
    response = client.post("/api/v2/agent/events", headers=agent_headers, json=payload)
    assert response.status_code == 422


def test_v2_stale_logon_does_not_duplicate_closed_session(client, agent_headers):
    base = {
        "contract_version": 2,
        "agent_version": "0.1.0",
        "platform": "linux",
        "protocol": "SSH",
        "boot_id": "linux-boot-002",
        "agent_time_utc": "2026-09-04T14:10:00Z",
    }
    logon = {
        **base,
        "events": [{
            "type": "LOGON",
            "provider_session_id": "pts/3",
            "provider_event_id": "cursor-a",
            "username": "bob",
            "occurred_at": "2026-09-04T14:00:00Z",
        }],
    }
    logoff = {
        **base,
        "events": [{
            "type": "LOGOFF",
            "provider_session_id": "pts/3",
            "provider_event_id": "cursor-b",
            "username": "bob",
            "occurred_at": "2026-09-04T14:05:00Z",
        }],
    }
    stale_logon = {
        **base,
        "events": [{
            "type": "LOGON",
            "provider_session_id": "pts/3",
            "provider_event_id": "cursor-c",
            "username": "bob",
            "occurred_at": "2026-09-04T14:01:00Z",
        }],
    }

    assert client.post("/api/v2/agent/events", headers=agent_headers, json=logon).status_code == 200
    assert client.post("/api/v2/agent/events", headers=agent_headers, json=logoff).status_code == 200
    assert client.post("/api/v2/agent/events", headers=agent_headers, json=stale_logon).status_code == 200

    with TestingSessionLocal() as db:
        sessions = db.scalars(select(RdpSession)).all()
        assert len(sessions) == 1
        assert sessions[0].state == "CLOSED"


def test_v1_query_surface_does_not_expose_ssh_server(client, agent_headers):
    payload = {
        "contract_version": 2,
        "agent_version": "0.1.0",
        "platform": "linux",
        "protocol": "SSH",
        "boot_id": "linux-boot-003",
        "agent_time_utc": "2026-09-04T15:00:00Z",
        "events": [{
            "type": "LOGON",
            "provider_session_id": "pts/9",
            "provider_event_id": "cursor-z",
            "username": "carol",
            "occurred_at": "2026-09-04T14:59:00Z",
        }],
    }
    assert client.post("/api/v2/agent/events", headers=agent_headers, json=payload).status_code == 200

    v1_servers = client.get("/api/v1/servers", headers=QUERY_HEADERS)
    assert v1_servers.status_code == 200
    assert v1_servers.json() == []

    v2_servers = client.get("/api/v2/servers", headers=QUERY_HEADERS)
    assert v2_servers.status_code == 200
    assert len(v2_servers.json()) == 1
    assert v2_servers.json()[0]["platform"] == "linux"
