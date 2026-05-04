"""
Correlation Engine v3

Upgrades from v2:
- Delayed resolution queue: unresolved events retried on new commit/deploy
- Timeout fallback: after 2h assign to lowest-confidence cluster
- Per-event confidence score stored in metadata
- evaluate_correlation_accuracy() for synthetic validation
"""
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from app.core.eas_config import eas_config

# ── Delayed resolution queue (in-process; swap for Redis in multi-worker) ────
_unresolved_queue: list[dict] = []   # {"event": dict, "queued_at": datetime, "candidates": list}


def _parse_dt(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


def _time_score(event_ts: datetime, task: dict, window_min: int) -> float:
    started = _parse_dt(task.get("started_at"))
    ended   = _parse_dt(task.get("ended_at")) or datetime.utcnow()
    if not started:
        return 0.0
    if started <= event_ts <= ended:
        return 1.0
    delta = (started - event_ts).total_seconds() if event_ts < started else (event_ts - ended).total_seconds()
    max_d = window_min * 60
    return max(0.0, round(1.0 - delta / max_d, 4)) if delta < max_d else 0.0


def _semantic_score(event_text: str, goal: str) -> float:
    if not event_text.strip() or not goal.strip():
        return 0.0
    try:
        from app.services.loop_detection import _get_model, _cosine_similarity
        emb = _get_model().encode([event_text, goal], normalize_embeddings=True)
        return float(_cosine_similarity(emb[0], emb[1]))
    except Exception:
        return 0.0


def _event_text(event: dict) -> str:
    meta = event.get("metadata") or event.get("metadata_") or {}
    return " ".join(
        str(v) for k, v in meta.items()
        if k in ("message", "prompt_snippet", "description", "goal") and isinstance(v, str)
    )[:300]


def _score_candidates(event: dict, tasks: list[dict]) -> list[tuple[float, str]]:
    """Return sorted list of (composite_score, task_id) for all candidates."""
    cfg = eas_config.correlator
    event_tid  = event.get("task_id")
    event_ts   = _parse_dt(event.get("timestamp")) or datetime.utcnow()
    event_text = _event_text(event)

    scored = []
    for task in tasks:
        tid = task.get("id") or task.get("task_id")
        if not tid:
            continue
        id_score  = 1.0 if (event_tid and event_tid == tid) else 0.0
        t_score   = _time_score(event_ts, task, cfg.time_window_minutes)
        sem_score = _semantic_score(event_text, task.get("goal", "")) if id_score == 0.0 else 0.0
        composite = cfg.weight_task_id * id_score + cfg.weight_time * t_score + cfg.weight_semantic * sem_score
        scored.append((composite, tid))

    scored.sort(reverse=True)
    return scored


def correlate_event_to_task(
    event: dict,
    tasks: list[dict],
) -> tuple[Optional[str], float]:
    """
    Returns (task_id, confidence) or (None, 0.0) if unmatched/ambiguous.
    Ambiguous events are added to delayed resolution queue.
    """
    cfg = eas_config.correlator
    if not tasks:
        return None, 0.0

    scored = _score_candidates(event, tasks)
    if not scored:
        return None, 0.0

    best_score, best_id = scored[0]

    if best_score < cfg.min_confidence:
        return None, 0.0

    # Conflict check
    if len(scored) >= 2 and (best_score - scored[1][0]) < cfg.conflict_margin:
        # Only resolve via exact ID
        event_tid = event.get("task_id")
        if event_tid and best_id == event_tid:
            return best_id, round(best_score, 4)
        # Queue for delayed resolution
        _queue_unresolved(event, tasks)
        return None, 0.0

    return best_id, round(best_score, 4)


def _queue_unresolved(event: dict, tasks: list[dict]):
    """Add event to delayed resolution queue."""
    _unresolved_queue.append({
        "event": event,
        "tasks": tasks,
        "queued_at": datetime.utcnow(),
    })


def resolve_unresolved_queue(
    new_events: Optional[list[dict]] = None,
    force_timeout: bool = False,
) -> list[tuple[dict, Optional[str], float]]:
    """
    Attempt to resolve queued events.

    Triggers:
    - new_events contains a commit or deploy → retry all queued
    - force_timeout=True → assign lowest-confidence cluster after 2h

    Returns list of (event, resolved_task_id, confidence).
    """
    cfg = eas_config.correlator
    timeout = timedelta(hours=cfg.unresolved_timeout_hours)
    now = datetime.utcnow()

    # Check if new commit/deploy arrived
    has_trigger = False
    if cfg.retry_on_new_event and new_events:
        trigger_types = {"commit", "deploy"}
        has_trigger = any(e.get("event_type") in trigger_types for e in new_events)

    resolved: list[tuple[dict, Optional[str], float]] = []
    remaining: list[dict] = []

    for item in _unresolved_queue:
        event   = item["event"]
        tasks   = item["tasks"]
        queued  = item["queued_at"]
        age     = now - queued

        should_retry = has_trigger or (force_timeout and age >= timeout)

        if not should_retry:
            remaining.append(item)
            continue

        scored = _score_candidates(event, tasks)
        if not scored:
            resolved.append((event, None, 0.0))
            continue

        if force_timeout and age >= timeout:
            # Assign to lowest-confidence cluster (best available even if ambiguous)
            best_score, best_id = scored[0]
            resolved.append((event, best_id, round(best_score, 4)))
        else:
            # Retry normal resolution
            cfg2 = eas_config.correlator
            best_score, best_id = scored[0]
            if len(scored) >= 2 and (best_score - scored[1][0]) < cfg2.conflict_margin:
                remaining.append(item)  # still ambiguous
            elif best_score >= cfg2.min_confidence:
                resolved.append((event, best_id, round(best_score, 4)))
            else:
                resolved.append((event, None, 0.0))

    _unresolved_queue.clear()
    _unresolved_queue.extend(remaining)

    return resolved


def group_events_by_task(
    events: list[dict],
    tasks: list[dict],
) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {t["id"]: [] for t in tasks}
    grouped["__unmatched__"] = []
    grouped["__ambiguous__"] = []

    for event in events:
        tid, conf = correlate_event_to_task(event, tasks)
        enriched = dict(event)
        meta = dict(enriched.get("metadata") or {})
        meta["_correlation_confidence"] = conf
        enriched["metadata"] = meta

        if tid and tid in grouped:
            grouped[tid].append(enriched)
        elif conf == 0.0:
            grouped["__ambiguous__"].append(enriched)
        else:
            grouped["__unmatched__"].append(enriched)

    return grouped


def evaluate_correlation_accuracy(
    events_with_ground_truth: list[dict],
    tasks: list[dict],
) -> dict:
    """
    Synthetic validation. Events must have _ground_truth_task_id key.
    """
    total = len(events_with_ground_truth)
    if not total:
        return {"accuracy": None, "total": 0}
    correct = wrong = unmatched = 0
    for ev in events_with_ground_truth:
        truth = ev.get("_ground_truth_task_id")
        pred, _ = correlate_event_to_task(ev, tasks)
        if pred == truth:
            correct += 1
        elif pred is None and truth is not None:
            unmatched += 1
        else:
            wrong += 1
    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "unmatched": unmatched,
        "accuracy_pct": round(correct / total * 100, 1),
        "meets_threshold": (correct / total) >= eas_config.metrics.correlation_accuracy_min_pct / 100,
        "unresolved_queue_size": len(_unresolved_queue),
    }


def queue_stats() -> dict:
    return {
        "unresolved_count": len(_unresolved_queue),
        "oldest_queued_at": min(
            (i["queued_at"].isoformat() for i in _unresolved_queue), default=None
        ),
    }
