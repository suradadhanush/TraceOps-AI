"""
Loop Detection Engine v3

Upgrades from v2:
- Context classification: debugging | building | research
  → debugging threshold 0.90, others 0.85
- loop_type_context added to result
- All thresholds sourced from eas_config (no hardcodes)
- Error normalization with fuzzy merge cluster storage
- Backward-compatible detect_all_loops() signature
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from app.core.eas_config import eas_config

_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


@dataclass
class LoopResult:
    loop_detected: bool
    loop_type: Optional[str]           # prompt_loop | error_loop | attempt_loop
    loop_type_context: Optional[str]   # debugging | building | research | None
    severity: float                    # 0.0–1.0
    loop_confidence: float             # confidence that this is a real loop
    evidence: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


# ── Shared ────────────────────────────────────────────────────────────────────

_PATH_RE = re.compile(r'(/[\w./-]+\.py)')
_LINE_RE = re.compile(r', line \d+')
_ADDR_RE = re.compile(r'0x[0-9a-fA-F]+')
_MEMRE   = re.compile(r'at 0x\w+')

# In-process error cluster store: hash → [normalized strings]
_error_clusters: dict[str, list[str]] = {}


def normalize_error(raw: str) -> tuple[str, str]:
    t = _PATH_RE.sub("<path>", raw)
    t = _LINE_RE.sub(", line N", t)
    t = _ADDR_RE.sub("<addr>", t)
    t = _MEMRE.sub("at <addr>", t)
    t = re.sub(r'\s+', ' ', t).strip()
    h = hashlib.sha256(t.encode()).hexdigest()[:16]
    return t, h


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / d) if d > 0 else 0.0


def _embeddings(texts: list[str]) -> np.ndarray:
    return _get_model().encode(texts, convert_to_numpy=True, normalize_embeddings=True)


def _semantic_drift(embs: np.ndarray) -> float:
    """Average step-wise dissimilarity. High = evolving prompts."""
    if len(embs) < 2:
        return 0.0
    return float(np.mean([1.0 - _cosine_similarity(embs[i], embs[i+1]) for i in range(len(embs)-1)]))


# ── Context classifier ────────────────────────────────────────────────────────

def classify_prompt_context(
    prompts: list[str],
    error_logs: list[str],
) -> str:
    """
    Returns: "debugging" | "building" | "research"

    Rules:
    - error_logs present + prompts mention error keywords → debugging
    - prompts contain implementation keywords → building
    - else → research
    """
    debug_keywords = {"error", "exception", "traceback", "bug", "fix", "fail", "crash",
                      "404", "500", "401", "403", "null", "none", "undefined", "keyerror",
                      "valueerror", "typeerror", "attributeerror"}
    build_keywords = {"implement", "build", "create", "add", "write", "function", "class",
                      "endpoint", "api", "model", "schema", "migrate", "deploy", "test"}

    combined_text = " ".join(prompts + error_logs).lower()
    words = set(combined_text.split())

    debug_hits  = len(debug_keywords & words)
    build_hits  = len(build_keywords & words)
    has_errors  = bool(error_logs)

    if has_errors and debug_hits >= 2:
        return "debugging"
    if build_hits >= 3:
        return "building"
    return "research"


def _threshold_for_context(context: str) -> float:
    cfg = eas_config.loop_detection
    if context == "debugging":
        return cfg.similarity_threshold_debugging
    return cfg.similarity_threshold_normal   # building + research use normal


# ── Prompt loop ───────────────────────────────────────────────────────────────

def detect_prompt_loop(
    prompts: list[str],
    output_signals: Optional[list[bool]] = None,
    error_logs: Optional[list[str]] = None,
    debugging_mode: bool = False,   # kept for backward compat; derived from context now
) -> LoopResult:
    cfg      = eas_config.loop_detection
    min_occ  = cfg.min_occurrences
    context  = classify_prompt_context(prompts, error_logs or [])
    threshold = _threshold_for_context(context) if not debugging_mode else cfg.similarity_threshold_debugging

    if len(prompts) < min_occ:
        return LoopResult(False, None, None, 0.0, 0.0)

    embeddings = _embeddings(prompts)
    n = len(embeddings)

    # Segment by output signals
    segments: list[list[int]] = []
    current: list[int] = []
    for i in range(n):
        current.append(i)
        if output_signals and i < len(output_signals) and output_signals[i]:
            if len(current) >= min_occ:
                segments.append(current)
            current = []
    if current:
        segments.append(current)

    loop_segments = []
    for seg in segments:
        if len(seg) < min_occ:
            continue
        seg_emb = embeddings[seg]
        similar_pairs = [
            (seg[a], seg[b], _cosine_similarity(seg_emb[a], seg_emb[b]))
            for a in range(len(seg))
            for b in range(a+1, len(seg))
            if _cosine_similarity(seg_emb[a], seg_emb[b]) >= threshold
        ]
        drift = _semantic_drift(seg_emb)
        if drift > cfg.drift_cancel_threshold:
            continue  # prompts evolving — not a loop
        involved = {i for i, j, _ in similar_pairs} | {j for i, j, _ in similar_pairs}
        if len(involved) >= min_occ:
            loop_segments.append((seg, similar_pairs, drift))

    if not loop_segments:
        return LoopResult(False, None, context, 0.0, 0.0)

    all_pairs = [p for _, pairs, _ in loop_segments for p in pairs]
    avg_sim   = float(np.mean([s for _, _, s in all_pairs])) if all_pairs else 0.0
    severity  = min(1.0, (avg_sim - threshold) / (1.0 - threshold + 1e-9) + 0.3)
    confidence = min(1.0, len(loop_segments) / max(1, len(segments)) + 0.3)

    return LoopResult(
        loop_detected=True,
        loop_type="prompt_loop",
        loop_type_context=context,
        severity=round(severity, 3),
        loop_confidence=round(confidence, 3),
        evidence=[f"Prompt {i}<->Prompt {j}: sim={s:.3f}" for i, j, s in all_pairs[:5]],
        details={
            "context": context,
            "threshold_used": threshold,
            "loop_segments": len(loop_segments),
            "avg_similarity": round(avg_sim, 3),
            "drift_cancel_applied": any(
                _semantic_drift(embeddings[seg]) > cfg.drift_cancel_threshold
                for seg in segments if len(seg) >= min_occ
            ),
        },
    )


# ── Error loop ────────────────────────────────────────────────────────────────

def detect_error_loop(error_logs: list[str]) -> LoopResult:
    cfg     = eas_config.loop_detection
    min_occ = cfg.min_occurrences

    hash_counts: dict[str, list[str]] = {}
    for raw in error_logs:
        norm, h = normalize_error(raw)
        hash_counts.setdefault(h, []).append(norm)
        _error_clusters.setdefault(h, [])
        if norm not in _error_clusters[h]:
            _error_clusters[h].append(norm)

    # Fuzzy merge
    hashes = list(hash_counts.keys())
    if len(hashes) > 1:
        try:
            samples = [hash_counts[h][0] for h in hashes]
            embs = _embeddings(samples)
            canonical: dict[str, str] = {h: h for h in hashes}
            for i in range(len(hashes)):
                for j in range(i+1, len(hashes)):
                    if _cosine_similarity(embs[i], embs[j]) >= cfg.fuzzy_error_threshold:
                        canonical[hashes[j]] = hashes[i]
            merged: dict[str, list[str]] = {}
            for h, msgs in hash_counts.items():
                merged.setdefault(canonical[h], []).extend(msgs)
            hash_counts = merged
        except Exception:
            pass

    loops = {h: msgs for h, msgs in hash_counts.items() if len(msgs) >= min_occ}
    if not loops:
        return LoopResult(False, None, None, 0.0, 0.0)

    max_count  = max(len(v) for v in loops.values())
    severity   = min(1.0, (max_count - min_occ) / (min_occ * 2) + 0.4)
    confidence = min(1.0, len(loops) * 0.4 + 0.3)
    evidence   = [f"Error hash {h[:8]}: {len(msgs)}x — \"{msgs[0][:100]}\"" for h, msgs in list(loops.items())[:5]]

    return LoopResult(
        loop_detected=True,
        loop_type="error_loop",
        loop_type_context="debugging",
        severity=round(severity, 3),
        loop_confidence=round(confidence, 3),
        evidence=evidence,
        details={"loop_groups": len(loops), "max_repetitions": max_count, "clusters": len(_error_clusters)},
    )


# ── Attempt loop ──────────────────────────────────────────────────────────────

def detect_attempt_loop(task_attempts: list[dict]) -> LoopResult:
    cfg     = eas_config.loop_detection
    min_occ = cfg.min_occurrences
    if len(task_attempts) < min_occ:
        return LoopResult(False, None, None, 0.0, 0.0)
    non_success = [a for a in task_attempts if a.get("status") not in ("success", "completed")]
    if len(non_success) < min_occ:
        return LoopResult(False, None, None, 0.0, 0.0)
    severity   = min(1.0, len(non_success) / (min_occ * 2))
    confidence = min(1.0, len(non_success) / (min_occ * 3) + 0.4)
    return LoopResult(
        loop_detected=True, loop_type="attempt_loop", loop_type_context=None,
        severity=round(severity, 3), loop_confidence=round(confidence, 3),
        evidence=[f"{len(non_success)} consecutive failed attempts"],
        details={"failed_attempts": len(non_success), "total_attempts": len(task_attempts)},
    )


# ── Composite ─────────────────────────────────────────────────────────────────

def detect_all_loops(
    prompts: list[str],
    error_logs: list[str],
    task_attempts: list[dict],
    output_signals: Optional[list[bool]] = None,
    debugging_mode: bool = False,
) -> LoopResult:
    results = [
        detect_prompt_loop(prompts, output_signals, error_logs, debugging_mode),
        detect_error_loop(error_logs),
        detect_attempt_loop(task_attempts),
    ]
    detected = [r for r in results if r.loop_detected]
    if not detected:
        return LoopResult(False, None, None, 0.0, 0.0)
    worst = max(detected, key=lambda r: r.severity)
    worst.evidence = [e for r in detected for e in r.evidence]
    return worst


def get_error_clusters() -> dict:
    return {h: {"count": len(msgs), "sample": msgs[0][:100]} for h, msgs in _error_clusters.items()}
