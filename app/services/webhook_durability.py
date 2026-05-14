"""
Webhook Durability Layer (Fix 2)

All incoming webhook payloads stored to DB BEFORE processing.
Failed processing → retry queue (max 3 attempts).
Idempotency via SHA-256 of payload content.
/webhook/replay → reprocess all failed events.

Replaces the naive pass-through in events.py for GitHub + deploy webhooks.
"""
import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base, AsyncSessionLocal

log = logging.getLogger("traceops.webhook")

MAX_RETRIES = 3


# ── ORM model ─────────────────────────────────────────────────────────────────

class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    idempotency_key = Column(String(64), unique=True, nullable=False, index=True)
    source        = Column(String(64), nullable=False)   # github | deploy | manual
    event_type    = Column(String(64), nullable=True)
    raw_payload   = Column(Text, nullable=False)          # JSON blob
    status        = Column(String(32), default="pending") # pending|processed|failed|retry
    attempt_count = Column(Integer, default=0)
    error_log     = Column(Text, nullable=True)
    received_at   = Column(DateTime(timezone=True), default=datetime.utcnow)
    processed_at  = Column(DateTime(timezone=True), nullable=True)


# ── Idempotency key ───────────────────────────────────────────────────────────

def _idempotency_key(source: str, payload: dict) -> str:
    """SHA-256 of source + canonical JSON — same payload never processed twice."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{source}:{canonical}".encode()).hexdigest()[:32]


# ── Store raw webhook ─────────────────────────────────────────────────────────

async def store_webhook(
    db: AsyncSession,
    source: str,
    event_type: Optional[str],
    payload: dict,
) -> tuple[Optional["WebhookEvent"], bool]:
    """
    Persist raw webhook payload to DB before any processing.

    Returns (WebhookEvent, is_duplicate).
    is_duplicate=True means this exact payload was already processed → skip.
    """
    ikey = _idempotency_key(source, payload)

    existing = await db.execute(
        select(WebhookEvent).where(WebhookEvent.idempotency_key == ikey)
    )
    row = existing.scalar_one_or_none()
    if row:
        if row.status == "processed":
            log.info(f"Duplicate webhook skipped: {ikey[:12]} (source={source})")
            return row, True
        # Already stored but not processed yet → return it for retry
        return row, False

    wh = WebhookEvent(
        idempotency_key=ikey,
        source=source,
        event_type=event_type,
        raw_payload=json.dumps(payload, default=str),
        status="pending",
        attempt_count=0,
    )
    db.add(wh)
    await db.flush()
    log.info(f"Webhook stored: id={wh.id} source={source} ikey={ikey[:12]}")
    return wh, False


async def mark_processed(db: AsyncSession, wh_id: int):
    result = await db.execute(select(WebhookEvent).where(WebhookEvent.id == wh_id))
    wh = result.scalar_one_or_none()
    if wh:
        wh.status       = "processed"
        wh.processed_at = datetime.utcnow()
        await db.flush()


async def mark_failed(db: AsyncSession, wh_id: int, error: str):
    result = await db.execute(select(WebhookEvent).where(WebhookEvent.id == wh_id))
    wh = result.scalar_one_or_none()
    if wh:
        wh.attempt_count += 1
        wh.error_log      = (wh.error_log or "") + f"\n[{datetime.utcnow().isoformat()}] {error}"
        if wh.attempt_count >= MAX_RETRIES:
            wh.status = "failed"
            log.error(f"Webhook id={wh_id} permanently failed after {MAX_RETRIES} attempts: {error}")
        else:
            wh.status = "retry"
            log.warning(f"Webhook id={wh_id} attempt {wh.attempt_count} failed, will retry: {error}")
        await db.flush()


# ── Retry queue ───────────────────────────────────────────────────────────────

async def get_retry_queue(limit: int = 50) -> list[dict]:
    """Return all webhook events in 'retry' or 'pending' status for reprocessing."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WebhookEvent)
            .where(WebhookEvent.status.in_(["retry", "pending"]))
            .where(WebhookEvent.attempt_count < MAX_RETRIES)
            .order_by(WebhookEvent.received_at.asc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "source": r.source,
                "event_type": r.event_type,
                "payload": json.loads(r.raw_payload),
                "attempt_count": r.attempt_count,
                "received_at": r.received_at.isoformat(),
            }
            for r in rows
        ]


async def get_failed_events(limit: int = 100) -> list[dict]:
    """Return permanently failed webhook events."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WebhookEvent)
            .where(WebhookEvent.status == "failed")
            .order_by(WebhookEvent.received_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "source": r.source,
                "event_type": r.event_type,
                "attempt_count": r.attempt_count,
                "error_log": r.error_log,
                "received_at": r.received_at.isoformat(),
            }
            for r in rows
        ]


async def webhook_stats() -> dict:
    async with AsyncSessionLocal() as db:
        from sqlalchemy import func
        result = await db.execute(
            select(WebhookEvent.status, func.count(WebhookEvent.id).label("count"))
            .group_by(WebhookEvent.status)
        )
        rows = result.all()
        by_status = {r.status: r.count for r in rows}
        total = sum(by_status.values())
        return {
            "total": total,
            "processed": by_status.get("processed", 0),
            "pending": by_status.get("pending", 0),
            "retry": by_status.get("retry", 0),
            "failed": by_status.get("failed", 0),
            "success_rate": round(by_status.get("processed", 0) / max(1, total) * 100, 1),
        }
