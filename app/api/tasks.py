"""
Task API

POST /task/start  — begin a task
POST /task/end    — complete a task and trigger scoring
GET  /task/{id}   — get task details
GET  /task/       — list tasks
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Event, Score, Task
from app.services.loop_detection import detect_all_loops
from app.services.scoring import score_from_task_data

router = APIRouter(prefix="/task", tags=["Tasks"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class TaskStartRequest(BaseModel):
    goal: str = Field(..., min_length=3, max_length=500)
    target_level: int = Field(..., ge=0, le=5)
    project_id: Optional[str] = None


class TaskEndRequest(BaseModel):
    task_id: str
    final_level: int = Field(..., ge=0, le=5)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/start", status_code=201)
async def start_task(req: TaskStartRequest, db: AsyncSession = Depends(get_db)):
    """Start a new task. Returns task_id for use in commits, AI prompts, and events."""
    task = Task(
        goal=req.goal,
        target_level=req.target_level,
        project_id=req.project_id,
        status="active",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return {
        "task_id": task.id,
        "goal": task.goal,
        "target_level": task.target_level,
        "started_at": task.started_at,
        "status": task.status,
        "instructions": (
            f"Add [EAS-{task.id}] to your git commits. "
            f"Send task_id='{task.id}' with all AI proxy requests."
        ),
    }


@router.post("/end")
async def end_task(req: TaskEndRequest, db: AsyncSession = Depends(get_db)):
    """
    Mark task as complete, compute score, run loop detection.
    """
    result = await db.execute(select(Task).where(Task.id == req.task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task.status == "completed":
        raise HTTPException(status_code=409, detail="Task already completed.")

    task.final_level = req.final_level
    task.ended_at = datetime.utcnow()
    task.status = "completed"
    await db.flush()

    # Fetch associated events
    ev_result = await db.execute(select(Event).where(Event.task_id == req.task_id))
    events = ev_result.scalars().all()
    events_dicts = [
        {
            "event_type": e.event_type,
            "timestamp": e.timestamp,
            "metadata": e.metadata_ or {},
        }
        for e in events
    ]

    # Loop detection
    prompts = [
        e.metadata_.get("prompt_snippet", "") for e in events
        if e.event_type == "ai" and e.metadata_
    ]
    error_logs = [
        e.metadata_.get("message", "") for e in events
        if e.event_type == "error" and e.metadata_
    ]
    loop_result = detect_all_loops(prompts=prompts, error_logs=error_logs, task_attempts=[])

    task_dict = {
        "goal": task.goal,
        "target_level": task.target_level,
        "final_level": req.final_level,
        "started_at": task.started_at,
        "ended_at": task.ended_at,
        "loop_detected": loop_result.loop_detected,
        "loop_severity": loop_result.severity,
    }

    breakdown = score_from_task_data(task_dict, events_dicts)

    # Persist score
    score_row = Score(
        task_id=task.id,
        date=task.date,
        level=req.final_level,
        velocity=breakdown.velocity,
        stability_penalty=breakdown.stability_penalty,
        ai_penalty=breakdown.ai_penalty,
        final_score=breakdown.final_score,
    )
    db.add(score_row)
    await db.commit()

    return {
        "task_id": task.id,
        "status": "completed",
        "final_level": req.final_level,
        "score": breakdown.details,
        "loop_detection": {
            "loop_detected": loop_result.loop_detected,
            "loop_type": loop_result.loop_type,
            "severity": loop_result.severity,
            "evidence": loop_result.evidence[:3],
        },
    }


@router.get("/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    sc_result = await db.execute(select(Score).where(Score.task_id == task_id))
    score = sc_result.scalar_one_or_none()

    return {
        "id": task.id,
        "goal": task.goal,
        "target_level": task.target_level,
        "final_level": task.final_level,
        "status": task.status,
        "started_at": task.started_at,
        "ended_at": task.ended_at,
        "score": {
            "level": score.level,
            "velocity": score.velocity,
            "stability_penalty": score.stability_penalty,
            "ai_penalty": score.ai_penalty,
            "final_score": score.final_score,
        } if score else None,
    }


@router.get("/")
async def list_tasks(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Task).order_by(Task.started_at.desc()).limit(50)
    if status:
        q = q.where(Task.status == status)
    result = await db.execute(q)
    tasks = result.scalars().all()
    return [
        {
            "id": t.id,
            "goal": t.goal[:60],
            "target_level": t.target_level,
            "final_level": t.final_level,
            "status": t.status,
            "started_at": t.started_at,
        }
        for t in tasks
    ]
