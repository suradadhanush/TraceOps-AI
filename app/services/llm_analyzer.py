"""
LLM Analyzer

Sends scored execution data to an LLM and returns structured analysis:
- Top 2 bottlenecks
- Classification (planning/execution/loop/tool_misuse)
- Root cause
- 3 corrective actions
"""
import json
from typing import Optional

from app.core.config import settings

ANALYSIS_SYSTEM_PROMPT = """You are a strict execution auditor. You receive developer execution data and must produce an honest, evidence-tied audit.

Rules:
- No generic advice. Every claim must be tied to data provided.
- Be critical. Surface what actually failed, not what might have.
- Classify failures precisely: planning_failure | execution_failure | loop | tool_misuse
- Corrective actions must be specific and immediately actionable.

Respond ONLY with valid JSON matching this schema:
{
  "bottlenecks": [
    {
      "title": "string",
      "classification": "planning_failure|execution_failure|loop|tool_misuse",
      "evidence": "string (cite specific data)",
      "impact": "high|medium|low"
    }
  ],
  "waste_patterns": ["string"],
  "root_cause": "string (single paragraph, evidence-based)",
  "corrective_actions": [
    {
      "action": "string",
      "rationale": "string"
    }
  ],
  "score_accuracy_note": "string (optional: flag any scoring anomalies)"
}"""


def _build_user_prompt(task_data: dict, events: list[dict], score: dict) -> str:
    event_summary = _summarize_events(events)
    return f"""## Task
Goal: {task_data.get('goal', 'N/A')}
Target Level: {task_data.get('target_level')}
Final Level: {task_data.get('final_level')}
Duration: {task_data.get('started_at')} → {task_data.get('ended_at')}

## Score Breakdown
{json.dumps(score, indent=2)}

## Event Summary
{event_summary}

Produce a strict audit. No padding. Tie every claim to the data above."""


def _summarize_events(events: list[dict]) -> str:
    counts: dict[str, int] = {}
    for e in events:
        t = e.get("event_type", "unknown")
        counts[t] = counts.get(t, 0) + 1

    lines = [f"Total events: {len(events)}"]
    for etype, count in sorted(counts.items()):
        lines.append(f"  {etype}: {count}")

    # Surface failures
    failures = [e for e in events if e.get("metadata", {}).get("status") in ("failed", "error")]
    if failures:
        lines.append(f"Failed deploys/errors: {len(failures)}")

    ai_events = [e for e in events if e.get("event_type") == "ai"]
    unproductive = [e for e in ai_events if not e.get("metadata", {}).get("has_output", True)]
    if unproductive:
        lines.append(f"Unproductive AI prompts: {len(unproductive)}")

    return "\n".join(lines)


async def analyze_with_openai(
    task_data: dict,
    events: list[dict],
    score: dict,
) -> dict:
    import openai
    client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    resp = await client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(task_data, events, score)},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content
    return json.loads(raw)


async def analyze_with_anthropic(
    task_data: dict,
    events: list[dict],
    score: dict,
) -> dict:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    resp = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": _build_user_prompt(task_data, events, score)},
        ],
    )
    raw = resp.content[0].text
    # Strip markdown fences if any
    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(raw)


async def run_analysis(
    task_data: dict,
    events: list[dict],
    score: dict,
) -> dict:
    """
    Run LLM bottleneck analysis using configured provider.
    Returns structured analysis dict.
    """
    provider = settings.LLM_PROVIDER.lower()
    try:
        if provider == "anthropic":
            return await analyze_with_anthropic(task_data, events, score)
        return await analyze_with_openai(task_data, events, score)
    except Exception as exc:
        # Graceful fallback — return a stub so the report still generates
        return {
            "bottlenecks": [],
            "waste_patterns": [],
            "root_cause": f"LLM analysis unavailable: {str(exc)[:200]}",
            "corrective_actions": [],
            "score_accuracy_note": "Analysis skipped due to LLM error.",
        }
