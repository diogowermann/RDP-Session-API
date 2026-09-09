# Phase 6 asynchronous session correlation

Phase 6 enriches persisted remote-session telemetry with frozen device/asset evidence from the Integration-Service temporal network resolver.

The correlation path is deliberately asynchronous. Agent ingestion never waits for the resolver and does not make external calls.

## Data flow

```text
Agent -> RDP/SSH event -> session_events + sessions
                              |
                              v
                    correlation worker
                              |
                              +-> discover source_ip events
                              +-> correlation_jobs
                              +-> GET resolver(ip, occurred_at)
                              +-> correlation_evidence
```

The worker uses the Phase 1 `correlation_jobs` and `correlation_evidence` tables. No new schema migration is required for this phase.

## Resolver contract

The worker calls:

```text
GET /api/v1/devices/resolve-network?ip=<source-ip>&at=<utc-timestamp>
X-API-Key: <dedicated resolver key>
```

The resolver service remains authoritative for temporal network-to-device/asset correlation. Remote Session API never derives identity from current ARP, DNS, hostname or present-day IP ownership.

Accepted deterministic outcomes:

- `MATCHED`
- `AMBIGUOUS`
- `UNRESOLVED`

`AMBIGUOUS` and `UNRESOLVED` are terminal evidence, not transport failures, and are therefore not retried automatically.

## Frozen evidence

Each successful resolver response is persisted as one immutable `correlation_evidence` row associated with the source session event.

Persistence mapping:

- `source_device_id` stores the Integration-Service `Device.uuid` when the resolver returns `MATCHED`;
- `integration_record_id` stores the single matched asset-link identifier when present;
- `asset_tag` stores the resolved asset tag when present;
- `method` and `reason_code` preserve the resolver decision metadata;
- the current resolver confidence string is mapped to a numeric storage score (`deterministic=1.0`, `none=0.0`) while the original value remains in the JSON snapshot;
- `evidence_snapshot` stores the complete resolver response used for the decision.

Evidence IDs are deterministic per source event. If a terminal evidence row already exists, the worker restores status from that row and does not call the resolver again. A future DHCP lease or current resolver state therefore cannot silently rewrite historical evidence.

## Job lifecycle

```text
PENDING -> MATCHED
        -> AMBIGUOUS
        -> UNRESOLVED
        -> RETRY -> ... -> terminal result
                   \-> FAILED after max attempts
```

Automatic retry is limited to resolver availability failures:

- connection/transport errors;
- HTTP 408/425/429;
- HTTP 5xx.

The delay uses bounded exponential backoff. `correlation_max_attempts` prevents infinite retry.

Authentication or endpoint-configuration errors (HTTP 401/403/404, missing base URL or missing key) are worker configuration failures. They do not intentionally consume the queue as deterministic failures.

Other invalid resolver responses are treated as permanent protocol failures for the affected job and become `FAILED`.

## Discovery and session association

The worker discovers persisted `session_events` that have a usable `source_ip` and no correlation status.

It associates an event only with a session matching:

- server;
- protocol;
- provider/legacy session identifier;
- boot instance;
- username/domain;
- event timestamp inside the session lifecycle.

If no deterministic session is available, no job is created and the event remains eligible for a later discovery cycle.

The discovery path is local database work only; the ingest HTTP transaction is not coupled to resolver availability.

## Feature flag and environment

The worker is safe to deploy before activation.

```text
RDP_SESSION_CORRELATION_ENABLED=false
RDP_SESSION_RESOLVER_BASE_URL=<internal resolver base URL>
RDP_SESSION_RESOLVER_API_KEY=<dedicated service-to-service key>
RDP_SESSION_RESOLVER_TIMEOUT_SECONDS=5
RDP_SESSION_CORRELATION_POLL_SECONDS=30
RDP_SESSION_CORRELATION_BATCH_SIZE=100
RDP_SESSION_CORRELATION_MAX_ATTEMPTS=5
RDP_SESSION_CORRELATION_RETRY_BASE_SECONDS=60
```

The resolver key must remain only in the protected API environment file. Do not put it in Agent configuration, query strings, repository files, shell tracing or documentation.

## Runtime separation

The API and correlation worker are independent systemd processes:

```text
rdp-session-api.service
rdp-session-correlation-worker.service
```

Both use the same database and protected environment file. The API service remains responsible for Alembic migrations. The worker performs no migration at startup and can remain active-but-disabled while the feature flag is false.

## Metrics

Authenticated query clients can read:

```text
GET /api/v2/correlation/metrics
X-API-Key: <query key>
```

The response exposes:

- queue depth;
- pending and retry counts;
- failed jobs;
- `MATCHED`, `AMBIGUOUS` and `UNRESOLVED` counts;
- match rate over deterministic terminal resolver outcomes;
- oldest queue age;
- average terminal processing latency;
- persisted evidence count;
- current feature-flag state.

These metrics are intended for Grafana/operations and contain no resolver credential.

## Safe rollout

1. Back up the Remote Session API database.
2. Deploy version 0.6.0 with `RDP_SESSION_CORRELATION_ENABLED=false`.
3. Install/start the correlation worker and confirm it reports that the feature is disabled.
4. Confirm existing Agent ingestion, snapshots, v1/v2 history and Grafana remain healthy.
5. Configure the resolver base URL and a dedicated resolver API key while keeping the feature flag false.
6. From the API host, validate one known `ip + timestamp` resolver request without printing the key.
7. Inspect the current count of source events that have no correlation status.
8. Enable `RDP_SESSION_CORRELATION_ENABLED=true` and restart only the correlation worker.
9. Observe the first batch: queue, terminal results, retries, failures and evidence rows.
10. Validate one known historical session against the frozen evidence snapshot.
11. Confirm a deliberately unresolved timestamp remains `UNRESOLVED` and is not retried.
12. Keep Agent ingestion running throughout the test to prove correlation failures do not block telemetry.

## Rollback

Immediate processing rollback:

```text
RDP_SESSION_CORRELATION_ENABLED=false
```

Restart the correlation worker after changing the environment. Existing sessions/events and frozen evidence remain intact.

Stopping or disabling `rdp-session-correlation-worker.service` also halts enrichment without affecting the API or Agents.

Do not delete terminal evidence as part of ordinary rollback. It is historical audit data.

## Phase 6 exit gate

Phase 6 can be closed when:

- worker and resolver client tests are green;
- production deploy is stable with the feature flag initially off;
- resolver authentication is service-to-service and not exposed to Agents or browsers;
- known `MATCHED`, `AMBIGUOUS`/`UNRESOLVED` behavior is validated;
- transient resolver failure creates bounded retries without blocking ingest;
- a frozen evidence row is not rewritten when resolver state later changes;
- metrics expose match rate, unresolved/ambiguous counts, queue age and latency;
- no unexpected `FAILED` backlog remains after the controlled rollout.
