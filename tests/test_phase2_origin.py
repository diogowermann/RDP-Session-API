from sqlalchemy import select

from app.models import RdpSession, SessionEvent
from app.schemas import AgentEvent, EventType
from tests.conftest import TestingSessionLocal


def _event(*, record_id: int, event_type: str, source_ip=None, source_port=None):
    payload = {
        "event_id": 21 if event_type == "LOGON" else 25,
        "record_id": record_id,
        "type": event_type,
        "session_id": 42,
        "username": "alice",
        "domain": "EXAMPLE",
        "occurred_at": "2026-09-04T12:00:00Z" if event_type == "LOGON" else "2026-09-04T12:10:00Z",
    }
    if source_ip is not None:
        payload["source_ip"] = source_ip
    if source_port is not None:
        payload["source_port"] = source_port
    return payload


def _envelope(events):
    return {
        "contract_version": 1,
        "agent_version": "0.3.0",
        "boot_time_utc": "2026-09-04T09:00:00Z",
        "agent_time_utc": "2026-09-04T12:15:00Z",
        "events": events,
    }


def test_source_normalization_never_rejects_bad_ip_values():
    cases = {
        "LOCAL": None,
        "127.0.0.1": None,
        "::1": None,
        "0.0.0.0": None,
        "192.168.1": None,
        "not-an-ip": None,
        "192.0.2.10": "192.0.2.10",
        "2001:0db8:0:0::1": "2001:db8::1",
    }

    for raw, expected in cases.items():
        event = AgentEvent(
            event_id=21,
            record_id=1,
            type=EventType.LOGON,
            session_id=1,
            username="alice",
            source_ip=raw,
            source_port="53000",
            occurred_at="2026-09-04T12:00:00Z",
        )
        assert event.source_ip == expected
        assert event.source_port == 53000

    event = AgentEvent(
        event_id=21,
        record_id=2,
        type=EventType.LOGON,
        session_id=1,
        username="alice",
        source_ip="192.0.2.10",
        source_port=70000,
        occurred_at="2026-09-04T12:00:00Z",
    )
    assert event.source_port is None


def test_logon_and_reconnect_preserve_initial_and_update_last_source(client, agent_headers):
    first = client.post(
        "/api/v1/agent/events",
        headers=agent_headers,
        json=_envelope([_event(record_id=3001, event_type="LOGON", source_ip="192.0.2.10", source_port=53001)]),
    )
    assert first.status_code == 200
    assert first.json() == {"accepted": 1, "duplicates": 0}

    second = client.post(
        "/api/v1/agent/events",
        headers=agent_headers,
        json=_envelope([_event(record_id=3002, event_type="RECONNECT", source_ip="2001:db8::20", source_port=53002)]),
    )
    assert second.status_code == 200

    with TestingSessionLocal() as db:
        events = db.scalars(select(SessionEvent).order_by(SessionEvent.event_record_id)).all()
        session = db.scalar(select(RdpSession))

        assert [event.source_ip for event in events] == ["192.0.2.10", "2001:db8::20"]
        assert [event.source_port for event in events] == [53001, 53002]
        assert session is not None
        assert session.initial_source_ip == "192.0.2.10"
        assert session.last_source_ip == "2001:db8::20"


def test_invalid_source_is_accepted_and_stored_as_null(client, agent_headers):
    response = client.post(
        "/api/v1/agent/events",
        headers=agent_headers,
        json=_envelope([_event(record_id=3010, event_type="LOGON", source_ip="127.0.0.1", source_port="invalid")]),
    )
    assert response.status_code == 200

    with TestingSessionLocal() as db:
        event = db.scalar(select(SessionEvent))
        session = db.scalar(select(RdpSession))
        assert event is not None and event.source_ip is None and event.source_port is None
        assert session is not None and session.initial_source_ip is None and session.last_source_ip is None


def test_snapshot_updates_last_source_without_rewriting_initial(client, agent_headers):
    first = client.post(
        "/api/v1/agent/events",
        headers=agent_headers,
        json=_envelope([_event(record_id=3020, event_type="LOGON", source_ip="192.0.2.30")]),
    )
    assert first.status_code == 200

    snapshot = client.post(
        "/api/v1/agent/snapshot",
        headers=agent_headers,
        json={
            "contract_version": 1,
            "agent_version": "0.3.0",
            "boot_time_utc": "2026-09-04T09:00:00Z",
            "agent_time_utc": "2026-09-04T12:20:00Z",
            "hostname": "SRV-RDS01",
            "sessions": [
                {
                    "session_id": 42,
                    "username": "alice",
                    "domain": "EXAMPLE",
                    "state": "ACTIVE",
                    "source_ip": "198.51.100.44",
                }
            ],
        },
    )
    assert snapshot.status_code == 200

    with TestingSessionLocal() as db:
        session = db.scalar(select(RdpSession))
        assert session is not None
        assert session.initial_source_ip == "192.0.2.30"
        assert session.last_source_ip == "198.51.100.44"
