"""
Secured Metrics API v4 (Fix 4)

Changes from v3:
- X-Metrics-Key required for /metrics, /tune, /config, /webhook/replay
- /metrics/public - no auth, limited view only
- Rate limit: 10 req/min per IP (sliding window, in-memory)
- Sensitive thresholds NOT exposed on public endpoint
- POST /metrics/webhook/replay - reprocess failed webhook events
- GET /metrics/proxy/coverage - proxy enforcement summary
"""
import statistics
import time
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.eas_config import eas_config
from app.models.models import Event, Score, Task
from app.services.task_enforcement import coverage_metrics
from app.services.webhook_durability import get_failed_events, get_retry_queue, webhook_stats
from app.services.proxy_enforcement import compute_proxy_coverage, detect_proxy_gaps

router = APIRouter(prefix="/metrics", tags=["Diagnostics"])

_manual_scores: list[dict] = []
_loop_feedback: list[dict] = []

# Rate limiter
_rate_windows: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT  = 10
RATE_WINDOW = 60.0


def _check_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    _rate_windows[ip] = [t for t in _rate_windows[ip] if now - t < RATE_WINDOW]
    if len(_rate_windows[ip]) >= RATE_LIMIT:
        return False
    _rate_windows[ip].append(now)
    return True


def _require_key(key: Optional[str]):
    import hmac as _hmac
    if not key or not _hmac.compare_digest(key, settings.SECRET_KEY):
        raise HTTPException(status_code=403, detail="Invalid or missing X-Metrics-Key.")


def _safe_mean(v: list) -> Optional[float]:
    return round(statistics.mean(v), 3) if v else None

def _safe_stdev(v: list) -> Optional[float]:
    return round(statistics.stdev(v), 3) if len(v) > 1 else None

def _distribution(v: list) -> dict:
    if not v:
        return {}
    return {"count": len(v), "mean": _safe_mean(v), "median": round(statistics.median(v), 3),
            "min": round(min(v), 3), "max": round(max(v), 3), "stdev": _safe_stdev(v)}

def _loop_fp_rate() -> Optional[float]:
    if not _loop_feedback:
        return None
    return round(sum(1 for f in _loop_feedback if not f["was_actual_loop"]) / len(_loop_feedback), 3)


@router.get("/")
async def get_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_metrics_key: Optional[str] = Header(None, alias="X-Metrics-Key"),
):
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Rate limit: 10 req/min.")
    _require_key(x_metrics_key)

    today    = date.today()
    cfg      = eas_config.metrics
    coverage = coverage_metrics.to_dict()

    ev_result = await db.execute(
        select(Event).where(Event.timestamp >= datetime.combine(today, datetime.min.time())).limit(1000)
    )
    events      = ev_result.scalars().all()
    confidences = [float(e.metadata_.get("_correlation_confidence", 0))
                   for e in events if e.metadata_ and "_correlation_confidence" in e.metadata_]

    deviations  = [abs(r["human_score"] - r["system_score"])
                   for r in _manual_scores if r.get("system_score") is not None]
    fp_rate     = _loop_fp_rate()

    task_result = await db.execute(
        select(func.count(Task.id).label("t"), func.count(Task.id).filter(Task.status == "completed").label("c"))
        .where(Task.date == today)
    )
    row = task_result.one()
    sv  = [s.final_score for s in (await db.execute(select(Score).where(Score.date == today))).scalars().all()]

    wh_stats  = await webhook_stats()
    proxy_cov = await compute_proxy_coverage(db, today)
    low_conf  = round(sum(1 for c in confidences if c < 0.3) / max(1, len(confidences)) * 100, 1) if confidences else 0.0

    return {
        "date": today.isoformat(),
        "generated_at": datetime.utcnow().isoformat(),
        "task_id_coverage": coverage,
        "correlation": {"events_analyzed": len(confidences), "confidence_distribution": _distribution(confidences), "low_confidence_pct": low_conf},
        "scoring": {"tasks_today": row.t, "completed_today": row.c, "score_distribution": _distribution(sv),
                    "manual_comparisons": len(_manual_scores), "score_deviation": _distribution(deviations),
                    "deviation_ok": (_safe_mean(deviations) or 0) < cfg.score_deviation_max_points if deviations else None},
        "loop_detection": {"feedback_count": len(_loop_feedback), "false_positive_rate": fp_rate,
                           "fp_rate_ok": fp_rate < cfg.loop_fp_rate_max if fp_rate is not None else None},
        "webhook_durability": wh_stats,
        "proxy_enforcement": proxy_cov,
        "adaptive_tuning": {"last_tuning": eas_config._tuning_log[-1] if eas_config._tuning_log else None,
                            "entries": len(eas_config._tuning_log)},
        "acceptance_criteria": {
            "task_id_coverage_pct":   {"value": coverage["coverage_pct"],  "threshold": cfg.task_id_coverage_min_pct,    "ok": coverage["coverage_pct"] >= cfg.task_id_coverage_min_pct},
            "score_deviation_points": {"value": _safe_mean(deviations),    "threshold": cfg.score_deviation_max_points,   "ok": (_safe_mean(deviations) or 0) < cfg.score_deviation_max_points if deviations else None},
            "loop_fp_rate":           {"value": fp_rate,                   "threshold": cfg.loop_fp_rate_max,             "ok": fp_rate < cfg.loop_fp_rate_max if fp_rate is not None else None},
            "proxy_coverage_pct":     {"value": proxy_cov["coverage_pct"], "threshold": 80.0,                             "ok": proxy_cov["coverage_pct"] >= 80.0},
        },
    }


