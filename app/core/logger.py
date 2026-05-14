"""
Structured Logging Module (Fix 5 — Observability)

JSON-formatted logs for:
- Task lifecycle events
- Correlation decisions (with confidence)
- Scoring outputs
- Webhook ingestion + retry
- Proxy bypass warnings
- Error severity levels

All modules import get_logger() from here.
"""
import json
import logging
import sys
from datetime import datetime
from typing import Any, Optional


class JSONFormatter(logging.Formatter):
    """Emit every log record as a single-line JSON object."""

    SEVERITY_MAP = {
        logging.DEBUG:    "DEBUG",
        logging.INFO:     "INFO",
        logging.WARNING:  "WARNING",
        logging.ERROR:    "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts":       datetime.utcnow().isoformat(),
            "level":    self.SEVERITY_MAP.get(record.levelno, "INFO"),
            "logger":   record.name,
            "msg":      record.getMessage(),
        }
        # Attach structured fields passed via extra={}
        for k, v in record.__dict__.items():
            if k.startswith("traceops_"):
                payload[k[9:]] = v  # strip "traceops_" prefix

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        try:
            return json.dumps(payload, default=str)
        except Exception:
            return json.dumps({"level": "ERROR", "msg": "log serialization failed"})


def configure_logging(level: str = "INFO") -> None:
    """
    Call once at app startup (in main.py lifespan).
    Sets JSON formatter on root logger.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        root.addHandler(handler)

    # Silence noisy third-party loggers
    for name in ("uvicorn.access", "sqlalchemy.engine", "celery.app.trace"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"traceops.{name}")


# ── Domain-specific log helpers ───────────────────────────────────────────────

_task_log  = get_logger("task")
_corr_log  = get_logger("correlation")
_score_log = get_logger("scoring")
_proxy_log = get_logger("proxy")
_wh_log    = get_logger("webhook")


def log_task_start(task_id: str, goal: str, target_level: int):
    _task_log.info("task.start", extra={
        "traceops_task_id": task_id,
        "traceops_goal": goal[:80],
        "traceops_target_level": target_level,
        "traceops_event": "task.start",
    })


def log_task_end(task_id: str, final_level: int, score: int, duration_hours: float):
    _task_log.info("task.end", extra={
        "traceops_task_id": task_id,
        "traceops_final_level": final_level,
        "traceops_score": score,
        "traceops_duration_hours": round(duration_hours, 2),
        "traceops_event": "task.end",
    })


def log_correlation_decision(
    event_id: Any,
    event_type: str,
    assigned_task_id: Optional[str],
    confidence: float,
    method: str,  # "direct_id" | "time_window" | "semantic" | "unmatched"
):
    level = logging.WARNING if assigned_task_id is None else logging.INFO
    _corr_log.log(level, "correlation.decision", extra={
        "traceops_event_id": event_id,
        "traceops_event_type": event_type,
        "traceops_assigned_task": assigned_task_id,
        "traceops_confidence": confidence,
        "traceops_method": method,
        "traceops_event": "correlation.decision",
    })


def log_score_output(
    task_id: str,
    final_score: int,
    level: int,
    velocity: int,
    stability_penalty: int,
    ai_penalty: int,
    loop_detected: bool,
):
    _score_log.info("score.output", extra={
        "traceops_task_id": task_id,
        "traceops_final_score": final_score,
        "traceops_level": level,
        "traceops_velocity": velocity,
        "traceops_stability_penalty": stability_penalty,
        "traceops_ai_penalty": ai_penalty,
        "traceops_loop_detected": loop_detected,
        "traceops_event": "score.output",
    })


def log_proxy_usage(
    task_id: Optional[str],
    provider: str,
    prompt_tokens: Optional[int],
    latency_ms: int,
    has_output: bool,
    suspected_bypass: bool = False,
):
    level = logging.WARNING if suspected_bypass else logging.INFO
    _proxy_log.log(level, "proxy.usage", extra={
        "traceops_task_id": task_id,
        "traceops_provider": provider,
        "traceops_prompt_tokens": prompt_tokens,
        "traceops_latency_ms": latency_ms,
        "traceops_has_output": has_output,
        "traceops_suspected_bypass": suspected_bypass,
        "traceops_event": "proxy.usage",
    })


def log_proxy_bypass_warning(gap_hours: float, direct_usage_estimate: int):
    _proxy_log.warning("proxy.bypass_suspected", extra={
        "traceops_gap_hours": gap_hours,
        "traceops_direct_usage_estimate": direct_usage_estimate,
        "traceops_event": "proxy.bypass_suspected",
    })


def log_webhook_received(source: str, event_type: Optional[str], ikey: str, is_duplicate: bool):
    _wh_log.info("webhook.received", extra={
        "traceops_source": source,
        "traceops_event_type": event_type,
        "traceops_ikey": ikey[:12],
        "traceops_duplicate": is_duplicate,
        "traceops_event": "webhook.received",
    })


def log_webhook_failed(wh_id: int, attempt: int, error: str):
    _wh_log.error("webhook.failed", extra={
        "traceops_webhook_id": wh_id,
        "traceops_attempt": attempt,
        "traceops_error": error[:200],
        "traceops_event": "webhook.failed",
    })
