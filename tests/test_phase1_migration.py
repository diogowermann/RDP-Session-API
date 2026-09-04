from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


MIGRATIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration(name: str, path: Path):
    spec = spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase1_upgrade_and_downgrade_schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase1-migration.db'}")

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))

        initial = _load_migration("phase1_test_0001", MIGRATIONS / "0001_initial_schema.py")
        initial.op = operations
        initial.upgrade()

        phase1 = _load_migration(
            "phase1_test_0002",
            MIGRATIONS / "0002_add_origin_and_correlation_schema.py",
        )
        phase1.op = operations
        phase1.upgrade()

        inspector = inspect(connection)
        assert {"correlation_evidence", "correlation_jobs"}.issubset(inspector.get_table_names())
        assert {"protocol", "source_ip", "source_port", "correlation_status"}.issubset(
            {column["name"] for column in inspector.get_columns("session_events")}
        )
        assert {"protocol", "initial_source_ip", "last_source_ip", "correlation_status"}.issubset(
            {column["name"] for column in inspector.get_columns("sessions")}
        )

        phase1.downgrade()

        inspector = inspect(connection)
        assert "correlation_evidence" not in inspector.get_table_names()
        assert "correlation_jobs" not in inspector.get_table_names()
        assert "protocol" not in {column["name"] for column in inspector.get_columns("session_events")}
        assert "protocol" not in {column["name"] for column in inspector.get_columns("sessions")}
