# Phase 8: operational unification

Phase 8 connects the normalized RDP/SSH history to the Device Registry and operational views without changing ingestion semantics or the persisted session schema.

## API scope in this repository

The Remote Session API remains the source of truth for session facts and frozen correlation evidence. Phase 8 adds the missing query primitive required by the Portal for Device Registry -> Remote Sessions navigation:

```text
GET /api/v2/sessions/history?source_device_id=<device-uuid>
```

The filter matches sessions that have at least one persisted `correlation_evidence.source_device_id` equal to the requested device identifier.

The implementation uses a subquery against correlation evidence instead of joining evidence into the history result. This preserves one row per session even when a session has multiple evidence records.

## Semantics

- No current-state IP/hostname lookup is performed.
- No new correlation is calculated during a history request.
- Only frozen evidence already persisted by the Phase 6 worker participates.
- Unknown device identifiers return an empty page.
- Existing RDP/SSH, time, server, username, source IP, state and correlation filters remain composable with the device filter.
- No database migration is required.

## Consumers

The Portal can use this filter to implement a contextual link from one Device Registry record to the remote sessions historically correlated to that device.

The reverse direction, Session -> Device Registry, uses the `source_device_id`, `integration_record_id`, `asset_tag`, `method` and `confidence` already returned by the session detail/timeline correlation evidence contract.

## Compatibility

This is an additive query change:

- `/api/v1` ingestion/query behavior is unchanged;
- `/api/v2` Agent ingestion is unchanged;
- existing history consumers that omit `source_device_id` receive the same result set as before;
- no Agent update is required.

## Phase 8 API gate

Before deploying API 0.7.0:

1. automated tests must confirm a known device returns only its correlated sessions;
2. an unknown device must return an empty result without fallback;
3. invalid/oversized input must be rejected by request validation;
4. existing Phase 3/4/6 contract tests must remain green;
5. production validation must use a known correlated Device UUID and confirm pagination/count remain consistent.
