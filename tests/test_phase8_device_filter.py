from tests.test_phase4_global_history import QUERY_HEADERS, _seed_history


def test_history_filters_by_source_device_id(client):
    _seed_history()

    response = client.get(
        "/api/v2/sessions/history?source_device_id=device-001",
        headers=QUERY_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "session-rdp-closed"


def test_history_device_filter_is_fail_closed_for_unknown_device(client):
    _seed_history()

    response = client.get(
        "/api/v2/sessions/history?source_device_id=device-does-not-exist",
        headers=QUERY_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []


def test_history_rejects_oversized_source_device_id(client):
    _seed_history()

    response = client.get(
        "/api/v2/sessions/history?source_device_id=" + ("x" * 65),
        headers=QUERY_HEADERS,
    )

    assert response.status_code == 422
