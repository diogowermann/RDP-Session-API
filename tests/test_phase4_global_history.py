from datetime import datetime

from app.models import CorrelationEvidence, RdpSession, Server, SessionEvent
from tests.conftest import TestingSessionLocal


QUERY_HEADERS = {"X-API-Key": "test-query-key"}


def _seed_history() -> None:
    with TestingSessionLocal() as db:
        db.add_all(
            [
                Server(
                    id="11111111-1111-1111-1111-111111111111",
                    hostname="RDP-HOST",
                    fqdn="rdp-host.example.test",
                    platform="windows",
                    enabled=True,
                ),
                Server(
                    id="22222222-2222-2222-2222-222222222222",
                    hostname="LINUX-HOST",
                    fqdn="linux-host.example.test",
                    platform="linux",
                    enabled=True,
                ),
            ]
        )

        db.add_all(
            [
                RdpSession(
                    id="session-rdp-closed",
                    server_id="11111111-1111-1111-1111-111111111111",
                    protocol="RDP",
                    platform="windows",
                    provider_session_id="4",
                    boot_id="boot-rdp-001",
                    windows_session_id=4,
                    username="alice",
                    domain="CORP",
                    boot_time=datetime(2026, 9, 4, 12, 0, 0),
                    state="CLOSED",
                    logon_at=datetime(2026, 9, 4, 12, 10, 0),
                    logoff_at=datetime(2026, 9, 4, 12, 40, 0),
                    last_connected_at=datetime(2026, 9, 4, 12, 20, 0),
                    last_disconnected_at=datetime(2026, 9, 4, 12, 19, 0),
                    initial_source_ip="192.0.2.10",
                    last_source_ip="192.0.2.11",
                    correlation_status="MATCHED",
                    disconnect_count=1,
                    duration_minutes=30,
                    end_reason="LOGOFF",
                ),
                RdpSession(
                    id="session-rdp-active",
                    server_id="11111111-1111-1111-1111-111111111111",
                    protocol="RDP",
                    platform="windows",
                    provider_session_id="5",
                    boot_id="boot-rdp-001",
                    windows_session_id=5,
                    username="bob",
                    domain="CORP",
                    boot_time=datetime(2026, 9, 4, 12, 0, 0),
                    state="ACTIVE",
                    logon_at=datetime(2026, 9, 4, 13, 0, 0),
                    last_connected_at=datetime(2026, 9, 4, 13, 0, 0),
                    initial_source_ip="192.0.2.20",
                    last_source_ip="192.0.2.20",
                    correlation_status=None,
                    disconnect_count=0,
                ),
                RdpSession(
                    id="session-ssh-closed",
                    server_id="22222222-2222-2222-2222-222222222222",
                    protocol="SSH",
                    platform="linux",
                    provider_session_id="pts/2",
                    boot_id="boot-linux-001",
                    windows_session_id=900000002,
                    username="carol",
                    domain=None,
                    boot_time=datetime(2026, 9, 4, 11, 0, 0),
                    state="CLOSED",
                    logon_at=datetime(2026, 9, 4, 11, 30, 0),
                    logoff_at=datetime(2026, 9, 4, 11, 45, 0),
                    last_connected_at=datetime(2026, 9, 4, 11, 30, 0),
                    initial_source_ip="198.51.100.10",
                    last_source_ip="198.51.100.10",
                    correlation_status="UNRESOLVED",
                    disconnect_count=0,
                    duration_minutes=15,
                    end_reason="LOGOFF",
                ),
            ]
        )

        db.add_all(
            [
                SessionEvent(
                    id="event-rdp-logon",
                    server_id="11111111-1111-1111-1111-111111111111",
                    protocol="RDP",
                    platform="windows",
                    provider_session_id="4",
                    provider_event_id="1001",
                    boot_id="boot-rdp-001",
                    event_type="LOGON",
                    event_channel="test",
                    event_id=21,
                    event_record_id=1001,
                    windows_session_id=4,
                    username="alice",
                    domain="CORP",
                    boot_time=datetime(2026, 9, 4, 12, 0, 0),
                    occurred_at=datetime(2026, 9, 4, 12, 10, 0),
                    source_ip="192.0.2.10",
                    source_port=55123,
                    event_fingerprint="phase4-rdp-logon",
                    payload_version=2,
                ),
                SessionEvent(
                    id="event-rdp-logoff",
                    server_id="11111111-1111-1111-1111-111111111111",
                    protocol="RDP",
                    platform="windows",
                    provider_session_id="4",
                    provider_event_id="1002",
                    boot_id="boot-rdp-001",
                    event_type="LOGOFF",
                    event_channel="test",
                    event_id=23,
                    event_record_id=1002,
                    windows_session_id=4,
                    username="alice",
                    domain="CORP",
                    boot_time=datetime(2026, 9, 4, 12, 0, 0),
                    occurred_at=datetime(2026, 9, 4, 12, 40, 0),
                    source_ip=None,
                    source_port=None,
                    event_fingerprint="phase4-rdp-logoff",
                    payload_version=2,
                ),
            ]
        )

        db.add(
            CorrelationEvidence(
                id="evidence-rdp-001",
                session_id="session-rdp-closed",
                session_event_id="event-rdp-logon",
                status="MATCHED",
                source_ip="192.0.2.10",
                observed_at=datetime(2026, 9, 4, 12, 10, 0),
                source_device_id="device-001",
                integration_record_id="integration-001",
                asset_tag="LQ301",
                method="source_ip_timestamp",
                confidence=1.0,
                reason_code="UNIQUE_TEMPORAL_MATCH",
                evidence_snapshot={"test": True},
            )
        )
        db.commit()


