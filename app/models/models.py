"""
TraceOps AI — Database Models
Includes: User, Integration, OAuthToken + existing Task/Event/Score/Report/AIProxyLog
"""
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ── User ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str]           = mapped_column(String, primary_key=True, default=gen_uuid)
    email: Mapped[str]        = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str]         = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str]   = mapped_column(Text, nullable=True)
    github_id: Mapped[str]    = mapped_column(String(64), unique=True, nullable=True, index=True)
    google_id: Mapped[str]    = mapped_column(String(64), unique=True, nullable=True, index=True)
    github_username: Mapped[str] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool]   = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    integrations: Mapped[list["Integration"]] = relationship("Integration", back_populates="user", cascade="all, delete-orphan")
    sessions:     Mapped[list["UserSession"]] = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    tasks:        Mapped[list["Task"]]        = relationship("Task", back_populates="user")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str]           = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str]      = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    session_token: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ip_address: Mapped[str]   = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str]   = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="sessions")


# ── Integrations ──────────────────────────────────────────────────────────────

class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)

    id: Mapped[str]            = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str]       = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str]      = mapped_column(String(64), nullable=False)   # github|vercel|gitlab|etc
    status: Mapped[str]        = mapped_column(String(32), default="connected") # connected|disconnected|error
    access_token: Mapped[str]  = mapped_column(Text, nullable=True)           # encrypted
    refresh_token: Mapped[str] = mapped_column(Text, nullable=True)           # encrypted
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str]        = mapped_column(Text, nullable=True)           # space-separated scopes
    provider_user_id: Mapped[str]  = mapped_column(String(128), nullable=True)
    provider_username: Mapped[str] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict]    = mapped_column("metadata", JSON, nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="integrations")


class OAuthState(Base):
    """Temporary state for OAuth CSRF protection."""
    __tablename__ = "oauth_states"

    id: Mapped[str]         = mapped_column(String, primary_key=True, default=gen_uuid)
    state: Mapped[str]      = mapped_column(String(256), unique=True, nullable=False, index=True)
    provider: Mapped[str]   = mapped_column(String(64), nullable=False)
    user_id: Mapped[str]    = mapped_column(String, nullable=True)  # None for new user flow
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Existing models (now user-scoped) ─────────────────────────────────────────

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str]           = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str]      = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    project_id: Mapped[str]   = mapped_column(String, nullable=True)
    goal: Mapped[str]         = mapped_column(Text, nullable=False)
    target_level: Mapped[int] = mapped_column(Integer, nullable=False)
    final_level: Mapped[int]  = mapped_column(Integer, nullable=True)
    status: Mapped[str]       = mapped_column(String, default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime]   = mapped_column(DateTime(timezone=True), nullable=True)
    date: Mapped[date]           = mapped_column(Date, default=date.today)

    user:   Mapped["User"]    = relationship("User", back_populates="tasks")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="task")
    score:  Mapped["Score"]   = relationship("Score", back_populates="task", uselist=False)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str]     = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    task_id: Mapped[str]     = mapped_column(String, ForeignKey("tasks.id"), nullable=True)
    event_type: Mapped[str]  = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str]      = mapped_column(String, nullable=True)
    raw_data: Mapped[dict]   = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict]  = mapped_column("metadata", JSON, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="events")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int]              = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str]         = mapped_column(String, ForeignKey("tasks.id"), unique=True)
    date: Mapped[date]           = mapped_column(Date, default=date.today)
    level: Mapped[int]           = mapped_column(Integer)
    velocity: Mapped[int]        = mapped_column(Integer)
    stability_penalty: Mapped[int] = mapped_column(Integer)
    ai_penalty: Mapped[int]      = mapped_column(Integer)
    final_score: Mapped[int]     = mapped_column(Integer)

    task: Mapped["Task"] = relationship("Task", back_populates="score")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str]     = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    date: Mapped[date]       = mapped_column(Date, default=date.today)
    content: Mapped[dict]    = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIProxyLog(Base):
    __tablename__ = "ai_proxy_logs"

    id: Mapped[int]              = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str]         = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    task_id: Mapped[str]         = mapped_column(String, nullable=True)
    provider: Mapped[str]        = mapped_column(String)
    prompt: Mapped[str]          = mapped_column(Text)
    response: Mapped[str]        = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int]   = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int]      = mapped_column(Integer, nullable=True)
    timestamp: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())
    error: Mapped[str]           = mapped_column(Text, nullable=True)
