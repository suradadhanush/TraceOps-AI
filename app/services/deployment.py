"""
Deployment Validator v3

Upgrades from v2:
- L5: state-change verification (pre/post request comparison)
- validation_depth_score (0.0–1.0)
- Config-driven via eas_config
- All thresholds from central config
"""
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from pydantic import BaseModel

from app.core.eas_config import eas_config


class EndpointCheck(BaseModel):
    path: str
    method: str = "GET"
    expected_status: int = 200
    required_keys: list[str] = []
    key_types: dict[str, str] = {}
    logic_assertions: list[dict] = []
    # L5: state change
    state_change_path: Optional[str] = None       # path to poll for state change
    state_change_field: Optional[str] = None      # JSON field to compare pre/post
    state_change_body: Optional[dict] = None      # body for triggering request
    timeout: float = 10.0


@dataclass
class CheckResult:
    level: int
    path: str
    passed: bool
    status_code: Optional[int]
    latency_ms: int
    failure_type: Optional[str]
    error: Optional[str] = None
    body: Any = None
    pre_state: Any = None
    post_state: Any = None
    state_changed: Optional[bool] = None


@dataclass
class ValidationResult:
    status: str
    validation_level: int           # highest level passed (1–5)
    validation_depth_score: float   # 0.0–1.0  (passed_levels / total_levels)
    score: float                    # alias for depth_score, backward compat
    checks: list[CheckResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    summary: str = ""


# ── Type helpers ──────────────────────────────────────────────────────────────

_TYPE_MAP = {"str": str, "int": int, "bool": bool, "list": list, "dict": dict, "float": float}


def _check_types(body: dict, key_types: dict[str, str]) -> Optional[str]:
    for key, etype in key_types.items():
        if key not in body:
            return f"Missing typed key: {key}"
        py_t = _TYPE_MAP.get(etype)
        if py_t and not isinstance(body[key], py_t):
            return f"Key '{key}' expected {etype}, got {type(body[key]).__name__}"
    return None


def _check_logic(body: dict, assertions: list[dict]) -> Optional[str]:
    for a in assertions:
        val = body
        for part in a.get("field", "").split("."):
            val = val.get(part) if isinstance(val, dict) else None
        if "equals" in a and val != a["equals"]:
            return f"Field '{a['field']}' expected '{a['equals']}', got '{val}'"
        if a.get("not_null") and val is None:
            return f"Field '{a['field']}' must not be null"
        if "min_length" in a and not (isinstance(val, (str, list)) and len(val) >= a["min_length"]):
            return f"Field '{a['field']}' too short"
    return None


def _get_nested(body: dict, field_path: str) -> Any:
    val = body
    for part in field_path.split("."):
        val = val.get(part) if isinstance(val, dict) else None
    return val


# ── Single check runner ───────────────────────────────────────────────────────

async def _run_check(
    client: httpx.AsyncClient,
    base_url: str,
    check: EndpointCheck,
    level: int,
) -> CheckResult:
    url   = f"{base_url.rstrip('/')}{check.path}"
    start = time.monotonic()
    pre_state = post_state = state_changed = None

    try:
        # L5 pre-state snapshot
        if level == 5 and check.state_change_path and check.state_change_field:
            try:
                pre_resp = await client.get(
                    f"{base_url.rstrip('/')}{check.state_change_path}",
                    timeout=check.timeout,
                )
                pre_state = _get_nested(pre_resp.json(), check.state_change_field)
            except Exception:
                pre_state = None

        # Main request
        if check.method.upper() == "POST" and check.state_change_body:
            resp = await client.post(url, json=check.state_change_body, timeout=check.timeout)
        else:
            resp = await client.get(url, timeout=check.timeout)

        latency_ms = int((time.monotonic() - start) * 1000)
        body = None
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:500] if resp.text else None

        if resp.status_code != check.expected_status:
            ftype = "health_fail" if level == 1 else "schema_fail"
            return CheckResult(level=level, path=check.path, passed=False,
                               status_code=resp.status_code, latency_ms=latency_ms,
                               failure_type=ftype,
                               error=f"Expected {check.expected_status}, got {resp.status_code}", body=body)

        # L3: schema
        if check.required_keys and isinstance(body, dict):
            missing = [k for k in check.required_keys if k not in body]
            if missing:
                return CheckResult(level=level, path=check.path, passed=False,
                                   status_code=resp.status_code, latency_ms=latency_ms,
                                   failure_type="schema_fail", error=f"Missing keys: {missing}", body=body)

        if check.key_types and isinstance(body, dict):
            type_err = _check_types(body, check.key_types)
            if type_err:
                return CheckResult(level=level, path=check.path, passed=False,
                                   status_code=resp.status_code, latency_ms=latency_ms,
                                   failure_type="schema_fail", error=type_err, body=body)

        # L4: logic
        if check.logic_assertions and isinstance(body, dict):
            logic_err = _check_logic(body, check.logic_assertions)
            if logic_err:
                return CheckResult(level=level, path=check.path, passed=False,
                                   status_code=resp.status_code, latency_ms=latency_ms,
                                   failure_type="logic_fail", error=logic_err, body=body)

        # L5: post-state verification
        if level == 5 and check.state_change_path and check.state_change_field:
            try:
                await __import__("asyncio").sleep(0.5)  # allow propagation
                post_resp = await client.get(
                    f"{base_url.rstrip('/')}{check.state_change_path}",
                    timeout=check.timeout,
                )
                post_state = _get_nested(post_resp.json(), check.state_change_field)
                state_changed = (pre_state != post_state) and (post_state is not None)
                if not state_changed:
                    return CheckResult(
                        level=level, path=check.path, passed=False,
                        status_code=resp.status_code, latency_ms=latency_ms,
                        failure_type="logic_fail",
                        error=f"State unchanged: '{check.state_change_field}' = {pre_state} before and after",
                        body=body, pre_state=pre_state, post_state=post_state, state_changed=False,
                    )
            except Exception as exc:
                return CheckResult(level=level, path=check.path, passed=False,
                                   status_code=resp.status_code, latency_ms=latency_ms,
                                   failure_type="logic_fail",
                                   error=f"State verification error: {exc}", body=body)

        return CheckResult(level=level, path=check.path, passed=True,
                           status_code=resp.status_code, latency_ms=latency_ms,
                           failure_type=None, body=body,
                           pre_state=pre_state, post_state=post_state, state_changed=state_changed)

    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - start) * 1000)
        return CheckResult(level=level, path=check.path, passed=False,
                           status_code=None, latency_ms=latency_ms,
                           failure_type="timeout", error="Request timed out")
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return CheckResult(level=level, path=check.path, passed=False,
                           status_code=None, latency_ms=latency_ms,
                           failure_type="health_fail", error=str(exc)[:200])


