"""
AI Proxy Enforcement (Fix 5)

Detects gaps between AI usage in proxy logs vs expected usage patterns.
Warns when proxy usage drops below 80% threshold.
Logs suspected bypass events.
Tracks per-task proxy coverage.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import log_proxy_bypass_warning
from app.models.models import AIProxyLog, Event

log = logging.getLogger("traceops.proxy_enforcement")

PROXY_COVERAGE_MIN = 0.80     # warn if < 80% of expected AI events went through proxy
BYPASS_GAP_HOURS   = 2.0      # gap in proxy logs > this hours = suspected bypass


# ── Per-day proxy coverage ────────────────────────────────────────────────────

async def compute_proxy_coverage(db: AsyncSession, target_date: Optional[date] = None) -> dict:
    """
    Compare:
      - AI events ingested through proxy (AIProxyLog table)
      - AI events in general Event table (event_type='ai')

    Coverage = proxy_count / max(1, total_ai_events)
    """
    target_date = target_date or date.today()
    day_start   = datetime.combine(target_date, datetime.min.time())
    day_end     = datetime.combine(target_date, datetime.max.time())

    # Events recorded via proxy
    proxy_result = await db.execute(
        select(func.count(AIProxyLog.id))
        .where(AIProxyLog.timestamp >= day_start)
        .where(AIProxyLog.timestamp <= day_end)
    )
    proxy_count = proxy_result.scalar() or 0

    # All AI events (proxy + direct if somehow logged)
    ev_result = await db.execute(
        select(func.count(Event.id))
        .where(Event.event_type == "ai")
        .where(Event.timestamp >= day_start)
        .where(Event.timestamp <= day_end)
    )
    total_ai = ev_result.scalar() or 0

    coverage = proxy_count / max(1, total_ai)
    below_threshold = coverage < PROXY_COVERAGE_MIN

    if below_threshold and total_ai > 3:
        log.warning(
            f"Proxy coverage {coverage:.0%} below threshold {PROXY_COVERAGE_MIN:.0%} "
            f"({proxy_count}/{total_ai} AI events via proxy)"
        )

    return {
        "date": target_date.isoformat(),
        "proxy_events": proxy_count,
        "total_ai_events": total_ai,
        "coverage_pct": round(coverage * 100, 1),
        "below_threshold": below_threshold,
        "threshold_pct": PROXY_COVERAGE_MIN * 100,
        "warning": below_threshold and total_ai > 3,
    }


# ── Gap detection ─────────────────────────────────────────────────────────────

async def detect_proxy_gaps(
    db: AsyncSession,
    task_id: Optional[str] = None,
    target_date: Optional[date] = None,
) -> list[dict]:
    """
    Find gaps in proxy log timeline > BYPASS_GAP_HOURS during active hours.
    A long silence in proxy logs while task was active = possible direct AI use.

    Returns list of gap dicts: {"start", "end", "gap_hours", "severity"}.
    """
    target_date = target_date or date.today()
    day_start   = datetime.combine(target_date, datetime.min.time())
    day_end     = datetime.combine(target_date, datetime.max.time())

    q = select(AIProxyLog.timestamp).where(
        AIProxyLog.timestamp >= day_start,
        AIProxyLog.timestamp <= day_end,
    )
    if task_id:
        q = q.where(AIProxyLog.task_id == task_id)
    q = q.order_by(AIProxyLog.timestamp.asc())

    result = await db.execute(q)
    timestamps = [row[0] for row in result.all()]

    if len(timestamps) < 2:
        return []

    gaps = []
    for i in range(len(timestamps) - 1):
        gap_hours = (timestamps[i+1] - timestamps[i]).total_seconds() / 3600
        if gap_hours > BYPASS_GAP_HOURS:
            severity = "high" if gap_hours > 4 else "medium"
            gaps.append({
                "start": timestamps[i].isoformat(),
                "end": timestamps[i+1].isoformat(),
                "gap_hours": round(gap_hours, 2),
                "severity": severity,
            })
            log_proxy_bypass_warning(gap_hours, direct_usage_estimate=0)

    return gaps


# ── Per-task proxy summary ────────────────────────────────────────────────────

async def task_proxy_summary(db: AsyncSession, task_id: str) -> dict:
    """
    Summary of proxy usage for a specific task.
    Flags if coverage is insufficient or gaps detected.
    """
    result = await db.execute(
        select(AIProxyLog).where(AIProxyLog.task_id == task_id)
        .order_by(AIProxyLog.timestamp.asc())
    )
    logs = result.scalars().all()

    total_prompts    = len(logs)
    errored          = sum(1 for l in logs if l.error)
    total_tokens     = sum((l.prompt_tokens or 0) + (l.completion_tokens or 0) for l in logs)
    avg_latency      = (
        sum(l.latency_ms or 0 for l in logs) / total_prompts
        if total_prompts > 0 else 0
    )
    providers        = list({l.provider for l in logs})

    # Detect bypass gaps within task timeline
    gaps: list[dict] = []
    ts_list = [l.timestamp for l in logs if l.timestamp]
    if len(ts_list) >= 2:
        for i in range(len(ts_list) - 1):
            gap_h = (ts_list[i+1] - ts_list[i]).total_seconds() / 3600
            if gap_h > BYPASS_GAP_HOURS:
                gaps.append({"gap_hours": round(gap_h, 2), "after": ts_list[i].isoformat()})

    return {
        "task_id": task_id,
        "total_proxy_prompts": total_prompts,
        "errored": errored,
        "total_tokens": total_tokens,
        "avg_latency_ms": round(avg_latency),
        "providers": providers,
        "suspected_bypass_gaps": gaps,
        "bypass_suspected": len(gaps) > 0,
    }
