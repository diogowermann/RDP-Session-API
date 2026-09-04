# Phase 1 additive origin schema

Phase 1 prepares RDP Session API to receive connection-origin data and later correlation results without changing the current Agent `/api/v1` request contract.

## Compatibility rule

Existing Windows Agents continue sending the same v1 event and snapshot payloads. No `source_ip`, `source_port`, correlation field, or protocol field is required from the Agent in this phase.

The API writes `protocol=RDP` internally for current v1 traffic. Existing rows are backfilled to `RDP` by migration `0002`. Origin and correlation fields remain nullable until the later Agent and enrichment phases populate them.

The existing v1 response schemas are intentionally unchanged in Phase 1. New storage fields are internal preparation for later additive read surfaces and `/api/v2`.

## Schema additions

### `session_events`

- `protocol` — non-null, defaults to `RDP` for the current contract.
- `source_ip` — nullable IPv4/IPv6 text, maximum 45 characters.
- `source_port` — nullable client source port.
- `correlation_status` — nullable lifecycle marker for future enrichment.

### `sessions`

- `protocol` — non-null, defaults to `RDP`.
- `initial_source_ip` — first known source for the session, nullable.
- `last_source_ip` — most recently known source, nullable.
- `correlation_status` — nullable session-level enrichment state.

### `correlation_evidence`

Reserved persistence for frozen resolver results. A row may reference both the consolidated session and the originating immutable event. It can retain the resolved device identifiers, asset tag, method, confidence, reason code, and a JSON evidence snapshot.

Phase 1 creates the structure only; it does not call Integration-Service or write evidence rows.

### `correlation_jobs`

Reserved queue state for the asynchronous enrichment phase. It stores the session/event target, source IP and observation timestamp, status, attempt count, retry timing, and last error code.

Phase 1 creates the structure only; no worker or scheduler is enabled.

## Index strategy

The existing per-server indexes are preserved. Additional indexes prepare the future global-history and enrichment workloads for:

- event/session time;
- `server_id` through the existing composite indexes;
- `protocol`;
- `username`;
- source IP;
- correlation job status and retry time.

Index usefulness and query plans must be rechecked with real production volume before increasing retention or enabling SSH ingestion.

## Migration

Upgrade:

```bash
.venv/bin/alembic -c alembic.ini upgrade head
```

Expected head after deployment:

```text
0002 (head)
```

Downgrade gate:

```bash
.venv/bin/alembic -c alembic.ini downgrade 0001
```

The downgrade removes only the Phase 1 additive fields, indexes, and correlation-ready tables. Before any production downgrade, preserve a fresh database backup. After Phase 2 begins writing origin data, downgrade must be treated as data-destructive for those new fields.

## Validation gate

Before Phase 1 is considered complete:

1. Apply `0002` to a controlled database and confirm the new columns/tables/indexes.
2. Confirm existing rows retain their identifiers and have `protocol=RDP` with null origin/correlation fields.
3. Run the complete pytest suite, including v1 payload tests that omit every Phase 1 field.
4. Execute `downgrade 0001` on the controlled database and confirm the legacy schema remains usable.
5. Re-apply `upgrade head` and re-run tests.
6. In production, verify `/api/v1/health`, Agent `last_seen`, snapshots, spool behavior, and existing Grafana/query endpoints before beginning Phase 2.
