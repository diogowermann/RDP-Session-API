"""Add generic provider identity for API v2.

Revision ID: 0003
Revises: 0002
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("platform", sa.String(16), nullable=True))
    op.add_column("servers", sa.Column("last_boot_id", sa.String(255), nullable=True))

    op.add_column(
        "session_events",
        sa.Column("platform", sa.String(16), nullable=False, server_default="windows"),
    )
    op.add_column("session_events", sa.Column("provider_session_id", sa.String(255), nullable=True))
    op.add_column("session_events", sa.Column("provider_event_id", sa.String(512), nullable=True))
    op.add_column("session_events", sa.Column("boot_id", sa.String(255), nullable=True))
    op.create_index(
        "ix_session_events_protocol_platform_occurred",
        "session_events",
        ["protocol", "platform", "occurred_at"],
    )

    op.add_column(
        "sessions",
        sa.Column("platform", sa.String(16), nullable=False, server_default="windows"),
    )
    op.add_column("sessions", sa.Column("provider_session_id", sa.String(255), nullable=True))
    op.add_column("sessions", sa.Column("boot_id", sa.String(255), nullable=True))
    op.create_index(
        "ix_sessions_protocol_platform_state",
        "sessions",
        ["protocol", "platform", "state"],
    )
    op.create_index(
        "ix_sessions_server_provider",
        "sessions",
        ["server_id", "protocol", "provider_session_id", "boot_id"],
    )

    servers = sa.table(
        "servers",
        sa.column("platform", sa.String(16)),
        sa.column("last_boot_at", sa.DateTime()),
        sa.column("last_boot_id", sa.String(255)),
    )
    events = sa.table(
        "session_events",
        sa.column("platform", sa.String(16)),
        sa.column("provider_session_id", sa.String(255)),
        sa.column("provider_event_id", sa.String(512)),
        sa.column("boot_id", sa.String(255)),
        sa.column("windows_session_id", sa.Integer()),
        sa.column("event_record_id", sa.Integer()),
        sa.column("boot_time", sa.DateTime()),
    )
    sessions = sa.table(
        "sessions",
        sa.column("platform", sa.String(16)),
        sa.column("provider_session_id", sa.String(255)),
        sa.column("boot_id", sa.String(255)),
        sa.column("windows_session_id", sa.Integer()),
        sa.column("boot_time", sa.DateTime()),
    )

    op.execute(servers.update().where(servers.c.platform.is_(None)).values(platform="windows"))
    op.execute(
        servers.update()
        .where(servers.c.last_boot_at.is_not(None), servers.c.last_boot_id.is_(None))
        .values(last_boot_id=sa.cast(servers.c.last_boot_at, sa.String(255)))
    )
    op.execute(
        events.update()
        .where(events.c.provider_session_id.is_(None))
        .values(provider_session_id=sa.cast(events.c.windows_session_id, sa.String(255)))
    )
    op.execute(
        events.update()
        .where(events.c.provider_event_id.is_(None))
        .values(provider_event_id=sa.cast(events.c.event_record_id, sa.String(512)))
    )
    op.execute(
        events.update()
        .where(events.c.boot_id.is_(None))
        .values(boot_id=sa.cast(events.c.boot_time, sa.String(255)))
    )
    op.execute(
        sessions.update()
        .where(sessions.c.provider_session_id.is_(None))
        .values(provider_session_id=sa.cast(sessions.c.windows_session_id, sa.String(255)))
    )
    op.execute(
        sessions.update()
        .where(sessions.c.boot_id.is_(None))
        .values(boot_id=sa.cast(sessions.c.boot_time, sa.String(255)))
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_server_provider", table_name="sessions")
    op.drop_index("ix_sessions_protocol_platform_state", table_name="sessions")
    op.drop_column("sessions", "boot_id")
    op.drop_column("sessions", "provider_session_id")
    op.drop_column("sessions", "platform")

    op.drop_index("ix_session_events_protocol_platform_occurred", table_name="session_events")
    op.drop_column("session_events", "boot_id")
    op.drop_column("session_events", "provider_event_id")
    op.drop_column("session_events", "provider_session_id")
    op.drop_column("session_events", "platform")

    op.drop_column("servers", "last_boot_id")
    op.drop_column("servers", "platform")
