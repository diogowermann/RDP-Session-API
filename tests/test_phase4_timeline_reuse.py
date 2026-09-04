from datetime import datetime

from app.models import RdpSession, Server, SessionEvent
from tests.conftest import TestingSessionLocal


QUERY_HEADERS = {"X-API-Key": "test-query-key"}


def test_timeline_is_bounded_to_the_selected_lifecycle(client):
    with TestingSessionLocal() as db:
        server_id = "33333333-3333-3333-3333-333333333333"
        db.add(Server(id=server_id, hostname="REUSE-HOST", platform="windows", enabled=True))
        db.add(
            RdpSession(
                id="selected-session",
                server_id=server_id,
                protocol="RDP",
                platform="windows",
                provider_session_id="7",
                boot_id="same-boot",
                windows_session_id=7,
                username="current.user",
                boot_time=datetime(2026, 9, 4, 10, 0, 0),
                state="CLOSED",
                logon_at=datetime(2026, 9, 4, 12, 0, 0),
                logoff_at=datetime(2026, 9, 4, 12, 30, 0),
                duration_minutes=30,
                disconnect_count=0,
                end_reason="LOGOFF",
            )
        )
        db.add_all(
            [
                SessionEvent(
                    id="old-lifecycle-event",
                    server_id=server_id,
                    protocol="RDP",
                    platform="windows",
                    provider_session_id="7",
                    provider_event_id="old-1",
                    boot_id="same-boot",
                    event_type="LOGON",
                    event_channel="test",
                    event_id=21,
                    event_record_id=1,
                    windows_session_id=7,
                    username="old.user",
                    boot_time=datetime(2026, 9, 4, 10, 0, 0),
                    occurred_at=datetime(2026, 9, 4, 11, 0, 0),
                    event_fingerprint="old-lifecycle-event",
                    payload_version=2,
                ),
                SessionEvent(
                    id="selected-logon",
                    server_id=server_id,
                    protocol="RDP",
                    platform="windows",
                    provider_session_id="7",
                    provider_event_id="selected-1",
                    boot_id="same-boot",
                    event_type="LOGON",
                    event_channel="test",
                    event_id=21,
                    event_record_id=2,
                    windows_session_id=7,
                    username="current.user",
                    boot_time=datetime(2026, 9, 4, 10, 0, 0),
                    occurred_at=datetime(2026, 9, 4, 12, 0, 0),
                    event_fingerprint="selected-logon",
                    payload_version=2,
                ),
                SessionEvent(
                    id="selected-logoff",
                    server_id=server_id,
                    protocol="RDP",
                    platform="windows",
                    provider_session_id="7",
                    provider_event_id="selected-2",
                    boot_id="same-boot",
                    event_type="LOGOFF",
                    event_channel="test",
                    event_id=23,
                    event_record_id=3,
                    windows_session_id=7,
                    username="current.user",
                    boot_time=datetime(2026, 9, 4, 10, 0, 0),
                    occurred_at=datetime(2026, 9, 4, 12, 30, 0),
                    event_fingerprint="selected-logoff",
                    payload_version=2,
                ),
                SessionEvent(
                    id="next-lifecycle-event",
                    server_id=server_id,
                    protocol="RDP",
                    platform="windows",
                    provider_session_id="7",
                    provider_event_id="next-1",
                    boot_id="same-boot",
                    event_type="LOGON",
                    event_channel="test",
                    event_id=21,
                    event_record_id=4,
                    windows_session_id=7,
                    username="next.user",
                    boot_time=datetime(2026, 9, 4, 10, 0, 0),
                    occurred_at=datetime(2026, 9, 4, 13, 0, 0),
                    event_fingerprint="next-lifecycle-event",
                    payload_version=2,
                ),
            ]
        )
        db.commit()

    response = client.get("/api/v2/sessions/selected-session/timeline", headers=QUERY_HEADERS)
    assert response.status_code == 200
    event_ids = [event["id"] for event in response.json()["events"]]
    assert event_ids == ["selected-logon", "selected-logoff"]