def test_history_requires_query_auth(client):
    response = client.get("/api/v2/sessions/history")
    assert response.status_code == 401


def test_global_history_filters_and_pagination(client):
    _seed_history()

    response = client.get("/api/v2/sessions/history?limit=2&offset=0", headers=QUERY_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 0
    assert len(payload["items"]) == 2
    assert payload["items"][0]["id"] == "session-rdp-active"
    assert payload["items"][0]["hostname"] == "RDP-HOST"

    response = client.get(
        "/api/v2/sessions/history?protocol=SSH&state=CLOSED&hostname=linux&source_ip=198.51.100.10",
        headers=QUERY_HEADERS,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "session-ssh-closed"
    assert payload["items"][0]["provider_session_id"] == "pts/2"

    response = client.get(
        "/api/v2/sessions/history?username=ALICE&correlation_status=MATCHED",
        headers=QUERY_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["initial_source_ip"] == "192.0.2.10"

    response = client.get(
        "/api/v2/sessions/history?correlation_status=NONE",
        headers=QUERY_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == "session-rdp-active"


def test_history_rejects_invalid_filters(client):
    _seed_history()

    response = client.get(
        "/api/v2/sessions/history?from=2026-09-04T14:00:00Z&to=2026-09-04T13:00:00Z",
        headers=QUERY_HEADERS,
    )
    assert response.status_code == 422

    response = client.get(
        "/api/v2/sessions/history?source_ip=not-an-ip",
        headers=QUERY_HEADERS,
    )
    assert response.status_code == 422


def test_session_detail_and_timeline(client):
    _seed_history()

    detail = client.get("/api/v2/sessions/session-rdp-closed", headers=QUERY_HEADERS)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["session"]["hostname"] == "RDP-HOST"
    assert payload["session"]["boot_id"] == "boot-rdp-001"
    assert payload["server"]["platform"] == "windows"
    assert len(payload["correlation_evidence"]) == 1
    assert payload["correlation_evidence"][0]["asset_tag"] == "LQ301"

    timeline = client.get("/api/v2/sessions/session-rdp-closed/timeline", headers=QUERY_HEADERS)
    assert timeline.status_code == 200
    payload = timeline.json()
    assert payload["session_id"] == "session-rdp-closed"
    assert [event["event_type"] for event in payload["events"]] == ["LOGON", "LOGOFF"]
    assert payload["events"][0]["provider_event_id"] == "1001"
    assert payload["events"][0]["source_port"] == 55123
    assert payload["correlation_evidence"][0]["status"] == "MATCHED"


def test_session_detail_returns_404_for_unknown_session(client):
    _seed_history()

    response = client.get("/api/v2/sessions/does-not-exist", headers=QUERY_HEADERS)
    assert response.status_code == 404

    response = client.get("/api/v2/sessions/does-not-exist/timeline", headers=QUERY_HEADERS)
    assert response.status_code == 404
