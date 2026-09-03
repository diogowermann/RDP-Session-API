#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = Path("/etc/rdp-session-api/rdp-session-api.env")
EVENT_TYPES = ("LOGON", "LOGOFF", "DISCONNECT", "RECONNECT")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def load_environment_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def run_command(args: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {
            "ok": result.returncode == 0,
            "return_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}


def read_versions() -> dict[str, Any]:
    package_version = None
    pyproject_path = REPO_ROOT / "pyproject.toml"
    try:
        import tomllib

        with pyproject_path.open("rb") as handle:
            package_version = tomllib.load(handle).get("project", {}).get("version")
    except (OSError, ValueError):
        pass

    runtime_declared_version = None
    try:
        main_text = (REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8")
        match = re.search(r'\bversion\s*=\s*["\']([^"\']+)["\']', main_text)
        if match:
            runtime_declared_version = match.group(1)
    except OSError:
        pass

    return {
        "package_version": package_version,
        "fastapi_declared_version": runtime_declared_version,
    }


def ensure_output_outside_repo(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError(
        "refusing to write baseline evidence inside the public Git repository; "
        "choose a path such as /var/tmp/rdp-session-phase0.json"
    )


def collect_database(sample_events_per_type: int) -> dict[str, Any]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from sqlalchemy import func, select

    from app.database import get_session_factory
    from app.models import RdpSession, Server, ServerCredential, SessionEvent

    session_factory = get_session_factory()
    with session_factory() as db:
        servers = db.scalars(select(Server).order_by(Server.hostname, Server.id)).all()

        server_rows = []
        for server in servers:
            event_count = db.scalar(
                select(func.count()).select_from(SessionEvent).where(SessionEvent.server_id == server.id)
            )
            session_count = db.scalar(
                select(func.count()).select_from(RdpSession).where(RdpSession.server_id == server.id)
            )
            active_count = db.scalar(
                select(func.count())
                .select_from(RdpSession)
                .where(RdpSession.server_id == server.id, RdpSession.state == "ACTIVE")
            )
            disconnected_count = db.scalar(
                select(func.count())
                .select_from(RdpSession)
                .where(RdpSession.server_id == server.id, RdpSession.state == "DISCONNECTED")
            )
            active_credentials = db.scalar(
                select(func.count())
                .select_from(ServerCredential)
                .where(
                    ServerCredential.server_id == server.id,
                    ServerCredential.revoked_at.is_(None),
                )
            )

            server_rows.append(
                {
                    "server_id": server.id,
                    "hostname": server.hostname,
                    "fqdn": server.fqdn,
                    "os_version": server.os_version,
                    "agent_version": server.agent_version,
                    "enabled": server.enabled,
                    "last_seen_at": as_iso(server.last_seen_at),
                    "last_snapshot_at": as_iso(server.last_snapshot_at),
                    "last_boot_at": as_iso(server.last_boot_at),
                    "event_count": int(event_count or 0),
                    "session_count": int(session_count or 0),
                    "active_sessions": int(active_count or 0),
                    "disconnected_sessions": int(disconnected_count or 0),
                    "active_credentials": int(active_credentials or 0),
                }
            )

        event_samples: dict[str, list[dict[str, Any]]] = {}
        for event_type in EVENT_TYPES:
            rows = db.scalars(
                select(SessionEvent)
                .where(SessionEvent.event_type == event_type)
                .order_by(SessionEvent.occurred_at.desc(), SessionEvent.id)
                .limit(sample_events_per_type)
            ).all()
            event_samples[event_type] = [
                {
                    "id": event.id,
                    "server_id": event.server_id,
                    "event_type": event.event_type,
                    "event_channel": event.event_channel,
                    "event_id": event.event_id,
                    "event_record_id": event.event_record_id,
                    "windows_session_id": event.windows_session_id,
                    "username": event.username,
                    "domain": event.domain,
                    "boot_time": as_iso(event.boot_time),
                    "occurred_at": as_iso(event.occurred_at),
                    "received_at": as_iso(event.received_at),
                    "payload_version": event.payload_version,
                }
                for event in rows
            ]

        return {
            "counts": {
                "servers": int(db.scalar(select(func.count()).select_from(Server)) or 0),
                "server_credentials": int(
                    db.scalar(select(func.count()).select_from(ServerCredential)) or 0
                ),
                "session_events": int(
                    db.scalar(select(func.count()).select_from(SessionEvent)) or 0
                ),
                "sessions": int(db.scalar(select(func.count()).select_from(RdpSession)) or 0),
            },
            "servers": server_rows,
            "event_samples": event_samples,
        }


def collect_systemd() -> dict[str, Any]:
    return run_command(
        [
            "systemctl",
            "show",
            "rdp-session-api",
            "--property=ActiveState,SubState,UnitFileState,MainPID,ExecMainStartTimestamp,FragmentPath",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture Phase 0 baseline evidence for RDP Session API."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="systemd-style environment file used by the API",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            f"/var/tmp/rdp-session-phase0-{utc_now().strftime('%Y%m%dT%H%M%SZ')}.json"
        ),
        help="output JSON path; must be outside the public repository",
    )
    parser.add_argument(
        "--sample-events-per-type",
        type=int,
        default=3,
        help="number of latest raw events to capture for each lifecycle type",
    )
    args = parser.parse_args()

    if args.sample_events_per_type < 1 or args.sample_events_per_type > 20:
        parser.error("--sample-events-per-type must be between 1 and 20")

    try:
        output_path = ensure_output_outside_repo(args.output)
    except ValueError as exc:
        parser.error(str(exc))

    load_environment_file(args.env_file)

    if not os.environ.get("RDP_SESSION_DATABASE_URL"):
        parser.error(
            "RDP_SESSION_DATABASE_URL is not available; provide --env-file or export the variable"
        )

    alembic_binary = Path(sys.executable).with_name("alembic")
    alembic_command = str(alembic_binary) if alembic_binary.exists() else "alembic"

    evidence = {
        "schema_version": 1,
        "captured_at": as_iso(utc_now()),
        "warning": (
            "Internal operational evidence. Do not commit this JSON to the public repository."
        ),
        "repository": {
            "root": str(REPO_ROOT),
            "git_commit": run_command(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT),
            "git_status": run_command(["git", "status", "--porcelain"], cwd=REPO_ROOT),
            **read_versions(),
        },
        "alembic": run_command([alembic_command, "-c", "alembic.ini", "current"], cwd=REPO_ROOT),
        "systemd": collect_systemd(),
        "database": collect_database(args.sample_events_per_type),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        output_path.chmod(0o600)
    except OSError:
        pass

    print(f"Phase 0 baseline written to: {output_path}")
    print("This file contains internal identifiers and usernames. Do not commit it to Git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
