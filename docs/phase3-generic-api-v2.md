# Phase 3: generic `/api/v2` contract

Phase 3 introduces a protocol-neutral API surface for remote sessions while keeping the production RDP `/api/v1` contract available during the initial rollout.

## Compatibility rule

- `/api/v1` remains the legacy Windows/RDP contract.
- RDP Agent 0.3.0 does not need to migrate to v2.
- `/api/v2` accepts generic provider identifiers suitable for both RDP and SSH.
- v1 ingestion is normalized internally into the same domain model used by v2.
- v1 query and alert endpoints remain RDP-only so future SSH telemetry does not change Grafana behavior.

## Generic identity

A v2 event is identified by:

- `platform`: agent/provider platform (`windows` or `linux`);
- `protocol`: `RDP` or `SSH`;
- `boot_id`: opaque provider boot identifier;
- `provider_session_id`: opaque string such as `4` or `pts/2`;
- `provider_event_id`: opaque provider event identifier such as a Windows record id or journald cursor.

The database keeps the original Windows-specific columns for backward compatibility. New domain logic uses the generic fields. Legacy columns are compatibility shadows for v2 data and are not identity fields.

## v2 ingestion endpoints

### `POST /api/v2/agent/events`

Example:

```json
{
  "contract_version": 2,
  "agent_version": "0.1.0",
  "platform": "linux",
  "protocol": "SSH",
  "boot_id": "8e25c8d0-opaque-provider-boot-id",
  "agent_time_utc": "2026-09-04T13:00:05Z",
  "events": [
    {
      "type": "LOGON",
      "provider_session_id": "pts/2",
      "provider_event_id": "journal-cursor-example",
      "username": "example.user",
      "source_ip": "192.0.2.20",
      "source_port": 53122,
      "occurred_at": "2026-09-04T13:00:00Z"
    }
  ]
}
```

SSH currently accepts `LOGON` and `LOGOFF`. RDP also supports `DISCONNECT` and `RECONNECT`.

### `POST /api/v2/agent/snapshot`

Snapshots use the same `platform`, `protocol`, `boot_id` and opaque `provider_session_id` model. They reconcile current state without becoming the primary event source.

## v2 read endpoints

All read endpoints require the configured query API key, as v1 does.

- `GET /api/v2/servers`
- `GET /api/v2/sessions/active`
- `GET /api/v2/sessions/history`
- `GET /api/v2/alerts/logons`

Phase 3 provides the common read surface. Phase 4 expands global history filters, detail/timeline endpoints and Portal integration.

## Idempotency and ordering

v1 retains its original fingerprint algorithm so a spool replay across the 0.3.0 -> 0.4.0 API upgrade does not create duplicate raw events.

v2 fingerprints use server, platform, protocol, boot id, provider event id, event type and provider session id. Replaying the same event is safe.

The session reducer ignores stale state transitions that would move a session backward in time. A delayed LOGON older than an already closed matching session does not create a second session.

## Source address behavior

The same non-rejecting normalization introduced in Phase 2 remains in force:

- valid IPv4/IPv6 is canonicalized;
- loopback, unspecified, `LOCAL`, malformed or partial values become `null`;
- invalid origin evidence never invalidates the session event.

## Authentication

Agent authentication remains per-server using `X-Server-ID` plus bearer credential. Query authentication remains separate through `X-API-Key`.

## OpenAPI

The running FastAPI application publishes the complete v1 + v2 contract at `/openapi.json`. Contract tests assert the presence of the v2 ingestion and read surfaces.

## Migration

Migration `0003` adds generic identity columns and backfills existing RDP rows:

- existing platform -> `windows`;
- `provider_session_id` <- legacy Windows session id;
- `provider_event_id` <- legacy event record id;
- `boot_id` <- persisted legacy boot time;
- server `last_boot_id` <- persisted `last_boot_at` when available.

No historical source IP or correlation data is invented.

Upgrade:

```bash
.venv/bin/alembic -c alembic.ini upgrade head
```

Expected head:

```text
0003 (head)
```

Downgrade before v2-only data becomes operationally relevant:

```bash
.venv/bin/alembic -c alembic.ini downgrade 0002
```

The downgrade removes only the generic v2 columns/indexes. Existing v1 schema and Phase 1 origin/correlation structures remain.

## Phase 3 production gate

Before closing Phase 3:

1. take a fresh database backup;
2. deploy API 0.4.0 and migration `0003`;
3. verify all RDP Agents 0.3.0 remain healthy on `/api/v1`;
4. verify existing Grafana queries/alerts are unchanged;
5. exercise valid/invalid v2 contract examples;
6. verify duplicate and out-of-order tests;
7. verify `/openapi.json` includes both v1 and v2 surfaces.
