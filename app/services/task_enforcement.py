"""
TASK_ID Enforcement v3

Upgrades from v2:
- Confidence-based auto-assignment (time + event similarity + task density)
- Assign only if confidence >= config threshold (else → "unassigned")
- HMAC-SHA256 validation with replay protection
- auto_assignment_accuracy_estimate metric
- Backward-compatible: enforce_task_id() signature unchanged
"""
import hashlib
import hmac
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.eas_config import eas_config
from app.models.models import Event, Task


# ── HMAC ─────────────────────────────────────────────────────────────────────

def generate_proxy_signature(task_id: str, timestamp: int) -> str:
    msg = f"{task_id}:{timestamp}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def verify_proxy_signature(task_id: str, signature: str, timestamp: int) -> bool:
    cfg = eas_config.task_enforcement
    if abs(int(time.time()) - timestamp) > cfg.hmac_max_age_seconds:
        return False
    expected = generate_proxy_signature(task_id, timestamp)
    return hmac.compare_digest(expected, signature)


# ── Confidence-based auto-assignment ─────────────────────────────────────────

def _parse_dt(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


def _time_proximity_score(event_ts: datetime, task: Task, window_min: int) -> float:
    """Decay from 1.0 (inside task window) to 0.0 at window boundary."""
    started = task.started_at
    ended   = task.ended_at or datetime.utcnow()
    if not started:
        return 0.0
    if started <= event_ts <= ended:
        return 1.0
    delta = (started - event_ts).total_seconds() if event_ts < started else (event_ts - ended).total_seconds()
    max_d = window_min * 60
    return max(0.0, 1.0 - delta / max_d) if delta < max_d else 0.0


def _task_density_score(tasks_in_window: list[Task]) -> float:
    """
    Penalise assignment confidence when many tasks overlap (high ambiguity).
    Returns 0.0 (many tasks = low confidence) to 1.0 (single task = high confidence).
    """
    n = len(tasks_in_window)
    if n == 0:
        return 0.0
    return 1.0 / n


def _event_similarity_score(event: dict, task: Task) -> float:
    """Semantic similarity between event text and task goal. 0.0 if model not loaded."""
    meta = event.get("metadata") or {}
    text = " ".join(str(v) for k, v in meta.items()
                    if k in ("message", "prompt_snippet", "description") and isinstance(v, str))[:200]
    if not text.strip() or not task.goal:
        return 0.0
    try:
        from app.services.loop_detection import _get_model, _cosine_similarity
        emb = _get_model().encode([text, task.goal], normalize_embeddings=True)
        return float(_cosine_similarity(emb[0], emb[1]))
    except Exception:
        return 0.0


async def _compute_assignment_confidence(
    event: dict,
    task: Task,
    all_candidates: list[Task],
    event_ts: datetime,
) -> float:
    """
    Composite confidence:
      0.50 × time_proximity
    + 0.30 × event_similarity
    + 0.20 × (1/density)

    Returns 0.0–1.0.
    """
    cfg = eas_config.task_enforcement
    t  = _time_proximity_score(event_ts, task, cfg.auto_assign_window_minutes)
    s  = _event_similarity_score(event, task)
    d  = _task_density_score(all_candidates)
    return round(0.50 * t + 0.30 * s + 0.20 * d, 4)


async def auto_assign_task_id(
    event: dict,
    db: AsyncSession,
) -> tuple[Optional[str], float]:
    """
    Returns (task_id, confidence).
    Returns (None, 0.0) if no candidate or confidence < threshold.
    Returns ("__unassigned__", confidence) if candidates exist but confidence too low.
    """
    cfg = eas_config.task_enforcement
    raw_ts = event.get("timestamp")
    event_ts = _parse_dt(raw_ts) or datetime.utcnow()
    window = timedelta(minutes=cfg.auto_assign_window_minutes)

    result = await db.execute(
        select(Task)
        .where(Task.started_at >= event_ts - window)
        .where(Task.started_at <= event_ts + window)
        .order_by(Task.started_at.desc())
        .limit(20)
    )
    candidates = result.scalars().all()

    if not candidates:
        return None, 0.0

    # Score all candidates
    scored: list[tuple[float, Task]] = []
    for task in candidates:
        conf = await _compute_assignment_confidence(event, task, candidates, event_ts)
        scored.append((conf, task))

    scored.sort(reverse=True)
    best_conf, best_task = scored[0]

    if best_conf < cfg.auto_assign_confidence_min:
        return "__unassigned__", best_conf

    # Check for conflict (top-2 too close)
    if len(scored) >= 2:
        second_conf = scored[1][0]
        if (best_conf - second_conf) < eas_config.correlator.conflict_margin:
            return "__unassigned__", best_conf

    return best_task.id, best_conf


# ── Coverage tracker ──────────────────────────────────────────────────────────

class CoverageMetrics:
    def __init__(self):
        self.reset()

    def record(self, had_task_id: bool, auto_assigned: bool = False,
               unassigned: bool = False, confidence: float = 0.0):
        self._total += 1
        if had_task_id:
            self._with_task_id += 1
        elif auto_assigned:
            self._with_task_id += 1
            self._auto_assigned += 1
            self._confidence_sum += confidence
            self._confidence_count += 1
        elif unassigned:
            self._unassigned += 1
        else:
            self._unmatched += 1

    @property
    def coverage_pct(self) -> float:
        return round(self._with_task_id / self._total * 100, 1) if self._total else 100.0

    @property
    def auto_assignment_accuracy_estimate(self) -> Optional[float]:
        """
        Estimated accuracy: average confidence of auto-assignments.
        High confidence → likely correct. Ground truth requires manual feedback.
        """
        if self._confidence_count == 0:
            return None
        return round(self._confidence_sum / self._confidence_count, 3)

    def to_dict(self) -> dict:
        return {
            "total_events": self._total,
            "with_task_id": self._with_task_id,
            "auto_assigned": self._auto_assigned,
            "unassigned": self._unassigned,
            "unmatched": self._unmatched,
            "coverage_pct": self.coverage_pct,
            "auto_assignment_accuracy_estimate": self.auto_assignment_accuracy_estimate,
            "warning": self.coverage_pct < eas_config.metrics.task_id_coverage_min_pct,
        }

    def reset(self):
        self._total = self._with_task_id = self._auto_assigned = 0
        self._unassigned = self._unmatched = 0
        self._confidence_sum = 0.0
        self._confidence_count = 0


coverage_metrics = CoverageMetrics()


# ── Main enforcement pipeline ─────────────────────────────────────────────────

async def enforce_task_id(
    event_dict: dict,
    db: AsyncSession,
    require_signature: bool = False,
    signature: Optional[str] = None,
    timestamp: Optional[int] = None,
) -> dict:
    """
    Enriches event_dict with task_id (auto-assigned if missing).
    Marks low-confidence assignments as __unassigned__.
    Backward-compatible with v2 callers.
    """
    had_task_id = bool(event_dict.get("task_id"))

    if require_signature:
        if not signature or not timestamp:
            raise ValueError("Missing X-EAS-Signature or X-EAS-Timestamp.")
        if not verify_proxy_signature(event_dict.get("task_id", ""), signature, timestamp):
            raise PermissionError("Invalid or expired EAS proxy signature.")

    if not had_task_id:
        assigned_id, confidence = await auto_assign_task_id(event_dict, db)
        meta = dict(event_dict.get("metadata") or {})

        if assigned_id and assigned_id != "__unassigned__":
            event_dict["task_id"] = assigned_id
            meta["_auto_assigned_task"] = True
            meta["_assignment_confidence"] = confidence
            coverage_metrics.record(had_task_id=False, auto_assigned=True, confidence=confidence)
        else:
            event_dict["task_id"] = None
            meta["_auto_assigned_task"] = False
            meta["_assignment_confidence"] = confidence
            meta["_unassigned"] = True
            coverage_metrics.record(had_task_id=False, unassigned=True, confidence=confidence)

        event_dict["metadata"] = meta
    else:
        coverage_metrics.record(had_task_id=True)

    return event_dict
