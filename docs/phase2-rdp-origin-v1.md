# Phase 2 RDP origin support in API v1

Phase 2 extends the existing `/api/v1` ingestion contract additively so upgraded Windows Agents can send RDP client origin while older Agents continue working unchanged.

## Compatibility

The fields below are optional. Existing Agent 0.2.0 payloads without any origin data remain valid.

Event payload additions:

- `source_ip`: optional IPv4/IPv6 client address;
- `source_port`: optional client source port.

Snapshot session addition:

- `source_ip`: optional IPv4/IPv6 client address observed through WTS.

No existing response field is removed or renamed, and no Windows Agent must be upgraded at the same time as the API.

## Non-rejecting normalization

Origin telemetry is supplementary evidence and must never make an otherwise valid lifecycle event unusable.

The API therefore normalizes source values before persistence:

- valid IPv4 and IPv6 are stored in canonical text form;
- `LOCAL`, empty values, malformed/partial addresses, loopback and unspecified addresses become `NULL`;
- invalid or out-of-range source ports become `NULL`;
- the event or snapshot remains valid when origin is unavailable.

This behavior is intentional because origin coverage differs by Windows version, event type and connection path.

## Session semantics

`session_events.source_ip` and `session_events.source_port` preserve the origin attached to each immutable event.

For consolidated sessions:

- LOGON may initialize both `initial_source_ip` and `last_source_ip`;
- a later LOGON can fill a missing `initial_source_ip` when the session was first discovered by reconciliation;
- RECONNECT updates only `last_source_ip`;
- a snapshot-created session may initialize both values from its current WTS evidence;
- a later snapshot may update only `last_source_ip`, never silently rewrite an already known initial origin.

This allows a reconnect from another client to remain the same RDP session while retaining both the original and most recent source evidence.

## Rollout order

1. Deploy this API release first.
2. Verify Agent 0.2.0 traffic, queries and Grafana remain healthy.
3. Upgrade one modern Windows Server canary to Agent 0.3.0.
4. Validate IPv4/IPv6/no-IP behavior and spool/retry.
5. Upgrade the Windows Server 2008 R2 legacy canary only after the modern canary is stable.
6. Expand to other servers in small batches.

The Phase 1 database schema is already sufficient; this API change requires no new Alembic revision.
