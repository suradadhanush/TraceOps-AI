"""
Event Ingestion API

POST /event          — ingest a single normalized event
POST /event/github   — receive GitHub webhook
POST /event/deploy   — ingest deploy log
POST /event/error    — ingest error log
GET  /event/         — list recent events
"""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Event
from app.services.normalizer import (
    normalize_deploy_event,
    normalize_error_event,
    normalize_event,
    normalize_github_commit,
)
from app.services.task_enforcement import enforce_task_id

router = APIRouter(prefix="/event", tags=["Events"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class EventRequest(BaseModel):
    task_id: Optional[str] = None
    event_type: str
    metadata: dict = {}
    source: Optional[str] = None
    timestamp: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _persist_event(db: AsyncSession, normalized: dict) -> Event:
    event = Event(
        task_id=normalized.get("task_id"),
        event_type=normalized["event_type"],
        source=normalized.get("source"),
        raw_data=normalized,
        metadata_=normalized.get("metadata"),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/", status_code=201)
async def ingest_event(req: EventRequest, db: AsyncSession = Depends(get_db)):
    """Generic event ingestion. Normalizes, enforces TASK_ID, and stores."""
    raw = {
        "task_id": req.task_id,
        "event_type": req.event_type,
        "source": req.source or "api",
        "timestamp": req.timestamp,
        "metadata": req.metadata,
    }
    normalized = normalize_event(raw)
    normalized = await enforce_task_id(normalized, db)
    event = await _persist_event(db, normalized)
    return {"event_id": event.id, "task_id": event.task_id, "event_type": event.event_type}


@router.post("/github", status_code=201)
async def ingest_github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
):
    """
    Receive GitHub push webhook.
    Configure your repo webhook to POST to this endpoint.
    """
    payload = await request.json()
    event_type = x_github_event or "push"

    if event_type not in ("push", "pull_request"):
        return {"skipped": True, "reason": f"Unhandled event type: {event_type}"}

    normalized_list = normalize_github_commit(payload)
    if isinstance(normalized_list, dict):
        normalized_list = [normalized_list]

    created_ids = []
    for normalized in normalized_list:
        event = await _persist_event(db, normalized)
        created_ids.append(event.id)

    return {"created": len(created_ids), "event_ids": created_ids}


@router.post("/deploy", status_code=201)
async def ingest_deploy_event(
    request: Request,
    task_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest a deploy log entry.
    Compatible with Render, Vercel, or custom CI/CD webhooks.
    """
    payload = await request.json()
    normalized = normalize_deploy_event(payload, task_id=task_id)
    event = await _persist_event(db, normalized)
    return {"event_id": event.id, "status": normalized.get("metadata", {}).get("status")}


@router.post("/error", status_code=201)
async def ingest_error_event(
    request: Request,
    task_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Ingest an error log with automatic normalization and hashing."""
    payload = await request.json()
    normalized = normalize_error_event(payload, task_id=task_id)
    event = await _persist_event(db, normalized)
    return {
        "event_id": event.id,
        "error_hash": normalized.get("metadata", {}).get("error_hash"),
        "normalized": normalized.get("metadata", {}).get("message", "")[:100],
    }


@router.get("/")
async def list_events(
    task_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(Event).order_by(Event.timestamp.desc()).limit(min(limit, 200))
    if task_id:
        q = q.where(Event.task_id == task_id)
    if event_type:
        q = q.where(Event.event_type == event_type)
    result = await db.execute(q)
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "task_id": e.task_id,
            "event_type": e.event_type,
            "source": e.source,
            "timestamp": e.timestamp,
            "metadata": e.metadata_,
        }
        for e in events
    ]
