# RDP Session API

RDP Session API is a small REST service for receiving Windows Remote Desktop session telemetry and maintaining a consolidated session history.

The project is designed to remain infrastructure-agnostic. It does not contain environment-specific hostnames, credentials, network addresses, or deployment configuration.

## Initial scope

- Versioned `/api/v1` contract.
- Per-server agent authentication.
- Idempotent RDP event ingestion.
- Session state consolidation (`ACTIVE`, `DISCONNECTED`, `CLOSED`).
- Snapshot reconciliation for current session state.
- SQLAlchemy models and Alembic migrations.
- MariaDB production support with SQLite-compatible tests.

The Windows-side collector is maintained separately in the `RDP-Session-Agent` project.
