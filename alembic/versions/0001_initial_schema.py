"""Initial RDP session schema.

Revision ID: 0001
Revises:
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "servers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column("fqdn", sa.String(255), nullable=True),
        sa.Column("os_version", sa.String(128), nullable=True),
        sa.Column("agent_version", sa.String(32), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_snapshot_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_boot_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
    )
    op.create_table(
        "server_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("server_id", sa.String(36), sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=False), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_server_credentials_token_hash"),
    )
    op.create_index("ix_server_credentials_server_id", "server_credentials", ["server_id"])

    op.create_table(
        "session_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("server_id", sa.String(36), sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("event_channel", sa.String(255), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("event_record_id", sa.Integer(), nullable=False),
        sa.Column("windows_session_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("boot_time", sa.DateTime(timezone=False), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("event_fingerprint", sa.String(64), nullable=False),
        sa.Column("payload_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("event_fingerprint", name="uq_session_events_fingerprint"),
    )
    op.create_index("ix_session_events_server_occurred", "session_events", ["server_id", "occurred_at"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("server_id", sa.String(36), sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("windows_session_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("boot_time", sa.DateTime(timezone=False), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("logon_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("logoff_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_connected_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_disconnected_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("disconnect_count", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("end_reason", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
    )
    op.create_index("ix_sessions_server_state", "sessions", ["server_id", "state"])
    op.create_index("ix_sessions_server_logon", "sessions", ["server_id", "logon_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_server_logon", table_name="sessions")
    op.drop_index("ix_sessions_server_state", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_session_events_server_occurred", table_name="session_events")
    op.drop_table("session_events")
    op.drop_index("ix_server_credentials_server_id", table_name="server_credentials")
    op.drop_table("server_credentials")
    op.drop_table("servers")
