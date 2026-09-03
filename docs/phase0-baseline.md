# Phase 0 — baseline capture

This runbook freezes the operational state of RDP Session API before any expansion migration.

## Scope

Capture and archive, as internal evidence:

- repository commit and working-tree state;
- package/runtime version declarations;
- Alembic current revision;
- systemd service state;
- registered servers and Agent versions;
- `last_seen_at`, `last_snapshot_at` and boot metadata;
- event/session counts;
- representative LOGON, LOGOFF, DISCONNECT and RECONNECT events.

The generated JSON contains internal server IDs, hostnames and usernames. **Never commit it to this public repository.** Archive the result in the internal project workspace instead.

## Capture

Run from the deployed API checkout using the production virtual environment:

```bash
sudo ./.venv/bin/python scripts/capture_phase0_baseline.py
```

The default output is written under `/var/tmp/rdp-session-phase0-<timestamp>.json` with best-effort mode `0600`.

To choose an explicit destination outside the repository:

```bash
sudo ./.venv/bin/python scripts/capture_phase0_baseline.py \
  --output /var/tmp/rdp-session-phase0.json
```

The script reads `/etc/rdp-session-api/rdp-session-api.env` by default. Use `--env-file` only when the deployed service uses another environment file.

## Database backup and restore gate

The capture script does **not** create or restore a production database backup. The backup/restore proof remains an explicit operator gate because restoration must occur in an isolated database/environment.

Before Phase 1:

1. create a native MariaDB/MySQL backup using the environment's established backup procedure;
2. restore that backup to an isolated validation database;
3. run `alembic current` against the restored database;
4. verify server, event and session row counts against the captured baseline;
5. archive the commands, timestamps and result in the internal project workspace.

Do not perform a destructive restore over the production database as a validation step.

## Version consistency gate

The baseline reports both:

- the package version declared in `pyproject.toml`;
- the version declared by the FastAPI application.

If these differ, resolve or document the discrepancy before Phase 1 so releases and deployed code can be identified unambiguously.

## Exit criteria

Phase 0 is complete only when all of the following are evidenced internally:

- every expected Windows server is present and enabled;
- expected Agents have recent `last_seen_at` and snapshots;
- no critical local Agent spool backlog is pending;
- current LOGON/LOGOFF/DISCONNECT/RECONNECT behavior is represented;
- Grafana's current queries/alerts are captured as a before-change reference;
- API database backup and isolated restore are proven;
- deployed repository commit, API version and Agent versions are recorded;
- no unresolved production incident is attributed to the current monitor.

Only then should the additive schema migration of Phase 1 be deployed.
