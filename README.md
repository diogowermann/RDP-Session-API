# RDP Session API

RDP Session API is the central REST service of a lightweight remote-session monitoring stack. The production `/api/v1` surface remains focused on Windows RDP, while the additive `/api/v2` contract normalizes provider identity so the same domain can support RDP and SSH without forcing an immediate Windows Agent migration.

The project is intentionally infrastructure-agnostic. This repository does **not** contain environment-specific hostnames, credentials, private addresses, TLS material, or production reverse-proxy configuration.

The Windows collector is maintained separately in [RDP-Session-Agent](https://github.com/diogowermann/RDP-Session-Agent).

## Current capabilities

- Backward-compatible `/api/v1` Windows/RDP contract.
- Generic `/api/v2` contract with `platform`, `protocol`, `boot_id`, `provider_session_id` and `provider_event_id`.
- Internal normalization of v1 RDP payloads into the common session domain.
- Per-server Agent authentication with individually registered credentials.
- Administrative server registration and credential rotation.
- Idempotent event ingestion with v1 replay compatibility.
- Consolidated session states: `ACTIVE`, `DISCONNECTED`, and `CLOSED`.
- Snapshot reconciliation for current-state correction.
- Optional IPv4/IPv6 connection origin.
- Separate `X-API-Key` protection for read/query endpoints.
- Cross-server LOGON alert feeds.
- SQLAlchemy persistence with Alembic migrations.
- MariaDB / MySQL production support and SQLite-compatible tests.
- Managed Linux deployment through systemd.
- Loopback-only Uvicorn deployment behind an HTTPS reverse proxy.
- OpenAPI contract at `/openapi.json`.

## API surface

### Legacy v1 — Windows/RDP

- `POST /api/v1/agent/events`
- `POST /api/v1/agent/snapshot`
- `GET /api/v1/servers`
- `GET /api/v1/servers/{server_id}/summary`
- `GET /api/v1/servers/{server_id}/sessions/active`
- `GET /api/v1/servers/{server_id}/sessions/history`
- `GET /api/v1/alerts/logons?lookback_minutes=5`
- `GET /api/v1/health`

The v1 read surface remains RDP-only so future SSH telemetry cannot change existing Grafana behavior.

### Generic v2 — remote sessions

- `POST /api/v2/agent/events`
- `POST /api/v2/agent/snapshot`
- `GET /api/v2/servers`
- `GET /api/v2/sessions/active`
- `GET /api/v2/sessions/history`
- `GET /api/v2/alerts/logons`
- `GET /api/v2/health`

Agent ingestion requires:

```http
X-Server-ID: <server-id>
Authorization: Bearer <agent-secret>
```

Read/query endpoints require:

```http
X-API-Key: <query-api-key>
```

## Documentation

- [Documentation index](docs/README.md)
- [Installation and configuration](docs/installation.md)
- [System architecture](docs/system-architecture.md)
- [Grafana logon alerting](docs/grafana-alerting.md)
- [systemd deployment and operations](docs/systemd.md)
- [Phase 3 generic API v2 contract](docs/phase3-generic-api-v2.md)

## Security model

- Every monitored server receives a unique Agent credential.
- The API stores only a hash of each Agent secret.
- Agent credentials cannot query session history.
- Read access uses a separate query API key.
- Production deployment keeps Uvicorn on loopback and exposes only the reverse proxy.
- Runtime secrets belong in a protected environment file outside the Git checkout.
- Session telemetry does not include commands, terminal contents, passwords or private keys.

## Public repository safety

Never commit:

- production `.env` files;
- real API keys or Agent secrets;
- private DNS names or addresses;
- TLS private keys or certificates;
- database passwords;
- environment-specific reverse-proxy configuration.

All documentation examples use fictitious values intentionally.

## License

Released under the [MIT License](LICENSE).
