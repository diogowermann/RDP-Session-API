from datetime import datetime

from app.models import RdpSession
from tests.conftest import TestingSessionLocal


def _query_headers() -> dict[str, str]:
    return {"X-API-Key": "test-query-key"}


def test_query_api_requires_key(client, agent_identity):
    response = client.get("/api/v1/servers")
    assert response.status_code == 401


def test_server_summary_active_and_history(client, agent_identity):
    server_id, _ = agent_identity
    with TestingSessionLocal() as db:
        db.add_all(
            [
                RdpSession(
                    server_id=server_id,
                    windows_session_id=2,
                    username="alice",
                    domain="EXAMPLE",
                    boot_time=datetime(2026, 8, 20, 8, 0),
                    state="ACTIVE",
                    logon_at=datetime(2026, 8, 20, 8, 10),
                ),
                RdpSession(
                    server_id=server_id,
                    windows_session_id=3,
                    username="bob",
                    domain="EXAMPLE",
                    boot_time=datetime(2026, 8, 20, 8, 0),
                    state="DISCONNECTED",
                    logon_at=datetime(2026, 8, 20, 8, 20),
                    last_disconnected_at=datetime(2026, 8, 20, 9, 0),
                    disconnect_count=1,
                ),
                RdpSession(
                    server_id=server_id,
                    windows_session_id=4,
                    username="carol",
                    domain="EXAMPLE",
                    boot_time=datetime(2026, 8, 20, 8, 0),
                    state="CLOSED",
                    logon_at=datetime(2026, 8, 20, 7, 0),
                    logoff_at=datetime(2026, 8, 20, 7, 45),
                    duration_minutes=45,
                    end_reason="LOGOFF",
                ),
            ]
        )
        db.commit()

    summary = client.get(
        f"/api/v1/servers/{server_id}/summary",
        headers=_query_headers(),
    )
    assert summary.status_code == 200
    assert summary.json()["active_users"] == 1
    assert summary.json()["active_sessions"] == 1
    assert summary.json()["disconnected_sessions"] == 1
    assert summary.json()["open_sessions"] == 2

    active = client.get(
        f"/api/v1/servers/{server_id}/sessions/active",
        headers=_query_headers(),
    )
    assert active.status_code == 200
    assert [item["username"] for item in active.json()] == ["alice"]

    history = client.get(
        f"/api/v1/servers/{server_id}/sessions/history?username=CAROL",
        headers=_query_headers(),
    )
    assert history.status_code == 200
    assert len(history.json()["items"]) == 1
    assert history.json()["items"][0]["duration_minutes"] == 45
