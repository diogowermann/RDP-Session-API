# Grafana logon alerting

RDP Session API exposes a query endpoint designed specifically for Grafana alert rules that need to notify on new RDP logons across **all enabled monitored servers**.

## Endpoint

```http
GET /api/v1/alerts/logons?lookback_minutes=5
X-API-Key: <query-api-key>
```

`lookback_minutes` controls how long a recently received LOGON remains visible to the alert rule.

- default: `5`
- minimum: `1`
- maximum: `60`

The endpoint uses the same query API key as the other read endpoints.

## Why the alert feed is event-based

The alert feed is built from immutable `LOGON` events rather than from the current `ACTIVE` session count.

This is intentional:

- a short session can still be detected even if it logs off before the next Grafana evaluation;
- a disconnected/reconnected session does not become a new logon alert;
- every logon has its own stable `alert_id`;
- replaying an Agent spool batch does not create another event because API ingestion is idempotent;
- a delayed spool delivery can still alert when the API finally receives the original LOGON.

The lookback filter uses the API `received_at` timestamp, while `logon_at` remains the actual Windows event time reported by the Agent.

## Response

Example:

```json
[
  {
    "alert_id": "c8b4e3e6-1ad3-4cf5-a3f3-70c65a7d3d79",
    "server_id": "00000000-0000-0000-0000-000000000001",
    "hostname": "SRV-RDS01",
    "principal": "EXAMPLE\\alice",
    "username": "alice",
    "domain": "EXAMPLE",
    "logon_at": "2026-08-24T11:05:12Z",
    "alert_value": 1
  }
]
```

Each object represents one alert instance. `alert_id` is unique per accepted LOGON event.

`hostname` is resolved from the registered server metadata. If a hostname is unavailable, the API falls back to FQDN and then to the server ID so the field is never empty.

## Recommended Grafana configuration

The instructions below assume an Infinity datasource already configured with:

```text
Base URL: https://rdp-api.example.com/api/v1
Header:   X-API-Key: <query-api-key>
```

The Grafana server must trust the TLS certificate chain used by the API.

### 1. Create the alert rule

Open:

```text
Alerting -> Alert rules -> New alert rule
```

Suggested name:

```text
RDP Logon Detected
```

### 2. Query the alert endpoint

Use the Infinity datasource with a backend parser so Grafana Alerting evaluates the query server-side.

```text
Method: GET
URL:    /alerts/logons?lookback_minutes=5
Type:   JSON
Parser: Backend
```

Expose these fields in the result:

| Field | Grafana use |
| --- | --- |
| `alert_id` | string label; unique alert instance |
| `hostname` | string label |
| `principal` | string label |
| `username` | string label |
| `domain` | string label |
| `logon_at` | string label / notification context |
| `alert_value` | number used by the condition |

Keep `alert_value` as the numeric field used by the alert expression.

### 3. Condition

Create a threshold expression equivalent to:

```text
alert_value > 0
```

Use no pending delay (`For = 0s`) when the requirement is immediate notification after the next evaluation.

A one-minute evaluation interval is a practical default because the Windows Agent Scheduled Task also runs every minute.

### 4. No-data behavior

When no new logons exist, the endpoint returns an empty array.

Configure the rule so **No Data is treated as Normal/OK**, not as an alert condition. An empty result is the expected steady state.

### 5. Notification annotations

Suggested summary:

```text
RDP logon detected on {{ $labels.hostname }}
```

Suggested description:

```text
User {{ $labels.principal }} logged on to {{ $labels.hostname }} at {{ $labels.logon_at }}.
```

The unique `alert_id` label prevents simultaneous logons on the same server or by the same user from collapsing into one alert instance.

## Alert lifecycle

With a five-minute lookback and a one-minute evaluation interval:

```text
Windows LOGON
    -> Agent collects event
    -> API accepts immutable LOGON
    -> /alerts/logons exposes event for 5 minutes
    -> Grafana creates one alert instance by alert_id
    -> notification is sent
    -> event ages out of lookback window
    -> alert instance resolves
```

A later LOGON receives a different `alert_id` and creates a new alert instance.

## Choosing the lookback window

The lookback should be larger than the combined expected Agent collection and Grafana evaluation intervals.

For the default deployment:

```text
Agent execution:       1 minute
Grafana evaluation:    1 minute
Recommended lookback:  5 minutes
```

Using a larger window does not normally create repeated notifications because the same `alert_id` remains the same alert instance while it is visible.

## Security

The alert endpoint is read-only and uses the normal query API authentication boundary. Do not place the query key directly in dashboard JSON or alert expressions when the datasource can store it securely.

Never publish production API URLs, API keys, server IDs, usernames, or internal hostnames in this public repository.
