"""
Event Normalizer

Converts heterogeneous inputs (GitHub webhooks, AI proxy logs, deploy events)
into the unified TraceOps event schema.
"""
from datetime import datetime
from typing import Any, Optional


UNIFIED_SCHEMA_KEYS = {"task_id", "event_type", "timestamp", "source", "metadata"}

VALID_EVENT_TYPES = {"commit", "deploy", "ai", "error", "pr", "review"}


def _parse_ts(ts: Any) -> str:
    """Coerce various timestamp formats to ISO 8601."""
    if isinstance(ts, datetime):
        return ts.isoformat()
    if isinstance(ts, (int, float)):
        return datetime.utcfromtimestamp(ts).isoformat()
    if isinstance(ts, str):
        return ts  # assume already ISO; caller validates
    return datetime.utcnow().isoformat()


def normalize_github_commit(payload: dict, task_id: Optional[str] = None) -> dict:
    """
    Normalize a GitHub push/commit webhook payload.
    """
    commits = payload.get("commits", [])
    normalized = []
    for commit in commits:
        task = task_id
        # Try to extract TASK_ID from commit message: e.g. [TRO-abc123]
        msg = commit.get("message", "")
        import re
        match = re.search(r'\[TRO-([A-Za-z0-9-]+)\]', msg)
        if match:
            task = match.group(1)

        normalized.append({
            "task_id": task,
            "event_type": "commit",
            "timestamp": _parse_ts(commit.get("timestamp")),
            "source": "github",
            "metadata": {
                "sha": commit.get("id", "")[:12],
                "message": msg[:200],
                "author": commit.get("author", {}).get("name"),
                "url": commit.get("url"),
                "added": len(commit.get("added", [])),
                "modified": len(commit.get("modified", [])),
                "removed": len(commit.get("removed", [])),
            },
        })
    return normalized


def normalize_deploy_event(payload: dict, task_id: Optional[str] = None) -> dict:
    """
    Normalize a deploy log entry (Render, Vercel, or custom).
    """
    status = payload.get("status", "unknown")
    return {
        "task_id": task_id or payload.get("task_id"),
        "event_type": "deploy",
        "timestamp": _parse_ts(payload.get("timestamp") or payload.get("created_at")),
        "source": payload.get("platform", "deploy"),
        "metadata": {
            "service": payload.get("service") or payload.get("name"),
            "status": status,
            "url": payload.get("url"),
            "commit_sha": payload.get("commit", {}).get("sha", payload.get("commit_sha", ""))[:12],
            "duration_ms": payload.get("duration_ms"),
            "error": payload.get("error"),
        },
    }


def normalize_ai_event(payload: dict) -> dict:
    """
    Normalize an AI proxy log entry.
    """
    prompt = payload.get("prompt", "")
    response = payload.get("response", "")
    has_output = bool(response and len(response.strip()) > 10)

    return {
        "task_id": payload.get("task_id"),
        "event_type": "ai",
        "timestamp": _parse_ts(payload.get("timestamp")),
        "source": f"proxy:{payload.get('provider', 'unknown')}",
        "metadata": {
            "provider": payload.get("provider"),
            "prompt_snippet": prompt[:100],
            "prompt_tokens": payload.get("prompt_tokens"),
            "completion_tokens": payload.get("completion_tokens"),
            "latency_ms": payload.get("latency_ms"),
            "has_output": has_output,
            "error": payload.get("error"),
        },
    }


def normalize_error_event(payload: dict, task_id: Optional[str] = None) -> dict:
    """
    Normalize an error log entry with hash.
    """
    from app.services.loop_detection import normalize_error
    raw = payload.get("raw", payload.get("message", ""))
    normalized_str, error_hash = normalize_error(raw)

    return {
        "task_id": task_id or payload.get("task_id"),
        "event_type": "error",
        "timestamp": _parse_ts(payload.get("timestamp")),
        "source": payload.get("source", "app"),
        "metadata": {
            "error_type": payload.get("error_type", "unknown"),
            "message": normalized_str[:300],
            "error_hash": error_hash,
            "stack_frame": payload.get("stack_frame"),
        },
    }


def normalize_event(raw_event: dict) -> dict:
    """
    Auto-dispatch to the correct normalizer based on event_type or source.
    Falls back to a passthrough that enforces the unified schema.
    """
    etype = raw_event.get("event_type", "").lower()
    source = raw_event.get("source", "").lower()

    if etype == "commit" or source == "github":
        if "commits" in raw_event:
            return normalize_github_commit(raw_event)
        return normalize_github_commit({"commits": [raw_event]}, raw_event.get("task_id"))[0]

    if etype == "deploy":
        return normalize_deploy_event(raw_event)

    if etype == "ai" or "proxy" in source:
        return normalize_ai_event(raw_event)

    if etype == "error":
        return normalize_error_event(raw_event)

    # Passthrough — ensure minimal schema
    return {
        "task_id": raw_event.get("task_id"),
        "event_type": raw_event.get("event_type", "unknown"),
        "timestamp": _parse_ts(raw_event.get("timestamp")),
        "source": raw_event.get("source", "unknown"),
        "metadata": raw_event.get("metadata", {}),
    }
