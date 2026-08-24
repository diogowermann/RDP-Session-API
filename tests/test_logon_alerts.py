from datetime import timedelta

from app.models import Server, SessionEvent
from app.timeutils import utc_now
from tests.conftest import TestingSessionLocal


def _query_headers() -> dict[str, str]:
    return {"X-API-Key": "test-query-key"}


def _event(
    *,
    server_id: str,
    record_id: int,
    username: str,
    domain: str | None,
    event_type: str,
    received_offset_minutes: int,
) -> SessionEvent:
    now = utc_now()
    return SessionEvent(
        server_id=server_id,
        event_type=event_type,
        event_channel="Microsoft-Windows-TerminalServices-LocalSessionManager/Operational",
        event_id=21 if event_type == "LOGON" else 24,
        event_record_id=record_id,
        windows_session_id=record_id,
        username=username,
        domain=domain,
        boot_time=now - timedelta(hours=2),
        occurred_at=now - timedelta(minutes=max(0, received_offset_minutes)),
        received_at=now - timedelta(minutes=received_offset_minutes),
        event_fingerprint=f"{record_id:064x}",
        payload_version=1,
    )


def test_logon_alert_feed_requires_query_key(client):
    response = client.get("/api/v1/alerts/logons")
    assert response.status_code == 401


def test_logon_alert_feed_returns_recent_logons_across_enabled_servers(client, agent_identity):
    primary_server_id, _ = agent_identity
    secondary_server_id = "22222222-2222-2222-2222-222222222222"
    disabled_server_id = "33333333-3333-3333-3333-333333333333"

    with TestingSessionLocal() as db:
        primary = db.get(Server, primary_server_id)
        primary.hostname = "SRV-RDS01"

        db.add(Server(id=secondary_server_id, hostname="SRV-RDS02", enabled=True))
        db.add(Server(id=disabled_server_id, hostname="SRV-RDS03", enabled=False))
        db.add_all(
            [
                _event(
                    server_id=primary_server_id,
                    record_id=101,
                    username="alice",
                    domain="EXAMPLE",
                    event_type="LOGON",
                    received_offset_minutes=1,
                ),
                _event(
                    server_id=secondary_server_id,
                    record_id=102,
                    username="bob",
                    domain=None,
                    event_type="LOGON",
                    received_offset_minutes=2,
                ),
                _event(
                    server_id=primary_server_id,
                    record_id=103,
                    username="alice",
                    domain="EXAMPLE",
                    event_type="DISCONNECT",
                    received_offset_minutes=1,
                ),
                _event(
                    server_id=primary_server_id,
                    record_id=104,
                    username="old-user",
                    domain="EXAMPLE",
                    event_type="LOGON",
                    received_offset_minutes=10,
                ),
                _event(
                    server_id=disabled_server_id,
                    record_id=105,
                    username="disabled-user",
                    domain="EXAMPLE",
                    event_type="LOGON",
                    received_offset_minutes=1,
                ),
            ]
        )
        db.commit()

    response = client.get(
        "/api/v1/alerts/logons?lookback_minutes=5",
        headers=_query_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {item["hostname"] for item in body} == {"SRV-RDS01", "SRV-RDS02"}
    assert {item["principal"] for item in body} == {"EXAMPLE\\alice", "bob"}
    assert all(item["alert_value"] == 1 for item in body)
    assert len({item["alert_id"] for item in body}) == 2
