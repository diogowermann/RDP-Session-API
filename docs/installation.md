# Installation

This document describes a generic installation of RDP Session API. Do not commit production credentials, internal hostnames, private addresses, or environment-specific reverse-proxy configuration to this repository.

## Requirements

- Linux host with Python 3.11 or newer.
- MariaDB or MySQL reachable by the API process.
- A dedicated database and database user for this service.
- A reverse proxy with HTTPS for production agent traffic.
- Git for source deployment, or an equivalent release artifact workflow.

## 1. Prepare the application

Clone the repository into an application directory, create a Python virtual environment, and install the package. For development, install the `dev` extra as well.

Example:

```bash
git clone https://github.com/diogowermann/RDP-Session-API.git
cd RDP-Session-API
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install .
```

## 2. Configure the database

Create an empty database and a dedicated SQL user. Grant that user only the permissions required by this database. Do not reuse credentials from unrelated applications.

Copy `.env.example` to `.env` only for a local/manual deployment. In managed production deployments, use `/etc/rdp-session-api/rdp-session-api.env` through the provided systemd workflow.

Required settings:

```text
RDP_SESSION_DATABASE_URL=mysql+pymysql://<user>:<password>@<database-host>:3306/<database-name>
RDP_SESSION_QUERY_API_KEY=<long-random-query-key>
```

`RDP_SESSION_QUERY_API_KEY` protects read/query endpoints. It is separate from per-server Agent credentials.

## 3. Apply migrations for manual validation

For a manual/local run, apply Alembic migrations directly:

```bash
.venv/bin/alembic upgrade head
```

The production systemd unit runs the same migration as `ExecStartPre` using the protected production environment file.

## 4. Register the first Windows server

Agents do not self-enroll. Register each server administratively:

```bash
.venv/bin/python scripts/register_server.py --hostname SRV-RDS01
```

The command returns a `server_id` and a one-time Agent secret. Store the secret securely. The API stores only its SHA-256 hash.

To rotate a server credential:

```bash
.venv/bin/python scripts/rotate_server_token.py --server-id <server-id>
```

Rotation immediately revokes previous active credentials for that server.

## 5. Validate the API manually

For a local validation run:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8091
```

Then verify:

```text
GET /api/v1/health
```

The health endpoint is intentionally simple. Query endpoints require `X-API-Key`; Agent ingestion requires `X-Server-ID` plus a Bearer token.

## 6. Production deployment with systemd

After manual validation, stop the manually launched Uvicorn process before systemd takes ownership of port `8091`.

The repository provides:

- `deploy/rdp-session-api.service.in` - hardened systemd unit template;
- `scripts/install_systemd.sh` - idempotent installer/renderer;
- `docs/systemd.md` - production operation and upgrade runbook.

Example for a prepared checkout:

```bash
sudo bash ./scripts/install_systemd.sh \
  --app-dir /opt/rdp-session-api \
  --env-source /path/to/validated.env \
  --start
```

The resulting service:

- runs as the dedicated `rdp-session-api` system user;
- reads secrets from `/etc/rdp-session-api/rdp-session-api.env`;
- binds Uvicorn only to `127.0.0.1:8091`;
- runs pending Alembic migrations before Uvicorn starts;
- restarts automatically after process failure;
- sends stdout/stderr to journald;
- starts automatically at boot;
- applies systemd hardening without requiring privileged Linux capabilities.

For existing installations in a different checkout directory, pass that current path to `--app-dir`; moving the repository is not required.

See [systemd.md](systemd.md) for status, logs, upgrades and conversion from a manual Uvicorn deployment.

## 7. Reverse proxy

Production Agent traffic should terminate HTTPS at a reverse proxy and forward to the loopback Uvicorn listener. Keep certificates, internal DNS names and environment-specific Nginx configuration outside this public repository.
