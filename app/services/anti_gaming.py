"""
Anti-Gaming Module v3

Upgrades from v2:
- commit_quality_score (0.0–1.0): semantic diff analysis
- Functions/classes added weighted higher than LOC alone
- Level 5 gate uses commit_quality_score threshold from config
- All thresholds from eas_config
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from app.core.eas_config import eas_config


@dataclass
class GamingFlag:
    flag_type: str   # low_quality_commit|signal_mismatch|ai_suppression|level5_blocked
    severity: str    # warn | block
    detail: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class AntiGamingResult:
    clean: bool
    flags: list[GamingFlag] = field(default_factory=list)
    adjusted_level: Optional[int] = None
    commit_quality_score: float = 1.0
    summary: str = ""


# ── Commit quality scoring ────────────────────────────────────────────────────

_FMT_KEYWORDS = {"fmt", "format", "lint", "whitespace", "style", "prettier",
                 "black", "isort", "flake8", "autopep8", "editorconfig"}
_TRIVIAL_KEYWORDS = {"typo", "comment", "readme", "changelog", "todo", "fixme", "wip", "merge"}
# Patterns that signal structural code change
_FUNC_PATTERN  = re.compile(r'\b(def |async def |function |fn |func )\w+', re.I)
_CLASS_PATTERN = re.compile(r'\b(class )\w+', re.I)
_IMPORT_PATTERN = re.compile(r'\b(import |from \w+ import )\w+', re.I)


def _commit_quality_score(commit_meta: dict) -> float:
    """
    Returns 0.0–1.0.

    Scoring:
    - LOC changed:     0–40 pts (normalized at 200 LOC = full)
    - Functions added: +20 pts each (cap 40)
    - Classes added:   +25 pts each (cap 25)
    - Not formatting:  +15 pts
    - Message quality: +10 pts (length > 15 chars, not trivial keyword)

    Normalized to 0.0–1.0 (max raw = 130).
    """
    msg     = (commit_meta.get("message") or "").lower()
    added   = commit_meta.get("lines_added", 0)
    removed = commit_meta.get("lines_removed", 0)
    loc     = added + removed
    diff    = commit_meta.get("diff_text", "")   # optional: raw diff snippet

    score = 0.0

    # LOC score (max 40)
    score += min(40, loc / 200 * 40)

    # Semantic diff analysis
    if diff:
        funcs_added  = len(_FUNC_PATTERN.findall(diff))
        classes_added = len(_CLASS_PATTERN.findall(diff))
        score += min(40, funcs_added * 20)
        score += min(25, classes_added * 25)

    # Not a formatting commit (+15)
    msg_words = set(msg.split())
    is_fmt    = bool(_FMT_KEYWORDS & msg_words)
    if not is_fmt:
        score += 15

    # Message quality (+10): meaningful length, not trivial
    is_trivial = bool(_TRIVIAL_KEYWORDS & msg_words)
    if len(msg) > 15 and not is_trivial:
        score += 10

    return round(min(1.0, score / 130), 3)


def compute_aggregate_commit_quality(commits: list[dict]) -> float:
    """Weighted average commit quality across all commits."""
    if not commits:
        return 0.0
    scores = [_commit_quality_score(c.get("metadata") or {}) for c in commits]
    return round(sum(scores) / len(scores), 3)


def check_commit_quality(commits: list[dict]) -> list[GamingFlag]:
    cfg    = eas_config.anti_gaming
    flags  = []
    if not commits:
        return flags

    low_q  = [c for c in commits if _commit_quality_score(c.get("metadata") or {}) < cfg.commit_quality_min_score]
    ratio  = len(low_q) / len(commits)

    if ratio > 0.7:
        flags.append(GamingFlag(
            flag_type="low_quality_commit",
            severity="warn",
            detail=f"{len(low_q)}/{len(commits)} commits below quality threshold ({ratio:.0%})",
            evidence=[
                f"Score {_commit_quality_score(c.get('metadata') or {}):.2f}: "
                f"'{(c.get('metadata') or {}).get('message', '')[:50]}'"
                for c in low_q[:3]
            ],
        ))
    return flags


def check_signal_consistency(
    commit_count: int,
    deploy_count: int,
    ai_prompt_count: int,
    active_hours: float,
) -> list[GamingFlag]:
    cfg   = eas_config.anti_gaming
    flags = []

    if ai_prompt_count > 5 and commit_count == 0 and deploy_count == 0:
        flags.append(GamingFlag(
            flag_type="signal_mismatch",
            severity="warn",
            detail=f"{ai_prompt_count} AI prompts but zero commits or deploys",
            evidence=[f"AI prompts: {ai_prompt_count}", "Commits: 0", "Deploys: 0"],
        ))

    if active_hours > 0 and commit_count > 0:
        rate = commit_count / active_hours
        if rate > cfg.max_commits_per_hour:
            flags.append(GamingFlag(
                flag_type="signal_mismatch",
                severity="warn",
                detail=f"Commit rate suspiciously high: {rate:.1f}/hr",
                evidence=[f"Commits: {commit_count}", f"Active hours: {active_hours:.1f}"],
            ))
    return flags


def check_ai_suppression(
    current_prompt_count: int,
    prior_avg_prompt_count: float,
    current_output_count: int,
) -> list[GamingFlag]:
    cfg   = eas_config.anti_gaming
    flags = []
    if prior_avg_prompt_count < 1:
        return flags
    drop = 1.0 - (current_prompt_count / prior_avg_prompt_count)
    if drop > cfg.ai_drop_threshold and current_output_count <= cfg.ai_suppression_output_max:
        flags.append(GamingFlag(
            flag_type="ai_suppression",
            severity="warn",
            detail=f"AI usage dropped {drop:.0%} vs baseline with zero output",
            evidence=[
                f"Current prompts: {current_prompt_count}",
                f"Prior avg: {prior_avg_prompt_count:.1f}",
                f"Outputs: {current_output_count}",
            ],
        ))
    return flags


def enforce_level5(
    claimed_level: int,
    deploy_validated: bool,
    deploy_validation_level: int,
    real_commit_count: int,
    commit_quality_score: float = 1.0,
) -> list[GamingFlag]:
    cfg   = eas_config.scoring
    agi   = eas_config.anti_gaming
    flags = []
    if claimed_level < 5:
        return flags

    if not deploy_validated or deploy_validation_level < cfg.level5_deploy_min_level:
        flags.append(GamingFlag(
            flag_type="level5_blocked",
            severity="block",
            detail=f"Level 5 requires deployment validation ≥ L{cfg.level5_deploy_min_level}.",
            evidence=[f"Validation level: {deploy_validation_level}"],
        ))

    if real_commit_count == 0:
        flags.append(GamingFlag(
            flag_type="level5_blocked",
            severity="block",
            detail="Level 5 requires at least one substantive commit.",
            evidence=["No qualifying commits found"],
        ))

    if commit_quality_score < agi.commit_quality_min_score:
        flags.append(GamingFlag(
            flag_type="level5_blocked",
            severity="block",
            detail=f"Commit quality score {commit_quality_score:.2f} below threshold {agi.commit_quality_min_score}.",
            evidence=[f"Quality score: {commit_quality_score:.2f}"],
        ))

    return flags


def run_anti_gaming_check(
    claimed_level: int,
    commits: list[dict],
    deploy_events: list[dict],
    ai_events: list[dict],
    active_hours: float,
    deploy_validated: bool = False,
    deploy_validation_level: int = 0,
    prior_avg_prompts: float = 0.0,
) -> AntiGamingResult:
    cfg   = eas_config.anti_gaming
    flags: list[GamingFlag] = []

    cq_score = compute_aggregate_commit_quality(commits)
    flags.extend(check_commit_quality(commits))

    # Real commits: quality above threshold
    real_commits = [
        c for c in commits
        if _commit_quality_score(c.get("metadata") or {}) >= cfg.commit_quality_min_score
    ]

    flags.extend(enforce_level5(
        claimed_level, deploy_validated, deploy_validation_level,
        len(real_commits), cq_score,
    ))

    flags.extend(check_signal_consistency(
        len(commits), len(deploy_events), len(ai_events), active_hours
    ))

    output_count = len(real_commits) + sum(
        1 for d in deploy_events
        if (d.get("metadata") or {}).get("status") == "success"
    )
    if prior_avg_prompts > 0:
        flags.extend(check_ai_suppression(len(ai_events), prior_avg_prompts, output_count))

    blocking       = [f for f in flags if f.severity == "block"]
    adjusted_level = claimed_level
    if blocking and claimed_level == 5:
        adjusted_level = 4

    return AntiGamingResult(
        clean=len(flags) == 0,
        flags=flags,
        adjusted_level=adjusted_level,
        commit_quality_score=cq_score,
        summary="; ".join(f.detail for f in flags) or "No gaming flags.",
    )
