"""
AI Proxy API

Sits between the developer and OpenAI/Anthropic APIs.
Injects TASK_ID, logs prompt/response, stores in PostgreSQL.

Route:
  POST /proxy/openai    → forwards to OpenAI chat completions
  POST /proxy/anthropic → forwards to Anthropic messages
"""
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import AIProxyLog, Event

router = APIRouter(prefix="/proxy", tags=["AI Proxy"])

OPENAI_BASE = "https://api.openai.com"
ANTHROPIC_BASE = "https://api.anthropic.com"


# ── Request/Response schemas ─────────────────────────────────────────────────

class ProxyRequest(BaseModel):
    task_id: Optional[str] = None
    payload: dict  # raw API payload to forward


# ── Helpers ──────────────────────────────────────────────────────────────────

def _inject_task_id(payload: dict, task_id: Optional[str]) -> dict:
    """Inject [EAS-task_id] into the system or first user message."""
    if not task_id:
        return payload

    tag = f"[EAS-{task_id}]"
    messages = payload.get("messages", [])

    if not messages:
        return payload

    # Inject into system message if present
    for msg in messages:
        if msg.get("role") == "system":
            msg["content"] = f"{tag}\n{msg['content']}"
            return payload

    # Otherwise prepend to first user message
    if isinstance(messages[0].get("content"), str):
        messages[0]["content"] = f"{tag}\n{messages[0]['content']}"
    return payload


def _extract_prompt_text(payload: dict, provider: str) -> str:
    messages = payload.get("messages", [])
    parts = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
            )
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)[:2000]


async def _log_to_db(
    db: AsyncSession,
    task_id: Optional[str],
    provider: str,
    prompt: str,
    response: Optional[str],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    latency_ms: int,
    error: Optional[str] = None,
):
    log = AIProxyLog(
        task_id=task_id,
        provider=provider,
        prompt=prompt,
        response=response,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        error=error,
    )
    db.add(log)

    # Also emit an EAS event
    has_output = bool(response and len(response.strip()) > 10)
    event = Event(
        task_id=task_id,
        event_type="ai",
        source=f"proxy:{provider}",
        raw_data={"prompt_snippet": prompt[:100]},
        metadata_={
            "provider": provider,
            "prompt_snippet": prompt[:100],
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "has_output": has_output,
            "error": error,
        },
    )
    db.add(event)
    await db.commit()


# ── OpenAI Proxy ─────────────────────────────────────────────────────────────

@router.post("/openai")
async def proxy_openai(
    req: ProxyRequest,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
    x_openai_key: Optional[str] = Header(None, alias="X-OpenAI-Key"),
):
    """
    Forward request to OpenAI. Injects TASK_ID, logs response.

    Send your OpenAI API key in:
      - Header: X-OpenAI-Key: sk-...
      - OR Header: Authorization: Bearer sk-...
    """
    from app.core.config import settings

    api_key = x_openai_key
    if not api_key and authorization and authorization.startswith("Bearer "):
        api_key = authorization.split(" ", 1)[1]
    if not api_key:
        api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise HTTPException(status_code=401, detail="No OpenAI API key provided.")

    payload = _inject_task_id(dict(req.payload), req.task_id)
    prompt_text = _extract_prompt_text(payload, "openai")

    start = time.monotonic()
    error_str = None
    resp_text = None
    prompt_tokens = completion_tokens = None

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{OPENAI_BASE}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        latency_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code != 200:
            error_str = resp.text[:500]
            raise HTTPException(status_code=resp.status_code, detail=resp.json())

        data = resp.json()
        resp_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")

        await _log_to_db(db, req.task_id, "openai", prompt_text, resp_text,
                         prompt_tokens, completion_tokens, latency_ms)
        return data

    except HTTPException:
        raise
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        error_str = str(exc)[:300]
        await _log_to_db(db, req.task_id, "openai", prompt_text, None,
                         None, None, latency_ms, error_str)
        raise HTTPException(status_code=502, detail=f"Upstream error: {error_str}")


# ── Anthropic Proxy ───────────────────────────────────────────────────────────

@router.post("/anthropic")
async def proxy_anthropic(
    req: ProxyRequest,
    db: AsyncSession = Depends(get_db),
    x_anthropic_key: Optional[str] = Header(None, alias="X-Anthropic-Key"),
):
    """
    Forward request to Anthropic Messages API. Injects TASK_ID, logs response.

    Send your Anthropic API key in Header: X-Anthropic-Key: sk-ant-...
    """
    from app.core.config import settings

    api_key = x_anthropic_key or settings.ANTHROPIC_API_KEY
    if not api_key:
        raise HTTPException(status_code=401, detail="No Anthropic API key provided.")

    payload = _inject_task_id(dict(req.payload), req.task_id)
    prompt_text = _extract_prompt_text(payload, "anthropic")

    start = time.monotonic()
    error_str = None
    resp_text = None
    prompt_tokens = completion_tokens = None

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{ANTHROPIC_BASE}/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        latency_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code != 200:
            error_str = resp.text[:500]
            raise HTTPException(status_code=resp.status_code, detail=resp.json())

        data = resp.json()
        content_blocks = data.get("content", [])
        resp_text = " ".join(
            b.get("text", "") for b in content_blocks if b.get("type") == "text"
        )
        usage = data.get("usage", {})
        prompt_tokens = usage.get("input_tokens")
        completion_tokens = usage.get("output_tokens")

        await _log_to_db(db, req.task_id, "anthropic", prompt_text, resp_text,
                         prompt_tokens, completion_tokens, latency_ms)
        return data

    except HTTPException:
        raise
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        error_str = str(exc)[:300]
        await _log_to_db(db, req.task_id, "anthropic", prompt_text, None,
                         None, None, latency_ms, error_str)
        raise HTTPException(status_code=502, detail=f"Upstream error: {error_str}")
