from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
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
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
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
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    server: Mapped[Server] = relationship(back_populates="events")


class RdpSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_server_state", "server_id", "state"),
        Index("ix_sessions_server_logon", "server_id", "logon_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    windows_session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    boot_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    logon_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    logoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    disconnect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now, onupdate=utc_now
    )

    server: Mapped[Server] = relationship(back_populates="sessions")