@router.get("/public")
async def get_public_metrics(request: Request, db: AsyncSession = Depends(get_db)):
    """No auth. Safe limited view only — no thresholds, no internal state."""
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Rate limit: 10 req/min.")
    today = date.today()
    row   = (await db.execute(
        select(func.count(Task.id).label("t"), func.count(Task.id).filter(Task.status == "completed").label("c"))
        .where(Task.date == today)
    )).one()
    sv = [s.final_score for s in (await db.execute(select(Score).where(Score.date == today))).scalars().all()]
    return {
        "date": today.isoformat(),
        "tasks_today": row.t,
        "completed_today": row.c,
        "avg_score": round(sum(sv) / len(sv), 1) if sv else None,
        "system_status": "operational",
    }


class ManualScoreInput(BaseModel):
    date: str
    human_score: int
    task_id: Optional[str] = None
    notes: Optional[str] = None

class LoopFeedback(BaseModel):
    task_id: str
    was_actual_loop: bool
    notes: Optional[str] = None

class TuningRequest(BaseModel):
    force: bool = False


@router.post("/score/manual")
async def submit_manual_score(data: ManualScoreInput, db: AsyncSession = Depends(get_db),
                               x_metrics_key: Optional[str] = Header(None, alias="X-Metrics-Key")):
    _require_key(x_metrics_key)
    target = date.fromisoformat(data.date)
    sys_sc = None
    if data.task_id:
        r = (await db.execute(select(Score).where(Score.task_id == data.task_id))).scalar_one_or_none()
        if r: sys_sc = r.final_score
    else:
        rows = (await db.execute(select(Score).where(Score.date == target))).scalars().all()
        if rows: sys_sc = round(sum(s.final_score for s in rows) / len(rows), 1)
    dev = abs(data.human_score - sys_sc) if sys_sc is not None else None
    _manual_scores.append({"date": data.date, "human_score": data.human_score, "system_score": sys_sc,
                            "deviation": dev, "task_id": data.task_id, "notes": data.notes,
                            "submitted_at": datetime.utcnow().isoformat()})
    cfg = eas_config.metrics
    return {"recorded": True, "human_score": data.human_score, "system_score": sys_sc, "deviation": dev,
            "deviation_ok": dev < cfg.score_deviation_max_points if dev is not None else None}


@router.post("/loop/feedback")
async def submit_loop_feedback(data: LoopFeedback,
                                x_metrics_key: Optional[str] = Header(None, alias="X-Metrics-Key")):
    _require_key(x_metrics_key)
    _loop_feedback.append({"task_id": data.task_id, "was_actual_loop": data.was_actual_loop,
                            "notes": data.notes, "submitted_at": datetime.utcnow().isoformat()})
    fp = _loop_fp_rate()
    return {"recorded": True, "false_positive_rate": fp,
            "fp_rate_ok": fp < eas_config.metrics.loop_fp_rate_max if fp is not None else None}


