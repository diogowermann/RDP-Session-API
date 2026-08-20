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

Copy `.env.example` to `.env` only for a local/manual deployment. In managed production deployments, prefer a protected environment file outside the repository checkout.

Required settings:

```text
RDP_SESSION_DATABASE_URL=mysql+pymysql://<user>:<password>@<database-host>:3306/<database-name>
RDP_SESSION_QUERY_API_KEY=<long-random-query-key>
```

`RDP_SESSION_QUERY_API_KEY` protects read/query endpoints. It is separate from per-server Agent credentials.

## 3. Apply migrations

Run all Alembic migrations before starting a new application version:

```bash
.venv/bin/alembic upgrade head
```

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

## 5. Validate the API

For a local validation run:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8091
```

Then verify:

```text
GET /api/v1/health
```

The health endpoint is intentionally simple. Query endpoints require `X-API-Key`; Agent ingestion requires `X-Server-ID` plus a Bearer token.

## 6. Production deployment

Run the application behind HTTPS and bind the application process to loopback or another private application interface. Do not expose the Uvicorn development command directly to untrusted networks.

A production deployment should also provide:

- a dedicated operating-system user;
- a protected environment file;
- a process supervisor such as systemd;
- database backups;
- log retention;
- TLS termination at the reverse proxy;
- controlled upgrade and rollback procedures.

Project-provided systemd/install automation is intentionally deferred until the runtime contract is stable. Until then, treat the commands above as a manual validation workflow rather than a complete production runbook.
