"""Add origin and correlation-ready schema.

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "session_events",
        sa.Column("protocol", sa.String(16), nullable=False, server_default="RDP"),
    )
    op.add_column("session_events", sa.Column("source_ip", sa.String(45), nullable=True))
    op.add_column("session_events", sa.Column("source_port", sa.Integer(), nullable=True))
    op.add_column("session_events", sa.Column("correlation_status", sa.String(16), nullable=True))
    op.create_index("ix_session_events_occurred_at", "session_events", ["occurred_at"])
    op.create_index("ix_session_events_source_occurred", "session_events", ["source_ip", "occurred_at"])
    op.create_index("ix_session_events_protocol_occurred", "session_events", ["protocol", "occurred_at"])
    op.create_index("ix_session_events_username_occurred", "session_events", ["username", "occurred_at"])

    op.add_column(
        "sessions",
        sa.Column("protocol", sa.String(16), nullable=False, server_default="RDP"),
    )
    op.add_column("sessions", sa.Column("initial_source_ip", sa.String(45), nullable=True))
    op.add_column("sessions", sa.Column("last_source_ip", sa.String(45), nullable=True))
    op.add_column("sessions", sa.Column("correlation_status", sa.String(16), nullable=True))
    op.create_index("ix_sessions_logon_at", "sessions", ["logon_at"])
    op.create_index("ix_sessions_protocol_logon", "sessions", ["protocol", "logon_at"])
    op.create_index("ix_sessions_username_logon", "sessions", ["username", "logon_at"])
    op.create_index("ix_sessions_initial_source_logon", "sessions", ["initial_source_ip", "logon_at"])
    op.create_index("ix_sessions_last_source_logon", "sessions", ["last_source_ip", "logon_at"])
    op.create_index(
        "ix_sessions_correlation_status_updated",
        "sessions",
        ["correlation_status", "updated_at"],
    )

    op.create_table(
        "correlation_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "session_event_id",
            sa.String(36),
            sa.ForeignKey("session_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_ip", sa.String(45), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("source_device_id", sa.String(36), nullable=True),
        sa.Column("integration_record_id", sa.String(36), nullable=True),
        sa.Column("asset_tag", sa.String(64), nullable=True),
        sa.Column("method", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
    )
    op.create_index(
        "ix_correlation_evidence_session_observed",
        "correlation_evidence",
        ["session_id", "observed_at"],
    )
    op.create_index(
        "ix_correlation_evidence_source_observed",
        "correlation_evidence",
        ["source_ip", "observed_at"],
    )

    op.create_table(
        "correlation_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "session_event_id",
            sa.String(36),
            sa.ForeignKey("session_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_ip", sa.String(45), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
    )
    op.create_index("ix_correlation_jobs_status_next", "correlation_jobs", ["status", "next_attempt_at"])
    op.create_index("ix_correlation_jobs_session", "correlation_jobs", ["session_id"])
    op.create_index(
        "ix_correlation_jobs_source_observed",
        "correlation_jobs",
        ["source_ip", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_correlation_jobs_source_observed", table_name="correlation_jobs")
    op.drop_index("ix_correlation_jobs_session", table_name="correlation_jobs")
    op.drop_index("ix_correlation_jobs_status_next", table_name="correlation_jobs")
    op.drop_table("correlation_jobs")

    op.drop_index("ix_correlation_evidence_source_observed", table_name="correlation_evidence")
    op.drop_index("ix_correlation_evidence_session_observed", table_name="correlation_evidence")
    op.drop_table("correlation_evidence")

    op.drop_index("ix_sessions_correlation_status_updated", table_name="sessions")
    op.drop_index("ix_sessions_last_source_logon", table_name="sessions")
    op.drop_index("ix_sessions_initial_source_logon", table_name="sessions")
    op.drop_index("ix_sessions_username_logon", table_name="sessions")
    op.drop_index("ix_sessions_protocol_logon", table_name="sessions")
    op.drop_index("ix_sessions_logon_at", table_name="sessions")
    op.drop_column("sessions", "correlation_status")
    op.drop_column("sessions", "last_source_ip")
    op.drop_column("sessions", "initial_source_ip")
    op.drop_column("sessions", "protocol")

    op.drop_index("ix_session_events_username_occurred", table_name="session_events")
    op.drop_index("ix_session_events_protocol_occurred", table_name="session_events")
    op.drop_index("ix_session_events_source_occurred", table_name="session_events")
    op.drop_index("ix_session_events_occurred_at", table_name="session_events")
    op.drop_column("session_events", "correlation_status")
    op.drop_column("session_events", "source_port")
    op.drop_column("session_events", "source_ip")
    op.drop_column("session_events", "protocol")
