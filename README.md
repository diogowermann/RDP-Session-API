# RDP Session API

RDP Session API is a small REST service for receiving Windows Remote Desktop session telemetry and maintaining a consolidated session history.

The project is infrastructure-agnostic. It does not contain environment-specific hostnames, credentials, network addresses, or deployment configuration.

## Current scope

- Versioned `/api/v1` contract.
- Per-server Agent authentication.
- Administrative server registration and credential rotation.
- Idempotent RDP event ingestion.
- Session state consolidation (`ACTIVE`, `DISCONNECTED`, `CLOSED`).
- Snapshot reconciliation for current session state.
- Read/query endpoints protected by a separate API key.
- SQLAlchemy models and Alembic migrations.
- MariaDB production support with SQLite-compatible tests.
- Production systemd deployment with a dedicated service account, protected environment file, automatic restart, migration preflight and journald logging.

The Windows-side collector is maintained separately in the `RDP-Session-Agent` project.

## API surface

Agent ingestion:

- `POST /api/v1/agent/events`
- `POST /api/v1/agent/snapshot`

Read/query API:

- `GET /api/v1/servers`
- `GET /api/v1/servers/{server_id}/summary`
- `GET /api/v1/servers/{server_id}/sessions/active`
- `GET /api/v1/servers/{server_id}/sessions/history`

Operational:

- `GET /api/v1/health`

## Installation

See [docs/installation.md](docs/installation.md) for application setup and [docs/systemd.md](docs/systemd.md) for the production systemd runbook.

## Security model

Agent credentials are unique per registered server. The API stores only a hash of each Agent secret. Read/query endpoints use a separate `X-API-Key`, so exposing the Agent ingestion path does not implicitly expose session history.

Production deployment keeps Uvicorn on loopback, runs under a non-login operating-system account and reads secrets from a root-protected environment file outside the repository checkout.

Do not commit `.env` files, real credentials, internal hostnames, private network addresses, or production reverse-proxy configuration.

## Status

The core event-ingestion, query and snapshot-reconciliation contracts are implemented. The repository includes a systemd deployment path for controlled Linux operation while Windows Server compatibility validation continues in the Agent project.
