from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.timeutils import utc_now


def new_uuid() -> str:
    return str(uuid4())


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fqdn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_boot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now, onupdate=utc_now
    )

    credentials: Mapped[list[ServerCredential]] = relationship(back_populates="server", cascade="all, delete-orphan")
    events: Mapped[list[SessionEvent]] = relationship(back_populates="server", cascade="all, delete-orphan")
    sessions: Mapped[list[RdpSession]] = relationship(back_populates="server", cascade="all, delete-orphan")


class ServerCredential(Base):
    __tablename__ = "server_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=utc_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    server: Mapped[Server] = relationship(back_populates="credentials")


class SessionEvent(Base):
    __tablename__ = "session_events"
    __table_args__ = (
        UniqueConstraint("event_fingerprint", name="uq_session_events_fingerprint"),
        Index("ix_session_events_server_occurred", "server_id", "occurred_at"),
        Index("ix_session_events_occurred_at", "occurred_at"),
        Index("ix_session_events_source_occurred", "source_ip", "occurred_at"),
        Index("ix_session_events_protocol_occurred", "protocol", "occurred_at"),
        Index("ix_session_events_username_occurred", "username", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), nullable=False, default="RDP", server_default="RDP")
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_channel: Mapped[str] = mapped_column(String(255), nullable=False)
    event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    windows_session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    boot_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=utc_now)
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    source_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    server: Mapped[Server] = relationship(back_populates="events")


class RdpSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_server_state", "server_id", "state"),
        Index("ix_sessions_server_logon", "server_id", "logon_at"),
        Index("ix_sessions_logon_at", "logon_at"),
        Index("ix_sessions_protocol_logon", "protocol", "logon_at"),
        Index("ix_sessions_username_logon", "username", "logon_at"),
        Index("ix_sessions_initial_source_logon", "initial_source_ip", "logon_at"),
        Index("ix_sessions_last_source_logon", "last_source_ip", "logon_at"),
        Index("ix_sessions_correlation_status_updated", "correlation_status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), nullable=False, default="RDP", server_default="RDP")
    windows_session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    boot_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    logon_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    logoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    initial_source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    last_source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    correlation_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    disconnect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now, onupdate=utc_now
    )

    server: Mapped[Server] = relationship(back_populates="sessions")


class CorrelationEvidence(Base):
    __tablename__ = "correlation_evidence"
    __table_args__ = (
        Index("ix_correlation_evidence_session_observed", "session_id", "observed_at"),
        Index("ix_correlation_evidence_source_observed", "source_ip", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    session_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("session_events.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    source_device_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    integration_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    asset_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_snapshot: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=utc_now)


class CorrelationJob(Base):
    __tablename__ = "correlation_jobs"
    __table_args__ = (
        Index("ix_correlation_jobs_status_next", "status", "next_attempt_at"),
        Index("ix_correlation_jobs_session", "session_id"),
        Index("ix_correlation_jobs_source_observed", "source_ip", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    session_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("session_events.id", ondelete="SET NULL"), nullable=True
    )
    source_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", server_default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now, onupdate=utc_now
    )
