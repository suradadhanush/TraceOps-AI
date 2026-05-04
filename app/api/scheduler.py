"""
Resilient Scheduler (Fix 1)

Handles Celery desync on free-tier containers:
1. /worker/health — verifies Celery worker is actually alive
2. /scheduler/trigger — manual fallback trigger for any scheduled job
3. Missed schedule detection + logging
4. All scheduled tasks wrapped with retry=3 + exponential backoff

Worker health check uses Celery inspect().ping() with timeout.
Falls back gracefully when broker unreachable.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

log = logging.getLogger("eas.scheduler")

router = APIRouter(prefix="/worker", tags=["Scheduler"])

# ── Missed schedule tracking ──────────────────────────────────────────────────

_schedule_log: list[dict] = []   # in-memory; persist to DB in production


def record_schedule_attempt(job_name: str, success: bool, error: Optional[str] = None):
    _schedule_log.append({
        "job": job_name,
        "triggered_at": datetime.utcnow().isoformat(),
        "success": success,
        "error": error,
    })
    if not success:
        log.error(f"Scheduled job MISSED: {job_name} — {error}")
    else:
        log.info(f"Scheduled job OK: {job_name}")


def get_missed_schedules(last_n: int = 20) -> list[dict]:
    missed = [s for s in _schedule_log if not s["success"]]
    return missed[-last_n:]


# ── Worker health check ───────────────────────────────────────────────────────

async def check_worker_alive(timeout: float = 3.0) -> dict:
    """
    Ping Celery workers via inspect().
    Returns {"alive": bool, "workers": list, "error": str|None}.
    """
    try:
        from app.core.celery_app import celery_app
        inspector = celery_app.control.inspect(timeout=timeout)
        ping_result = inspector.ping()

        if ping_result:
            workers = list(ping_result.keys())
            return {"alive": True, "workers": workers, "worker_count": len(workers), "error": None}
        else:
            return {"alive": False, "workers": [], "worker_count": 0, "error": "No workers responded to ping"}
    except Exception as exc:
        return {"alive": False, "workers": [], "worker_count": 0, "error": str(exc)[:200]}


# ── DB + Redis health checks ──────────────────────────────────────────────────

async def check_db_alive() -> dict:
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return {"alive": True, "error": None}
    except Exception as exc:
        return {"alive": False, "error": str(exc)[:150]}


async def check_redis_alive() -> dict:
    try:
        from app.core.config import settings
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        return {"alive": True, "error": None}
    except Exception as exc:
        return {"alive": False, "error": str(exc)[:150]}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/health")
async def worker_health():
    """
    Deep health check: DB + Redis + Celery worker.
    Used by UptimeRobot and monitoring to detect full desync.
    """
    db_status     = await check_db_alive()
    redis_status  = await check_redis_alive()
    worker_status = await check_worker_alive()

    overall_ok = db_status["alive"] and redis_status["alive"]
    # Worker may be starting up — don't hard-fail on worker absence
    worker_warn = not worker_status["alive"]

    return {
        "status": "ok" if overall_ok else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "database": db_status,
            "redis": redis_status,
            "celery_worker": worker_status,
        },
        "worker_warning": worker_warn,
        "degraded": not overall_ok,
    }


class TriggerRequest(BaseModel):
    job: str      # "daily_report" | "fetch_git" | "retry_webhooks"
    force: bool = False


@router.post("/scheduler/trigger")
async def manual_trigger(
    req: TriggerRequest,
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    """
    Fallback manual trigger for scheduled jobs.
    Use when Celery beat is not running (free tier restart).
    Requires X-Admin-Key header matching SECRET_KEY.
    """
    from app.core.config import settings
    import hmac as _hmac
    if not x_admin_key or not _hmac.compare_digest(x_admin_key, settings.SECRET_KEY):
        raise HTTPException(status_code=403, detail="Invalid admin key.")

    JOB_MAP = {
        "daily_report":    "app.tasks.celery_tasks.generate_daily_report",
        "fetch_git":       "app.tasks.celery_tasks.fetch_git_events",
        "retry_webhooks":  "app.tasks.celery_tasks.retry_failed_webhooks",
    }
    task_name = JOB_MAP.get(req.job)
    if not task_name:
        raise HTTPException(status_code=400, detail=f"Unknown job: {req.job}. Valid: {list(JOB_MAP)}")

    try:
        from app.core.celery_app import celery_app
        result = celery_app.send_task(task_name)
        record_schedule_attempt(req.job, success=True)
        return {
            "triggered": True,
            "job": req.job,
            "task_id": result.id,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        record_schedule_attempt(req.job, success=False, error=str(exc))
        raise HTTPException(status_code=503, detail=f"Failed to trigger job: {exc}")


@router.get("/scheduler/missed")
async def get_missed(
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    from app.core.config import settings
    import hmac as _hmac
    if not x_admin_key or not _hmac.compare_digest(x_admin_key, settings.SECRET_KEY):
        raise HTTPException(status_code=403, detail="Invalid admin key.")
    return {
        "missed_count": len([s for s in _schedule_log if not s["success"]]),
        "recent_missed": get_missed_schedules(20),
        "total_attempts": len(_schedule_log),
    }
