# Correlation worker operational runbook

This runbook covers routine operation, incident containment, recovery and rollback of the asynchronous session-to-device correlation worker.

## Runtime inventory

| Item | Value |
|---|---|
| Unit | `rdp-session-correlation-worker.service` |
| Application | `/opt/rdp-session-api` |
| Environment | `/etc/rdp-session-api/rdp-session-api.env` |
| Runtime user | `rdp-session-api` |
| Metrics | `GET /api/v2/correlation/metrics` |

The environment file contains database and resolver credentials and must remain root-only mode `0600`. Never print, source with shell tracing, or attach it to a ticket.

The worker is asynchronous. Stopping or disabling it halts enrichment but does not stop Agent ingestion or the API.

## Routine health check

```bash
sudo systemctl is-enabled rdp-session-correlation-worker.service
sudo systemctl is-active rdp-session-correlation-worker.service
sudo systemctl status rdp-session-correlation-worker.service --no-pager --full
sudo journalctl -u rdp-session-correlation-worker.service --since '-30 minutes' --no-pager
```

Query metrics without placing the query key in shell history:

```bash
read -rsp 'Query API key: ' RDP_QUERY_KEY
echo
curl -fsS \
  -H "X-API-Key: $RDP_QUERY_KEY" \
  https://rdp-api.example.com/api/v2/correlation/metrics | jq
unset RDP_QUERY_KEY
```

Healthy operation means:

- unit enabled and active without a restart loop;
- feature flag reports the intended state;
- queue age/depth are bounded and normally drain;
- retry count does not grow indefinitely;
- no unexpected `FAILED` backlog;
- `MATCHED`, `AMBIGUOUS` and `UNRESOLVED` terminal outcomes are being persisted;
- Agent ingestion remains healthy independently.

## Incident triage

### Worker inactive or restarting

```bash
sudo systemctl show rdp-session-correlation-worker.service \
  -p ActiveState -p SubState -p Result -p NRestarts
sudo journalctl -u rdp-session-correlation-worker.service -n 100 --no-pager
```

Check that the API service is active, because the worker unit requires it. Confirm the approved checkout, virtual environment and protected environment file exist. Do not run migrations through the worker; migrations belong to `rdp-session-api.service`.

### Worker reports feature disabled

This is expected when `RDP_SESSION_CORRELATION_ENABLED=false`. If correlation should be active, update only the protected environment through the approved configuration process and restart only the worker:

```bash
sudo systemctl restart rdp-session-correlation-worker.service
```

### Resolver configuration errors

Missing URL/key or HTTP 401/403/404 indicate configuration or authorization failure. They are not deterministic correlation results. Validate:

1. resolver base URL;
2. dedicated resolver key and its permissions;
3. resolver route availability;
4. TLS trust and DNS from the API host.

Never send the resolver key to Agents, browsers or query consumers.

### Queue or retry growth

Transport failures and HTTP 408/425/429/5xx enter bounded retry with exponential backoff. Inspect metrics and worker logs, then check resolver availability, latency, rate limits, TLS and network path. Do not manually convert these jobs to `UNRESOLVED`.

If resolver instability could overload operations, contain processing by disabling the feature flag or stopping only the worker. Ingestion remains available.

### Unexpected FAILED jobs

`FAILED` can indicate exhausted transient retries or a permanent resolver protocol violation. Record error codes and sanitized resolver status, then correct the dependency or contract. Do not delete jobs/evidence as an ordinary repair action.

### Unexpected AMBIGUOUS or UNRESOLVED rate

These are valid terminal resolver decisions and are not automatically retried. Validate the historical `ip + occurred_at` inputs and resolver evidence. Never replace temporal resolution with current ARP, DNS, hostname or present-day IP ownership.

### Evidence appears incorrect

Correlation evidence is frozen historical audit data. Do not rewrite or delete it manually. Capture session/event/evidence identifiers and the stored decision snapshot, investigate the resolver timeline, and handle any repair through an explicitly designed and reviewed procedure.

## Controlled resolver test

Use a known IP and historical UTC timestamp. Read the dedicated resolver key interactively and avoid verbose shell output:

```bash
read -rsp 'Resolver API key: ' RESOLVER_KEY
echo
curl -fsS --get \
  -H "X-API-Key: $RESOLVER_KEY" \
  --data-urlencode 'ip=192.0.2.10' \
  --data-urlencode 'at=2026-01-01T12:00:00Z' \
  https://resolver.example.com/api/v1/devices/resolve-network | jq
unset RESOLVER_KEY
```

Use environment-specific values locally; never commit them.

## Upgrade

1. Record deployed commit, API/worker status and correlation metrics.
2. Back up the database according to the deployment procedure.
3. Set the correlation flag false or stop the worker when the release requires controlled processing.
4. Update the checkout and virtual environment.
5. Restart the API first so Alembic completes successfully.
6. Restart the worker.
7. Confirm both units, API health, Agent ingestion and correlation metrics.
8. Re-enable processing when applicable and observe the first batch.

## Containment and rollback

Immediate containment:

```bash
sudo systemctl stop rdp-session-correlation-worker.service
```

Configuration-level containment uses `RDP_SESSION_CORRELATION_ENABLED=false` followed by a worker restart. Existing sessions, jobs and frozen evidence remain intact.

For code rollback, switch to the last approved release, restore compatible dependencies, restart the API first and then the worker. Do not delete terminal evidence during ordinary rollback.

## Credential rotation

1. Create/rotate the dedicated resolver credential.
2. Update the root-only environment file without exposing its contents.
3. Restart only the worker.
4. Confirm authentication succeeds and queue/retry metrics recover.
5. Revoke the previous credential after validation.

## Escalation evidence

Collect deployed commit/version, service state/result/restart count, sanitized worker logs, feature-flag state, queue depth/age, retry and failed counts, terminal outcome totals, resolver HTTP/error codes and one affected session/job identifier. Never collect credentials or unrestricted evidence snapshots.

## Post-recovery gate

- API and worker services active;
- v1/v2 Agent ingestion remains successful;
- queue is stable or draining;
- no unexplained failed backlog;
- one known historical session has the expected frozen evidence;
- one intentionally unresolved case remains terminal without retry;
- Portal navigation works in both Device -> Sessions and Session -> Device directions;
- no secret was exposed during diagnosis.
