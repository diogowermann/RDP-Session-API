# Phase 4 — Global session history API

Phase 4 extends the read-only `/api/v2` surface so the Portal can investigate RDP and SSH sessions through one normalized contract.

## Scope

This release is query-only. It does not change Agent ingestion, the v1 Grafana contract, database schema, correlation logic, or Agent credentials.

The Portal backend is expected to call the API with the existing query API key. User-level authorization remains the responsibility of the Portal backend; the query key must never be exposed to browser JavaScript.

## Endpoints

### `GET /api/v2/sessions/history`

Returns a globally paginated session list across servers and protocols.

Supported filters:

- `from` / `to`: session logon time range;
- `server_id`;
- `hostname`: case-insensitive substring against hostname or FQDN;
- `protocol`: `RDP` or `SSH`;
- `state`: `ACTIVE`, `DISCONNECTED`, or `CLOSED`;
- `username`: case-insensitive exact match;
- `provider_session_id`;
- `source_ip`: matches initial or last source IP;
- `correlation_status`: case-insensitive exact match; use `NONE` for sessions not yet correlated;
- `limit`: 1–500;
- `offset`: non-negative integer.

The response includes `total`, `limit`, and `offset` so the Portal can implement deterministic pagination.

The default query does not force `CLOSED`; it returns all session states. Consumers that need only historical closed sessions must request `state=CLOSED` explicitly.

### `GET /api/v2/sessions/{session_id}`

Returns the normalized session, server metadata, and any frozen correlation evidence currently attached to the session.

Correlation evidence may be empty until the resolver/enrichment phases are deployed.

### `GET /api/v2/sessions/{session_id}/timeline`

Returns the immutable provider events associated with the normalized session plus correlation evidence.

Event matching is based on:

- server;
- protocol;
- provider session identifier;
- boot identifier when present.

This keeps RDP numeric session IDs and SSH identifiers such as `pts/2` in the same read model.

## Compatibility

- `/api/v1` is unchanged.
- Existing RDP Agents continue posting to v1.
- v2 Agent ingestion is unchanged.
- No Alembic migration is required for this release.
- Grafana's current v1 queries and alerts are not moved to v2 in Phase 4.

## Security boundary

The API authenticates read requests with the internal query key. This is service-to-service authentication, not end-user RBAC.

The Portal backend must:

1. authenticate the Portal user using its existing identity/session mechanism;
2. authorize access to the remote-session module before querying this API;
3. keep the query key server-side;
4. return only the fields required by the Portal interface.

## Production gate

Before deploying the Portal interface:

1. deploy API 0.5.0;
2. verify v1 health and all existing RDP Agents;
3. verify `/api/v2/sessions/history` pagination and filters against production data;
4. verify detail/timeline for at least one known RDP session;
5. verify an unknown session returns 404;
6. confirm Grafana remains unchanged;
7. only then connect the Portal backend to the v2 query surface.