@router.post("/tune")
async def run_adaptive_tuning(req: TuningRequest,
                               x_metrics_key: Optional[str] = Header(None, alias="X-Metrics-Key")):
    _require_key(x_metrics_key)
    cfg = eas_config
    if len(_manual_scores) < 5 and not req.force:
        return {"tuned": False, "reason": f"Need ≥5 manual scores (have {len(_manual_scores)})."}
    if not req.force and cfg._tuning_log:
        days = (datetime.utcnow() - datetime.fromisoformat(cfg._tuning_log[-1]["timestamp"])).days
        if days < cfg.metrics.tuning_frequency_days:
            return {"tuned": False, "reason": f"Last tuning {days}d ago."}

    devs    = [abs(r["human_score"] - r["system_score"]) for r in _manual_scores if r.get("system_score") is not None]
    avg_dev = _safe_mean(devs) or 0
    fp      = _loop_fp_rate()
    cov     = coverage_metrics.coverage_pct
    max_c   = cfg.metrics.tuning_max_change_pct

    def _clamp(old: float, new: float) -> float:
        md = abs(old * max_c); return round(old + max(-md, min(md, new - old)), 4)

    changes = {}
    if avg_dev > cfg.metrics.score_deviation_max_points * 1.5:
        old = cfg.loop_detection.similarity_threshold_normal
        cfg.loop_detection.similarity_threshold_normal = _clamp(old, old + 0.02)
        changes["loop_threshold_normal"] = {"before": old, "after": cfg.loop_detection.similarity_threshold_normal}
    if fp is not None and fp > cfg.metrics.loop_fp_rate_max:
        old = cfg.loop_detection.similarity_threshold_debugging
        cfg.loop_detection.similarity_threshold_debugging = _clamp(old, min(0.98, old + 0.02))
        changes["loop_threshold_debugging"] = {"before": old, "after": cfg.loop_detection.similarity_threshold_debugging}
    if cov < cfg.metrics.task_id_coverage_min_pct:
        old = float(cfg.task_enforcement.auto_assign_window_minutes)
        cfg.task_enforcement.auto_assign_window_minutes = int(_clamp(old, old * 1.1))
        changes["auto_assign_window_minutes"] = {"before": int(old), "after": cfg.task_enforcement.auto_assign_window_minutes}

    entry = {"timestamp": datetime.utcnow().isoformat(),
             "trigger": {"avg_score_deviation": avg_dev, "loop_fp_rate": fp, "coverage_pct": cov},
             "changes": changes}
    cfg._tuning_log.append(entry)
    try:
        from app.services.config_store import save_config_to_db
        import asyncio; asyncio.create_task(save_config_to_db(cfg))
    except Exception:
        pass
    return {"tuned": True, "changes": changes, "log_entry": entry,
            "message": f"{len(changes)} adjusted." if changes else "Within thresholds."}


@router.get("/tune/log")
async def tuning_log(x_metrics_key: Optional[str] = Header(None, alias="X-Metrics-Key")):
    _require_key(x_metrics_key)
    return {"entries": len(eas_config._tuning_log), "log": eas_config._tuning_log[-20:]}


@router.get("/config")
async def current_config(x_metrics_key: Optional[str] = Header(None, alias="X-Metrics-Key")):
    _require_key(x_metrics_key)
    return eas_config.to_dict()


@router.get("/coverage/reset")
async def reset_coverage(x_metrics_key: Optional[str] = Header(None, alias="X-Metrics-Key")):
    _require_key(x_metrics_key)
    coverage_metrics.reset()
    return {"reset": True}


@router.post("/webhook/replay")
async def replay_webhooks(x_metrics_key: Optional[str] = Header(None, alias="X-Metrics-Key")):
    _require_key(x_metrics_key)
    try:
        from app.core.celery_app import celery_app
        r = celery_app.send_task("app.tasks.celery_tasks.retry_failed_webhooks")
        return {"triggered": True, "task_id": r.id}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/webhook/stats")
async def get_webhook_stats_view(x_metrics_key: Optional[str] = Header(None, alias="X-Metrics-Key")):
    _require_key(x_metrics_key)
    return {"stats": await webhook_stats(), "failed_sample": (await get_failed_events(20))[:5]}


@router.get("/proxy/coverage")
async def proxy_coverage_view(db: AsyncSession = Depends(get_db),
                               x_metrics_key: Optional[str] = Header(None, alias="X-Metrics-Key")):
    _require_key(x_metrics_key)
    return {"coverage": await compute_proxy_coverage(db), "gaps": await detect_proxy_gaps(db)}
