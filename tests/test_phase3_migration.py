from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


MIGRATIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration(name: str, path: Path):
    spec = spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase3_upgrade_backfill_and_downgrade(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase3-migration.db'}")

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))

        initial = _load_migration("phase3_test_0001", MIGRATIONS / "0001_initial_schema.py")
        initial.op = operations
        initial.upgrade()

        phase1 = _load_migration("phase3_test_0002", MIGRATIONS / "0002_add_origin_and_correlation_schema.py")
        phase1.op = operations
        phase1.upgrade()

        connection.execute(
            text(
                """
                INSERT INTO servers
                    (id, hostname, enabled, created_at, updated_at, last_boot_at)
                VALUES
                    ('srv-1', 'legacy-rdp', 1, :now, :now, :boot)
                """
            ),
            {"now": "2026-09-04 13:00:00", "boot": "2026-09-04 09:00:00"},
        )
        connection.execute(
            text(
                """
                INSERT INTO session_events
                    (id, server_id, event_type, event_channel, event_id, event_record_id,
                     windows_session_id, username, boot_time, occurred_at, received_at,
                     event_fingerprint, payload_version, protocol)
                VALUES
                    ('event-1', 'srv-1', 'LOGON', 'legacy', 21, 123, 4, 'alice',
                     :boot, :occurred, :received, 'fingerprint-1', 1, 'RDP')
                """
            ),
            {
                "boot": "2026-09-04 09:00:00",
                "occurred": "2026-09-04 12:00:00",
                "received": "2026-09-04 12:00:01",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO sessions
                    (id, server_id, windows_session_id, username, boot_time, state,
                     disconnect_count, created_at, updated_at, protocol)
                VALUES
                    ('session-1', 'srv-1', 4, 'alice', :boot, 'ACTIVE', 0, :now, :now, 'RDP')
                """
            ),
            {"boot": "2026-09-04 09:00:00", "now": "2026-09-04 12:00:00"},
        )

        phase3 = _load_migration(
            "phase3_test_0003",
            MIGRATIONS / "0003_add_generic_v2_contract_fields.py",
        )
        phase3.op = operations
        phase3.upgrade()

        event = connection.execute(
            text(
                "SELECT platform, provider_session_id, provider_event_id, boot_id "
                "FROM session_events WHERE id='event-1'"
            )
        ).mappings().one()
        assert event["platform"] == "windows"
        assert event["provider_session_id"] == "4"
        assert event["provider_event_id"] == "123"
        assert event["boot_id"] is not None

        session = connection.execute(
            text(
                "SELECT platform, provider_session_id, boot_id "
                "FROM sessions WHERE id='session-1'"
            )
        ).mappings().one()
        assert session["platform"] == "windows"
        assert session["provider_session_id"] == "4"
        assert session["boot_id"] is not None

        server = connection.execute(
            text("SELECT platform, last_boot_id FROM servers WHERE id='srv-1'")
        ).mappings().one()
        assert server["platform"] == "windows"
        assert server["last_boot_id"] is not None

        inspector = inspect(connection)
        assert {"platform", "provider_session_id", "provider_event_id", "boot_id"}.issubset(
            {column["name"] for column in inspector.get_columns("session_events")}
        )
        assert {"platform", "provider_session_id", "boot_id"}.issubset(
            {column["name"] for column in inspector.get_columns("sessions")}
        )

        phase3.downgrade()

        inspector = inspect(connection)
        assert "provider_event_id" not in {column["name"] for column in inspector.get_columns("session_events")}
        assert "provider_session_id" not in {column["name"] for column in inspector.get_columns("sessions")}
        assert "last_boot_id" not in {column["name"] for column in inspector.get_columns("servers")}
        assert "protocol" in {column["name"] for column in inspector.get_columns("session_events")}
        assert "source_ip" in {column["name"] for column in inspector.get_columns("session_events")}
