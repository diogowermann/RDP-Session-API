def test_agent_endpoint_requires_authentication(client):
    response = client.post(
        "/api/v1/agent/events",
        json={
            "contract_version": 1,
            "agent_version": "0.1.0",
            "boot_time_utc": "2026-08-20T10:00:00Z",
            "agent_time_utc": "2026-08-20T10:01:00Z",
            "events": [
                {
                    "event_id": 21,
                    "record_id": 1,
                    "type": "LOGON",
                    "session_id": 2,
                    "username": "alice",
                    "domain": "EXAMPLE",
                    "occurred_at": "2026-08-20T10:00:30Z",
                }
            ],
        },
    )
    assert response.status_code == 401
