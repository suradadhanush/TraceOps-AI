"""
Report Generator

Assembles the full daily execution audit report in JSON and Markdown.
"""
import json
from datetime import date, datetime
from typing import Optional


def _fmt_dt(dt) -> str:
    if dt is None:
        return "N/A"
    if isinstance(dt, (datetime, date)):
        return dt.isoformat()
    return str(dt)


def build_report(
    report_date: date,
    tasks: list[dict],
    scores: list[dict],
    analysis: dict,
    loop_results: list[dict],
    deploy_results: list[dict],
) -> dict:
    """
    Build the full structured report.

    Returns a JSON-serializable dict.
    """
    total_tasks = len(tasks)
    completed = sum(1 for t in tasks if t.get("status") == "completed")
    avg_score = (sum(s["final_score"] for s in scores) / len(scores)) if scores else 0

    report = {
        "meta": {
            "date": report_date.isoformat(),
            "generated_at": datetime.utcnow().isoformat(),
            "version": "1.0",
        },
        "summary": {
            "total_tasks": total_tasks,
            "completed_tasks": completed,
            "average_score": round(avg_score, 1),
            "score_grade": _grade(avg_score),
        },
        "tasks": [
            {
                "id": t.get("id"),
                "goal": t.get("goal"),
                "target_level": t.get("target_level"),
                "final_level": t.get("final_level"),
                "status": t.get("status"),
                "started_at": _fmt_dt(t.get("started_at")),
                "ended_at": _fmt_dt(t.get("ended_at")),
            }
            for t in tasks
        ],
        "scores": scores,
        "loop_detection": loop_results,
        "deployment_validation": deploy_results,
        "analysis": analysis,
    }
    return report


def _grade(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    return "F"


def report_to_markdown(report: dict) -> str:
    """
    Convert a report dict to a readable Markdown audit document.
    """
    meta = report["meta"]
    summary = report["summary"]
    analysis = report.get("analysis", {})

    lines = [
        f"# Execution Audit Report — {meta['date']}",
        f"> Generated: {meta['generated_at']}  |  Version: {meta['version']}",
        "",
        "---",
        "",
        "## Summary",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Tasks | {summary['completed_tasks']}/{summary['total_tasks']} completed |",
        f"| Average Score | {summary['average_score']} / 100 |",
        f"| Grade | **{summary['score_grade']}** |",
        "",
    ]

    # Task table
    lines += ["## Tasks", "", "| ID | Goal | Target | Final | Score | Status |",
              "|----|------|--------|-------|-------|--------|"]
    scores_by_task = {s.get("task_id"): s for s in report.get("scores", [])}
    for t in report.get("tasks", []):
        sc = scores_by_task.get(t["id"], {})
        lines.append(
            f"| `{t['id'][:8]}` | {t['goal'][:40]} | L{t['target_level']} | L{t['final_level']} | "
            f"{sc.get('final_score', 'N/A')} | {t['status']} |"
        )
    lines.append("")

    # Score breakdown
    lines += ["## Score Breakdowns", ""]
    for s in report.get("scores", []):
        lines += [
            f"### Task `{str(s.get('task_id', ''))[:8]}`",
            f"- Outcome: `{s.get('outcome_score', s.get('level', 0) * 10)}`",
            f"- Velocity: `+{s.get('velocity', 0)}`",
            f"- Stability Penalty: `-{s.get('stability_penalty', 0)}`",
            f"- AI Penalty: `-{s.get('ai_penalty', 0)}`",
            f"- **Final: `{s.get('final_score', 0)}`**",
            "",
        ]

    # Loop detection
    loops = report.get("loop_detection", [])
    if loops:
        lines += ["## Loop Detection", ""]
        for lr in loops:
            flag = "⚠️" if lr.get("loop_detected") else "✅"
            lines.append(
                f"{flag} Task `{str(lr.get('task_id', ''))[:8]}` — "
                f"{lr.get('loop_type', 'none')} (severity: {lr.get('severity', 0)})"
            )
        lines.append("")

    # Deployment validation
    deploys = report.get("deployment_validation", [])
    if deploys:
        lines += ["## Deployment Validation", ""]
        for dv in deploys:
            icon = {"success": "✅", "partial": "⚠️", "failed": "❌"}.get(dv.get("status"), "?")
            lines.append(f"{icon} `{dv.get('url', 'N/A')}` — {dv.get('status')} ({dv.get('summary', '')})")
        lines.append("")

    # LLM Analysis
    lines += ["## Analysis", ""]

    bottlenecks = analysis.get("bottlenecks", [])
    if bottlenecks:
        lines += ["### Bottlenecks", ""]
        for i, b in enumerate(bottlenecks[:2], 1):
            lines += [
                f"**{i}. {b.get('title', 'Unnamed')}**",
                f"- Classification: `{b.get('classification')}`",
                f"- Impact: `{b.get('impact')}`",
                f"- Evidence: {b.get('evidence')}",
                "",
            ]

    root_cause = analysis.get("root_cause")
    if root_cause:
        lines += ["### Root Cause", "", root_cause, ""]

    actions = analysis.get("corrective_actions", [])
    if actions:
        lines += ["### Corrective Actions", ""]
        for i, a in enumerate(actions[:3], 1):
            lines.append(f"{i}. **{a.get('action')}** — {a.get('rationale')}")
        lines.append("")

    waste = analysis.get("waste_patterns", [])
    if waste:
        lines += ["### Waste Patterns", ""]
        for w in waste:
            lines.append(f"- {w}")
        lines.append("")

    lines += ["---", "*TraceOps AI v1.0*"]
    return "\n".join(lines)