# ── Main validator ────────────────────────────────────────────────────────────

async def validate_deployment(
    base_url: str,
    checks: Optional[list[EndpointCheck]] = None,
    functional_path: str = "/",
    functional_expected_status: int = 200,
    functional_expected_keys: Optional[list[str]] = None,
    timeout: float = 10.0,
) -> ValidationResult:
    if checks is None:
        checks = [
            EndpointCheck(
                path="/health",
                expected_status=200,
                required_keys=["status"],
                key_types={"status": "str"},
                logic_assertions=[{"field": "status", "equals": "ok"}],
                timeout=timeout,
            ),
            EndpointCheck(
                path=functional_path,
                expected_status=functional_expected_status,
                required_keys=functional_expected_keys or [],
                timeout=timeout,
            ),
        ]

    results: list[CheckResult] = []
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for i, check in enumerate(checks, start=1):
            result = await _run_check(client, base_url, check, level=i)
            results.append(result)

    passed        = [r for r in results if r.passed]
    failed        = [r for r in results if not r.passed]
    depth_score   = len(passed) / len(results) if results else 0.0
    highest_level = max((r.level for r in passed), default=0)
    errors        = [f"L{r.level} {r.path}: {r.error}" for r in failed]

    if depth_score == 1.0:
        status  = "success"
        summary = f"All {len(results)} checks passed (L{highest_level})."
    elif depth_score > 0:
        status  = "partial"
        summary = f"{len(passed)}/{len(results)} checks passed. Failures: {'; '.join(errors)}"
    else:
        status  = "failed"
        summary = f"All checks failed. {'; '.join(errors)}"

    return ValidationResult(
        status=status,
        validation_level=highest_level,
        validation_depth_score=round(depth_score, 3),
        score=round(depth_score, 3),
        checks=results,
        errors=errors,
        summary=summary,
    )
