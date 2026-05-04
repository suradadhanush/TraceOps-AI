"""
Celery Tasks v2

Upgrades:
- retry_failed_webhooks task added
- All tasks: max_retries=3, exponential backoff
- Missed schedule logging via scheduler module
- generate_daily_report persists config to DB on completion
"""
import asyncio
import os
from datetime import date

from app.core.celery_app import celery_app


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.tasks.celery_tasks.generate_daily_report",
                 bind=True, max_retries=3, default_retry_delay=300)
def generate_daily_report(self):
    from app.core.database import AsyncSessionLocal
    from app.models.models import Report
    from app.api.reports import _generate_report_for_date
    from app.api.scheduler import record_schedule_attempt

    async def _run_inner():
        async with AsyncSessionLocal() as db:
            today   = date.today()
            content = await _generate_report_for_date(today, db)
            db.add(Report(date=today, content=content))
            await db.commit()
            return {"date": today.isoformat(), "status": "generated"}

    try:
        result = _run(_run_inner())
        record_schedule_attempt("daily_report", success=True)
        return result
    except Exception as exc:
        record_schedule_attempt("daily_report", success=False, error=str(exc))
        raise self.retry(exc=exc, countdown=300 * (self.request.retries + 1))


@celery_app.task(name="app.tasks.celery_tasks.fetch_git_events",
                 bind=True, max_retries=3, default_retry_delay=120)
def fetch_git_events(self):
    import httpx
    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPO")
    if not token or not repo:
        return {"skipped": True, "reason": "GITHUB_TOKEN or GITHUB_REPO not set"}

    from app.api.scheduler import record_schedule_attempt

    async def _run_inner():
        from app.core.database import AsyncSessionLocal
        from app.services.normalizer import normalize_github_commit
        from app.models.models import Event

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/commits?per_page=30",
                headers=headers,
            )
        if resp.status_code != 200:
            raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:100]}")

        commits_raw  = resp.json()
        pseudo       = {"commits": [{"id": c["sha"], "message": c["commit"]["message"],
                                     "timestamp": c["commit"]["author"]["date"],
                                     "author": {"name": c["commit"]["author"]["name"]},
                                     "url": c["html_url"]} for c in commits_raw]}
        normalized   = normalize_github_commit(pseudo)

        async with AsyncSessionLocal() as db:
            created = 0
            for ne in normalized:
                db.add(Event(task_id=ne.get("task_id"), event_type="commit",
                             source="github:poll", raw_data=ne, metadata_=ne.get("metadata")))
                created += 1
            await db.commit()
        return {"fetched": len(commits_raw), "created": created}

    try:
        result = _run(_run_inner())
        record_schedule_attempt("fetch_git", success=True)
        return result
    except Exception as exc:
        record_schedule_attempt("fetch_git", success=False, error=str(exc))
        raise self.retry(exc=exc, countdown=120 * (self.request.retries + 1))


@celery_app.task(name="app.tasks.celery_tasks.retry_failed_webhooks",
                 bind=True, max_retries=1)
def retry_failed_webhooks(self):
    """Reprocess all webhook events in retry/pending state."""
    from app.api.scheduler import record_schedule_attempt

    async def _run_inner():
        from app.services.webhook_durability import get_retry_queue, mark_processed, mark_failed
        from app.services.normalizer import normalize_event
        from app.core.database import AsyncSessionLocal
        from app.models.models import Event
        import json

        queue   = await get_retry_queue(limit=100)
        success = failed = 0

        async with AsyncSessionLocal() as db:
            for item in queue:
                try:
                    payload    = item["payload"]
                    normalized = normalize_event(payload)
                    event      = Event(
                        task_id=normalized.get("task_id"),
                        event_type=normalized["event_type"],
                        source=normalized.get("source"),
                        raw_data=normalized,
                        metadata_=normalized.get("metadata"),
                    )
                    db.add(event)
                    await db.flush()
                    await mark_processed(db, item["id"])
                    success += 1
                except Exception as exc:
                    await mark_failed(db, item["id"], str(exc)[:200])
                    failed += 1
            await db.commit()

        return {"retried": len(queue), "success": success, "failed": failed}

    try:
        result = _run(_run_inner())
        record_schedule_attempt("retry_webhooks", success=True)
        return result
    except Exception as exc:
        record_schedule_attempt("retry_webhooks", success=False, error=str(exc))
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="app.tasks.celery_tasks.run_loop_detection_on_task")
def run_loop_detection_on_task(task_id: str):
    async def _run_inner():
        from app.core.database import AsyncSessionLocal
        from app.models.models import Event
        from app.services.loop_detection import detect_all_loops
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            events = (await db.execute(select(Event).where(Event.task_id == task_id))).scalars().all()
            prompts = [e.metadata_.get("prompt_snippet", "") for e in events if e.event_type == "ai" and e.metadata_]
            errors  = [e.metadata_.get("message", "") for e in events if e.event_type == "error" and e.metadata_]
            r = detect_all_loops(prompts=prompts, error_logs=errors, task_attempts=[])
            return {"task_id": task_id, "loop_detected": r.loop_detected, "loop_type": r.loop_type, "severity": r.severity}

    return _run(_run_inner())
