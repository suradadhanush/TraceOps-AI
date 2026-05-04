import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    project_id: Mapped[str] = mapped_column(String, nullable=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    target_level: Mapped[int] = mapped_column(Integer, nullable=False)
    final_level: Mapped[int] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active | completed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    date: Mapped[date] = mapped_column(Date, default=date.today)

    events: Mapped[list["Event"]] = relationship("Event", back_populates="task")
    score: Mapped["Score"] = relationship("Score", back_populates="task", uselist=False)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)  # commit|deploy|ai|error
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String, nullable=True)  # github|proxy|deploy
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="events")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.id"), unique=True)
    date: Mapped[date] = mapped_column(Date, default=date.today)
    level: Mapped[int] = mapped_column(Integer)
    velocity: Mapped[int] = mapped_column(Integer)
    stability_penalty: Mapped[int] = mapped_column(Integer)
    ai_penalty: Mapped[int] = mapped_column(Integer)
    final_score: Mapped[int] = mapped_column(Integer)

    task: Mapped["Task"] = relationship("Task", back_populates="score")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, default=date.today)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIProxyLog(Base):
    __tablename__ = "ai_proxy_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String)  # openai | anthropic
    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    error: Mapped[str] = mapped_column(Text, nullable=True)
