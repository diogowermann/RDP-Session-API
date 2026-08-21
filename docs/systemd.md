# systemd deployment

This runbook describes a generic Linux production deployment for RDP Session API. Keep real credentials, internal DNS names, private addresses and reverse-proxy configuration outside the repository.

## Runtime layout

The provided deployment uses:

- service name: `rdp-session-api`;
- operating-system user: `rdp-session-api`;
- default application directory: `/opt/rdp-session-api`;
- protected environment file: `/etc/rdp-session-api/rdp-session-api.env`;
- Uvicorn bind: `127.0.0.1:8091`;
- logs: systemd journal under identifier `rdp-session-api`.

The installer accepts a different existing application directory with `--app-dir`; the repository does not need to be moved just to adopt systemd.

## First installation

Prepare the checkout and virtual environment first. Confirm that `.venv/bin/uvicorn` and `.venv/bin/alembic` exist.

Create a production environment file containing at least:

```text
RDP_SESSION_DATABASE_URL=mysql+pymysql://<user>:<password>@<database-host>:3306/<database-name>
RDP_SESSION_LOG_LEVEL=INFO
RDP_SESSION_QUERY_API_KEY=<long-random-query-key>
```

Then install the unit. If an existing validated `.env` is being migrated, pass it explicitly as the source:

```bash
sudo ./scripts/install_systemd.sh \
  --app-dir /opt/rdp-session-api \
  --env-source /path/to/existing.env \
  --start
```

The installer:

1. creates the non-login `rdp-session-api` system user if necessary;
2. installs the environment file as `/etc/rdp-session-api/rdp-session-api.env` with mode `0600`;
3. renders `/etc/systemd/system/rdp-session-api.service` for the selected application directory;
4. reloads systemd and enables the service at boot;
5. optionally starts/restarts the service with `--start`.

If the protected environment file already exists and `--env-source` is omitted, the installer preserves it.

## Migrations

The unit runs:

```text
alembic upgrade head
```

as `ExecStartPre`, using the same protected environment as the API. A migration failure prevents Uvicorn from starting instead of launching the application against an incompatible schema.

## Service operation

Status:

```bash
sudo systemctl status rdp-session-api --no-pager
```

Restart:

```bash
sudo systemctl restart rdp-session-api
```

Stop/start:

```bash
sudo systemctl stop rdp-session-api
sudo systemctl start rdp-session-api
```

Enablement:

```bash
sudo systemctl is-enabled rdp-session-api
```

## Logs

Recent logs:

```bash
sudo journalctl -u rdp-session-api -n 100 --no-pager
```

Follow logs:

```bash
sudo journalctl -u rdp-session-api -f
```

Logs are intentionally sent to journald rather than unmanaged application log files. Retention and disk limits remain under the host's central journald policy.

## Health validation

The service binds only to loopback by default:

```bash
curl -sS http://127.0.0.1:8091/api/v1/health
```

Expected response:

```json
{"status":"ok","contract":"v1"}
```

Production Agent traffic should reach the API through an HTTPS reverse proxy. The bundled unit accepts forwarded proxy headers only from `127.0.0.1`.

## Upgrade workflow

After a repository update:

```bash
cd /opt/rdp-session-api
git pull
.venv/bin/pip install .
sudo systemctl restart rdp-session-api
```

The restart loads the new Python code and runs pending Alembic migrations before Uvicorn starts. Always verify both service status and the health endpoint after an upgrade.

## Existing manual deployments

A deployment currently started with a manual Uvicorn command can be converted without changing its database or Agent credentials:

1. stop the manual Uvicorn process so port `8091` is free;
2. run `install_systemd.sh` with the current checkout as `--app-dir`;
3. copy the current validated environment with `--env-source`;
4. start the service;
5. verify `systemctl status`, journald and `/api/v1/health`;
6. only after successful cutover, remove any obsolete plaintext environment copy from the repository checkout if one was previously used.

## Hardening

The unit runs without privileged Linux capabilities and enables systemd protections including `NoNewPrivileges`, private temporary storage, protected system/home paths, kernel/control-group protections and a restrictive umask. It does not open an inbound public socket; Uvicorn remains bound to loopback.
