"""
User Dashboard API

All endpoints are user-scoped — returns only data belonging to the authenticated user.

GET /user/dashboard     → aggregated dashboard data
GET /user/stats         → contribution stats and streaks
GET /user/activity      → recent activity timeline
GET /user/repositories  → GitHub repos (if connected)
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import AIProxyLog, Event, Integration, Report, Score, Task, User
from app.api.auth.deps import get_current_user
import httpx

router = APIRouter(prefix="/user", tags=["User"])


@router.get("/dashboard")
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full dashboard data for the authenticated user."""
    today = date.today()
    uid   = current_user.id

    # Active tasks
    active_tasks = (await db.execute(
        select(Task).where(Task.user_id == uid, Task.status == "active")
        .order_by(Task.started_at.desc()).limit(5)
    )).scalars().all()

    # Today's completed tasks
    completed_today = (await db.execute(
        select(func.count(Task.id))
        .where(Task.user_id == uid, Task.status == "completed", Task.date == today)
    )).scalar() or 0

    # Today's scores
    today_scores = (await db.execute(
        select(Score)
        .join(Task, Score.task_id == Task.id)
        .where(Task.user_id == uid, Score.date == today)
    )).scalars().all()

    avg_score = (
        round(sum(s.final_score for s in today_scores) / len(today_scores), 1)
        if today_scores else None
    )

    # Recent events (last 20)
    recent_events = (await db.execute(
        select(Event).where(Event.user_id == uid)
        .order_by(Event.timestamp.desc()).limit(20)
    )).scalars().all()

    # Connected integrations count
    integrations = (await db.execute(
        select(Integration).where(Integration.user_id == uid, Integration.status == "connected")
    )).scalars().all()

    # 7-day score trend
    seven_days_ago = today - timedelta(days=7)
    week_scores = (await db.execute(
        select(Score.date, func.avg(Score.final_score).label("avg"))
        .join(Task, Score.task_id == Task.id)
        .where(Task.user_id == uid, Score.date >= seven_days_ago)
        .group_by(Score.date)
        .order_by(Score.date.asc())
    )).all()

    # Today's events counts by type
    today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    event_counts = (await db.execute(
        select(Event.event_type, func.count(Event.id).label("count"))
        .where(Event.user_id == uid, Event.timestamp >= today_start)
        .group_by(Event.event_type)
    )).all()

    return {
        "user": {
            "id":              current_user.id,
            "name":            current_user.name,
            "email":           current_user.email,
            "avatar_url":      current_user.avatar_url,
            "github_username": current_user.github_username,
        },
        "today": {
            "date":              today.isoformat(),
            "active_tasks":      len(active_tasks),
            "completed_tasks":   completed_today,
            "average_score":     avg_score,
            "events_by_type":    {r.event_type: r.count for r in event_counts},
        },
        "active_tasks": [
            {
                "id":           t.id,
                "goal":         t.goal,
                "target_level": t.target_level,
                "started_at":   t.started_at.isoformat() if t.started_at else None,
            }
            for t in active_tasks
        ],
        "recent_events": [
            {
                "id":         e.id,
                "event_type": e.event_type,
                "source":     e.source,
                "timestamp":  e.timestamp.isoformat() if e.timestamp else None,
                "metadata":   e.metadata_ or {},
            }
            for e in recent_events
        ],
        "score_trend": [
            {"date": str(r.date), "avg_score": round(float(r.avg), 1)}
            for r in week_scores
        ],
        "integrations_connected": len(integrations),
        "integrations": [
            {"provider": i.provider, "username": i.provider_username}
            for i in integrations
        ],
    }


@router.get("/stats")
async def get_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execution stats: streaks, totals, averages."""
    uid = current_user.id

    total_tasks = (await db.execute(
        select(func.count(Task.id)).where(Task.user_id == uid)
    )).scalar() or 0

    total_completed = (await db.execute(
        select(func.count(Task.id)).where(Task.user_id == uid, Task.status == "completed")
    )).scalar() or 0

    all_scores = (await db.execute(
        select(Score)
        .join(Task, Score.task_id == Task.id)
        .where(Task.user_id == uid)
        .order_by(Score.date.desc())
    )).scalars().all()

    avg_score    = round(sum(s.final_score for s in all_scores) / len(all_scores), 1) if all_scores else None
    best_score   = max((s.final_score for s in all_scores), default=None)
    total_events = (await db.execute(
        select(func.count(Event.id)).where(Event.user_id == uid)
    )).scalar() or 0

    # Commit count
    commit_count = (await db.execute(
        select(func.count(Event.id)).where(Event.user_id == uid, Event.event_type == "commit")
    )).scalar() or 0

    # AI usage count
    ai_count = (await db.execute(
        select(func.count(AIProxyLog.id)).where(AIProxyLog.user_id == uid)
    )).scalar() or 0

    # Streak: consecutive days with completed tasks
    score_dates = sorted({s.date for s in all_scores}, reverse=True)
    streak = 0
    today  = date.today()
    for i, d in enumerate(score_dates):
        expected = today - timedelta(days=i)
        if d == expected:
            streak += 1
        else:
            break

    return {
        "total_tasks":     total_tasks,
        "completed_tasks": total_completed,
        "completion_rate": round(total_completed / max(1, total_tasks) * 100, 1),
        "average_score":   avg_score,
        "best_score":      best_score,
        "current_streak":  streak,
        "total_events":    total_events,
        "total_commits":   commit_count,
        "total_ai_calls":  ai_count,
    }


@router.get("/activity")
async def get_activity(
    limit: int = 50,
    event_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent activity timeline for the user."""
    q = (
        select(Event)
        .where(Event.user_id == current_user.id)
        .order_by(Event.timestamp.desc())
        .limit(min(limit, 200))
    )
    if event_type:
        q = q.where(Event.event_type == event_type)

    events = (await db.execute(q)).scalars().all()
    return {
        "events": [
            {
                "id":         e.id,
                "event_type": e.event_type,
                "source":     e.source,
                "task_id":    e.task_id,
                "timestamp":  e.timestamp.isoformat() if e.timestamp else None,
                "metadata":   e.metadata_ or {},
            }
            for e in events
        ]
    }


@router.get("/repositories")
async def get_repositories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch live GitHub repositories for connected user."""
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user.id,
            Integration.provider == "github",
            Integration.status == "connected",
        )
    )
    github_integ = result.scalar_one_or_none()

    if not github_integ or not github_integ.access_token:
        return {
            "connected": False,
            "message": "GitHub not connected. Go to /app/settings to connect.",
            "repositories": [],
        }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.github.com/user/repos?per_page=30&sort=pushed&type=owner",
                headers={"Authorization": f"Bearer {github_integ.access_token}"},
            )
            if r.status_code != 200:
                return {"connected": True, "error": "GitHub API error", "repositories": []}
            repos = r.json()
            return {
                "connected": True,
                "repositories": [
                    {
                        "id":          repo["id"],
                        "name":        repo["name"],
                        "full_name":   repo["full_name"],
                        "description": repo.get("description"),
                        "language":    repo.get("language"),
                        "stars":       repo["stargazers_count"],
                        "forks":       repo["forks_count"],
                        "updated_at":  repo["updated_at"],
                        "url":         repo["html_url"],
                        "private":     repo["private"],
                    }
                    for repo in repos
                ],
            }
    except Exception as e:
        return {"connected": True, "error": str(e)[:100], "repositories": []}
