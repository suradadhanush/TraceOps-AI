"""
Scoring Engine v3

Upgrades from v2:
- AI efficiency: rate-based (prompts_per_hour / outputs_per_hour) not just ratio
- Long prompt chain penalty: >20 min AI chain with no output
- Continuity ratio: velocity = base_velocity * continuity
- All thresholds from eas_config
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.core.eas_config import eas_config


@dataclass
class ScoreBreakdown:
    outcome_score: int
    velocity: int
    stability_penalty: int
    ai_penalty: int
    final_score: int
    level: int
    details: dict


# ── Session / active time ─────────────────────────────────────────────────────

def compute_active_time_hours(
    event_timestamps: list[datetime],
    started_at: Optional[datetime],
    ended_at: Optional[datetime],
) -> float:
    if not started_at or not ended_at:
        return 0.0
    anchors = sorted(set(
        [started_at]
        + [ts for ts in event_timestamps if started_at <= ts <= ended_at]
        + [ended_at]
    ))
    idle_threshold = timedelta(minutes=eas_config.scoring.idle_gap_minutes)
    active_seconds = sum(
        (anchors[i+1] - anchors[i]).total_seconds()
        for i in range(len(anchors)-1)
        if (anchors[i+1] - anchors[i]) <= idle_threshold
    )
    return active_seconds / 3600


def compute_continuity_ratio(
    event_timestamps: list[datetime],
    started_at: Optional[datetime],
    ended_at: Optional[datetime],
) -> float:
    """
    continuity = active_time / session_span
    session_span = wall-clock from first to last event (or start→end)
    Returns 0.0–1.0.
    """
    if not started_at or not ended_at:
        return 1.0
    active = compute_active_time_hours(event_timestamps, started_at, ended_at)
    span = (ended_at - started_at).total_seconds() / 3600
    if span <= 0:
        return 1.0
    return min(1.0, round(active / span, 4))


# ── Velocity v3 ───────────────────────────────────────────────────────────────

def compute_velocity(
    event_timestamps: list[datetime],
    started_at: Optional[datetime],
    ended_at: Optional[datetime],
) -> int:
    """
    base_velocity from active hours × continuity_ratio.
    """
    cfg = eas_config.scoring
    active_hours = compute_active_time_hours(event_timestamps, started_at, ended_at)
    if active_hours == 0 and started_at and ended_at:
        active_hours = (ended_at - started_at).total_seconds() / 3600

    if active_hours < cfg.velocity_fast_hours:
        base = cfg.velocity_fast_bonus
    elif active_hours <= cfg.velocity_med_hours:
        base = cfg.velocity_med_bonus
    else:
        base = 0

    if base == 0:
        return 0

    continuity = compute_continuity_ratio(event_timestamps, started_at, ended_at)
    return max(0, round(base * continuity))


# ── AI efficiency v3 ──────────────────────────────────────────────────────────

def compute_ai_efficiency(
    prompt_count: int,
    output_count: int,
    active_hours: float,
    ai_event_timestamps: Optional[list[datetime]] = None,
) -> tuple[int, dict]:
    """
    Rate-based efficiency:
      prompts_per_hour = prompt_count / active_hours
      outputs_per_hour = output_count / active_hours
      efficiency       = outputs_per_hour / prompts_per_hour  (if prompts > 0)

    Long chain penalty: consecutive AI events > chain_no_output_minutes with no output.

    Returns (penalty_points, details_dict).
    """
    cfg = eas_config.scoring

    if active_hours <= 0:
        active_hours = 1.0  # prevent division by zero

    prompts_per_hour = prompt_count / active_hours
    outputs_per_hour = output_count / active_hours

    # Rate-based efficiency
    if prompts_per_hour > 0:
        efficiency = outputs_per_hour / prompts_per_hour
    else:
        efficiency = 1.0

    if efficiency >= cfg.ai_efficiency_high:
        efficiency_penalty = 0
    elif efficiency >= cfg.ai_efficiency_med:
        efficiency_penalty = cfg.ai_efficiency_penalty_mild
    else:
        efficiency_penalty = cfg.ai_efficiency_penalty_strong

    # Long chain penalty: consecutive AI prompts with no output > threshold
    chain_penalty = 0
    if ai_event_timestamps and len(ai_event_timestamps) >= 2:
        chain_limit = timedelta(minutes=cfg.chain_no_output_minutes)
        sorted_ts = sorted(ai_event_timestamps)
        chain_start = sorted_ts[0]
        for i in range(1, len(sorted_ts)):
            gap = sorted_ts[i] - sorted_ts[i-1]
            if gap > timedelta(minutes=cfg.idle_gap_minutes):
                chain_start = sorted_ts[i]  # reset chain after idle
            elif (sorted_ts[i] - chain_start) > chain_limit:
                chain_penalty = cfg.ai_chain_penalty
                break  # one penalty per task is enough

    total_penalty = min(efficiency_penalty + chain_penalty, cfg.max_loop_penalty)

    return total_penalty, {
        "prompts_per_hour": round(prompts_per_hour, 3),
        "outputs_per_hour": round(outputs_per_hour, 3),
        "efficiency_ratio": round(efficiency, 3),
        "efficiency_penalty": efficiency_penalty,
        "chain_penalty": chain_penalty,
        "total_ai_penalty": total_penalty,
    }


# ── Stability ─────────────────────────────────────────────────────────────────

def compute_stability_penalty(failed_deploy_count: int, repeated_error_count: int) -> int:
    cfg = eas_config.scoring
    penalty = (failed_deploy_count * cfg.failed_deploy_penalty) + (repeated_error_count * cfg.repeated_error_penalty)
    return min(penalty, cfg.max_stability_penalty)


# ── Master score function ─────────────────────────────────────────────────────

def compute_score(
    level: int,
    started_at: Optional[datetime],
    ended_at: Optional[datetime],
    failed_deploy_count: int = 0,
    repeated_error_count: int = 0,
    loop_detected: bool = False,
    loop_severity: float = 0.0,
    prompt_count: int = 0,
    output_count: int = 0,
    unproductive_prompts: int = 0,
    event_timestamps: Optional[list[datetime]] = None,
    ai_event_timestamps: Optional[list[datetime]] = None,
) -> ScoreBreakdown:
    if not 0 <= level <= 5:
        raise ValueError(f"Level must be 0-5, got {level}")

    cfg = eas_config.scoring
    ts  = event_timestamps or []

    outcome_score     = level * 10
    velocity          = compute_velocity(ts, started_at, ended_at)
    stability_penalty = compute_stability_penalty(failed_deploy_count, repeated_error_count)
    continuity        = compute_continuity_ratio(ts, started_at, ended_at)
    active_hours      = compute_active_time_hours(ts, started_at, ended_at) or \
                        ((ended_at - started_at).total_seconds() / 3600 if started_at and ended_at else 1.0)

    ai_penalty, ai_details = compute_ai_efficiency(prompt_count, output_count, active_hours, ai_event_timestamps)

    # Add loop penalty on top
    if loop_detected:
        loop_pts = max(cfg.loop_base_penalty, int(loop_severity * 15))
        ai_penalty = min(ai_penalty + loop_pts, cfg.max_loop_penalty)

    raw          = outcome_score + velocity - stability_penalty - ai_penalty
    final_score  = max(0, min(100, raw))

    return ScoreBreakdown(
        outcome_score=outcome_score,
        velocity=velocity,
        stability_penalty=stability_penalty,
        ai_penalty=ai_penalty,
        final_score=final_score,
        level=level,
        details={
            "outcome_score": outcome_score,
            "velocity_bonus": velocity,
            "continuity_ratio": continuity,
            "stability_penalty": stability_penalty,
            "ai_penalty": ai_penalty,
            **ai_details,
            "raw_score": raw,
            "final_score": final_score,
            "inputs": {
                "level": level,
                "failed_deploys": failed_deploy_count,
                "repeated_errors": repeated_error_count,
                "loop_detected": loop_detected,
                "loop_severity": loop_severity,
                "prompt_count": prompt_count,
                "output_count": output_count,
            },
        },
    )


def score_from_task_data(task_data: dict, events: list[dict]) -> ScoreBreakdown:
    started_at  = task_data.get("started_at")
    ended_at    = task_data.get("ended_at")
    final_level = task_data.get("final_level", 0)

    def _parse(ts):
        if isinstance(ts, datetime): return ts
        try: return datetime.fromisoformat(str(ts))
        except: return None

    all_ts     = [_parse(e.get("timestamp")) for e in events]
    all_ts     = [t for t in all_ts if t]
    ai_events  = [e for e in events if e["event_type"] == "ai"]
    ai_ts      = [_parse(e.get("timestamp")) for e in ai_events]
    ai_ts      = [t for t in ai_ts if t]

    deploy_events  = [e for e in events if e["event_type"] == "deploy"]
    failed_deploys = sum(1 for e in deploy_events if e.get("metadata", {}).get("status") in ("failed", "error"))
    error_events   = [e for e in events if e["event_type"] == "error"]
    error_hashes: dict[str, int] = {}
    for e in error_events:
        h = e.get("metadata", {}).get("error_hash", "")
        if h: error_hashes[h] = error_hashes.get(h, 0) + 1
    repeated_errors = sum(1 for c in error_hashes.values() if c > 1)

    prompt_count   = len(ai_events)
    unproductive   = sum(1 for e in ai_events if not e.get("metadata", {}).get("has_output", True))
    commit_events  = [e for e in events if e["event_type"] == "commit"]
    deploy_success = sum(1 for e in deploy_events if e.get("metadata", {}).get("status") == "success")
    output_count   = len(commit_events) + deploy_success

    return compute_score(
        level=final_level,
        started_at=started_at,
        ended_at=ended_at,
        failed_deploy_count=failed_deploys,
        repeated_error_count=repeated_errors,
        loop_detected=task_data.get("loop_detected", False),
        loop_severity=task_data.get("loop_severity", 0.0),
        prompt_count=prompt_count,
        output_count=output_count,
        unproductive_prompts=unproductive,
        event_timestamps=all_ts,
        ai_event_timestamps=ai_ts,
    )
