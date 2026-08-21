# Installation and configuration

This guide describes a generic installation of **RDP Session API** on Linux and the onboarding workflow for additional Windows servers.

The repository is public by design. Replace example values locally, but do **not** commit real credentials, internal DNS names, private addresses, or production reverse-proxy configuration.

## 1. Requirements

- Linux host with Python **3.11+**.
- MariaDB or MySQL reachable by the API process.
- A dedicated database and database user.
- Git for source deployment.
- A reverse proxy with HTTPS for production Agent traffic.
- A DNS name resolvable by monitored Windows servers.
- A TLS certificate trusted by those Windows servers.

## 2. Clone and install the application

Recommended application path:

```text
/opt/rdp-session-api
```

Example:

```bash
sudo mkdir -p /opt/rdp-session-api
sudo chown "$USER":"$USER" /opt/rdp-session-api
git clone https://github.com/diogowermann/RDP-Session-API.git /opt/rdp-session-api
cd /opt/rdp-session-api
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install .
```

For development/test dependencies:

```bash
.venv/bin/pip install '.[dev]'
```

## 3. Create the database

Use a dedicated schema and database user for this service.

Example only:

```sql
CREATE DATABASE rdp_session_service
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE USER 'rdp_session_api'@'localhost'
    IDENTIFIED BY 'replace-with-a-strong-password';

GRANT ALL PRIVILEGES ON rdp_session_service.*
    TO 'rdp_session_api'@'localhost';

FLUSH PRIVILEGES;
```

Adjust host grants according to your database topology.

## 4. Configure runtime settings

For local/manual validation, `.env.example` documents the supported settings.

For production, keep configuration outside the repository checkout. The provided systemd deployment uses:

```text
/etc/rdp-session-api/rdp-session-api.env
```

Required values:

```dotenv
RDP_SESSION_DATABASE_URL=mysql+pymysql://rdp_session_api:replace-with-password@127.0.0.1:3306/rdp_session_service
RDP_SESSION_QUERY_API_KEY=replace-with-a-long-random-query-key
RDP_SESSION_LOG_LEVEL=INFO
```

### `RDP_SESSION_DATABASE_URL`

Connection string for the service database.

### `RDP_SESSION_QUERY_API_KEY`

Protects read/query endpoints such as `/servers` and `/sessions/history`.

This key is **not** used by Windows Agents. Each Agent receives its own credential during server registration.

## 5. Apply database migrations

For manual validation:

```bash
cd /opt/rdp-session-api
.venv/bin/alembic upgrade head
```

The managed systemd unit also runs `alembic upgrade head` before application startup.

## 6. Validate the API manually

Before installing systemd, a manual loopback run can be useful:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8091
```

From another terminal:

```bash
curl -sS http://127.0.0.1:8091/api/v1/health
```

Expected response:

```json
{"status":"ok","contract":"v1"}
```

Stop the manual process before systemd takes ownership of port `8091`.

## 7. Install the managed systemd service

The repository provides:

- `deploy/rdp-session-api.service.in` — hardened unit template;
- `scripts/install_systemd.sh` — service installer;
- `docs/systemd.md` — operations and upgrade runbook.

Prepare a validated environment file, then run:

```bash
cd /opt/rdp-session-api
sudo bash ./scripts/install_systemd.sh \
  --app-dir /opt/rdp-session-api \
  --env-source /path/to/validated.env \
  --start
```

The installer:

- creates the non-login `rdp-session-api` operating-system account;
- installs the protected environment file;
- installs and enables the systemd unit;
- keeps Uvicorn bound to `127.0.0.1:8091`;
- runs pending Alembic migrations before startup;
- enables automatic restart after process failure;
- sends service logs to journald.

Validate:

```bash
sudo systemctl status rdp-session-api --no-pager
curl -sS http://127.0.0.1:8091/api/v1/health
```

## 8. Configure HTTPS reverse proxy

Production Agents should connect through HTTPS. A typical topology is:

```text
Windows Agent -> HTTPS reverse proxy :443 -> 127.0.0.1:8091 -> RDP Session API
```

Recommended requirements:

- dedicated DNS name for the API;
- certificate SAN matching that DNS name;
- certificate chain trusted by monitored Windows servers;
- TLS 1.2 or newer;
- proxy forwarding only to the loopback Uvicorn listener.

Keep private certificate material and environment-specific Nginx configuration outside this public repository.

After reverse-proxy configuration, validate from a monitored Windows server:

```powershell
Invoke-WebRequest `
  -Uri 'https://rdp-api.example.com/api/v1/health' `
  -UseBasicParsing
```

A successful request must not require certificate-validation bypasses.

## 9. Register the first Windows server

Agents do not self-enroll. Register every monitored server separately.

```bash
cd /opt/rdp-session-api
.venv/bin/python scripts/register_server.py --hostname SRV-RDS01
```

The command returns:

- `server_id`;
- a one-time Agent secret.

Record both securely for the Agent installation. The plaintext secret cannot be recovered later because the API stores only its hash.

## 10. Register additional Windows servers

Repeat registration once per server:

```bash
.venv/bin/python scripts/register_server.py --hostname SRV-RDS02
.venv/bin/python scripts/register_server.py --hostname SRV-RDS03
```

Each server must have its **own** `server_id` and Agent secret. Never reuse credentials between servers.

The corresponding Agent installation is documented in the [RDP-Session-Agent repository](https://github.com/diogowermann/RDP-Session-Agent).

## 11. Rotate an Agent credential

If a server secret must be replaced:

```bash
.venv/bin/python scripts/rotate_server_token.py --server-id <server-id>
```

The previous active credential is revoked immediately. Reinstall/update the Windows Agent with the newly returned secret.

## 12. Validate query access

Query endpoints require `X-API-Key`.

Example:

```bash
curl -sS \
  -H 'X-API-Key: replace-with-query-key' \
  'https://rdp-api.example.com/api/v1/servers'
```

For one server:

```bash
curl -sS \
  -H 'X-API-Key: replace-with-query-key' \
  'https://rdp-api.example.com/api/v1/servers/<server-id>/summary'
```

## 13. Grafana integration

A Grafana server can consume the query API over HTTPS using a REST/JSON datasource such as Infinity.

Typical configuration:

```text
Base URL: https://rdp-api.example.com/api/v1
Header:   X-API-Key: <query-api-key>
```

Useful endpoints:

- `/servers`
- `/servers/{server_id}/summary`
- `/servers/{server_id}/sessions/active`
- `/servers/{server_id}/sessions/history`

The Grafana host must trust the certificate authority that issued the API certificate.

## 14. Upgrade procedure

After pulling a new release:

```bash
cd /opt/rdp-session-api
git switch main
git pull --ff-only
.venv/bin/pip install .
sudo systemctl restart rdp-session-api
```

The restart runs pending Alembic migrations through `ExecStartPre` before Uvicorn starts.

Always validate afterward:

```bash
sudo systemctl status rdp-session-api --no-pager
curl -sS http://127.0.0.1:8091/api/v1/health
```

## 15. Logs and troubleshooting

Recent service logs:

```bash
sudo journalctl -u rdp-session-api -n 100 --no-pager
```

Follow logs:

```bash
sudo journalctl -u rdp-session-api -f
```

Common checks:

1. confirm the service is running;
2. confirm migrations completed successfully;
3. confirm the loopback health endpoint responds;
4. confirm the HTTPS reverse proxy responds;
5. confirm Windows servers trust the certificate chain;
6. confirm the server registration and Agent credential match.

For systemd-specific details, see [systemd.md](systemd.md).
