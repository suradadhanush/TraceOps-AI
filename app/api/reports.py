"""
Report API

GET  /report/daily       — get today's report (generate if missing)
GET  /report/{date}      — get report for specific date (YYYY-MM-DD)
POST /report/generate    — force-generate report for today
POST /report/validate    — run deployment validation on a URL
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Event, Report, Score, Task
from app.services.deployment import validate_deployment
from app.services.llm_analyzer import run_analysis
from app.services.loop_detection import detect_all_loops
from app.services.report_gen import build_report, report_to_markdown
from app.services.scoring import score_from_task_data

router = APIRouter(prefix="/report", tags=["Reports"])


class ValidateRequest(BaseModel):
    url: str
    functional_path: str = "/health"
    functional_expected_status: int = 200
    functional_expected_keys: Optional[list[str]] = None


# ── Core: build today's report data ─────────────────────────────────────────

async def _generate_report_for_date(target_date: date, db: AsyncSession) -> dict:
    # Fetch all tasks for the date
    task_result = await db.execute(
        select(Task).where(Task.date == target_date)
    )
    tasks = task_result.scalars().all()
    if not tasks:
        return {
            "meta": {"date": target_date.isoformat()},
            "summary": {"total_tasks": 0, "completed_tasks": 0, "average_score": 0, "score_grade": "N/A"},
            "tasks": [],
            "scores": [],
            "loop_detection": [],
            "deployment_validation": [],
            "analysis": {"bottlenecks": [], "root_cause": "No tasks recorded.", "corrective_actions": []},
        }

    task_ids = [t.id for t in tasks]

    # Fetch events
    ev_result = await db.execute(
        select(Event).where(Event.task_id.in_(task_ids))
    )
    all_events = ev_result.scalars().all()

    # Fetch existing scores
    sc_result = await db.execute(
        select(Score).where(Score.task_id.in_(task_ids))
    )
    scores = sc_result.scalars().all()

    # Loop detection per task
    loop_results = []
    for task in tasks:
        task_events = [e for e in all_events if e.task_id == task.id]
        prompts = [
            e.metadata_.get("prompt_snippet", "") for e in task_events
            if e.event_type == "ai" and e.metadata_
        ]
        error_logs = [
            e.metadata_.get("message", "") for e in task_events
            if e.event_type == "error" and e.metadata_
        ]
        lr = detect_all_loops(prompts=prompts, error_logs=error_logs, task_attempts=[])
        loop_results.append({
            "task_id": task.id,
            "loop_detected": lr.loop_detected,
            "loop_type": lr.loop_type,
            "severity": lr.severity,
            "evidence": lr.evidence[:3],
        })

    # Scores as dicts
    scores_dicts = [
        {
            "task_id": s.task_id,
            "level": s.level,
            "velocity": s.velocity,
            "stability_penalty": s.stability_penalty,
            "ai_penalty": s.ai_penalty,
            "final_score": s.final_score,
            "outcome_score": s.level * 10,
        }
        for s in scores
    ]

    # Aggregate events for LLM analysis
    all_events_dicts = [
        {
            "event_type": e.event_type,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "metadata": e.metadata_ or {},
        }
        for e in all_events
    ]

    # Summarize tasks for LLM
    completed = [t for t in tasks if t.status == "completed"]
    avg_score = (
        sum(s["final_score"] for s in scores_dicts) / len(scores_dicts)
        if scores_dicts else 0
    )
    task_summary = {
        "goal": f"{len(tasks)} tasks, {len(completed)} completed",
        "target_level": max((t.target_level for t in tasks), default=0),
        "final_level": max((t.final_level or 0 for t in tasks), default=0),
        "started_at": min((t.started_at for t in tasks), default=None),
        "ended_at": max((t.ended_at for t in tasks if t.ended_at), default=None),
    }

    analysis = await run_analysis(
        task_data=task_summary,
        events=all_events_dicts,
        score={"average_score": round(avg_score, 1), "scores": scores_dicts},
    )

    tasks_dicts = [
        {
            "id": t.id,
            "goal": t.goal,
            "target_level": t.target_level,
            "final_level": t.final_level,
            "status": t.status,
            "started_at": t.started_at,
            "ended_at": t.ended_at,
        }
        for t in tasks
    ]

    return build_report(
        report_date=target_date,
        tasks=tasks_dicts,
        scores=scores_dicts,
        analysis=analysis,
        loop_results=loop_results,
        deploy_results=[],
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/daily")
async def get_daily_report(db: AsyncSession = Depends(get_db)):
    """Return today's report from DB, or generate if missing."""
    today = date.today()
    result = await db.execute(
        select(Report).where(Report.date == today).order_by(Report.created_at.desc()).limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing.content

    # Generate fresh
    content = await _generate_report_for_date(today, db)
    report_row = Report(date=today, content=content)
    db.add(report_row)
    await db.commit()
    return content


@router.get("/daily/markdown")
async def get_daily_report_markdown(db: AsyncSession = Depends(get_db)):
    """Return today's report as a Markdown string."""
    from fastapi.responses import PlainTextResponse
    today = date.today()
    content = await _generate_report_for_date(today, db)
    return PlainTextResponse(report_to_markdown(content), media_type="text/markdown")


@router.get("/{report_date}")
async def get_report_by_date(report_date: str, db: AsyncSession = Depends(get_db)):
    try:
        d = date.fromisoformat(report_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    result = await db.execute(
        select(Report).where(Report.date == d).order_by(Report.created_at.desc()).limit(1)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail=f"No report for {report_date}.")
    return report.content


@router.post("/generate", status_code=201)
async def force_generate_report(db: AsyncSession = Depends(get_db)):
    """Force-generate and store today's report (overwrites existing)."""
    today = date.today()
    content = await _generate_report_for_date(today, db)
    report_row = Report(date=today, content=content)
    db.add(report_row)
    await db.commit()
    return {"message": "Report generated.", "date": today.isoformat(), "report": content}


@router.post("/validate")
async def run_validation(req: ValidateRequest):
    """Validate a deployed service's health and functional endpoints."""
    result = await validate_deployment(
        base_url=req.url,
        functional_path=req.functional_path,
        functional_expected_status=req.functional_expected_status,
        functional_expected_keys=req.functional_expected_keys,
    )
    return {
        "url": req.url,
        "status": result.status,
        "score": result.score,
        "summary": result.summary,
        "checks": [
            {
                "url": c.url,
                "status_code": c.status_code,
                "latency_ms": c.latency_ms,
                "success": c.success,
                "error": c.error,
            }
            for c in result.checks
        ],
    }
