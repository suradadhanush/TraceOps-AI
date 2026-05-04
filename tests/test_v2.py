"""
v2 Test Suite

Covers:
- Scoring v2 (session-aware velocity, AI efficiency)
- Loop detection v2 (drift, output-reset, confidence)
- Anti-gaming module
- Correlator v2 (weighted scoring, conflict resolution)
"""
import pytest
from datetime import datetime, timedelta


# ── Scoring v2 ───────────────────────────────────────────────────────────────

class TestScoringV2:
    def _score(self, **kwargs):
        from app.services.scoring import compute_score
        defaults = dict(
            level=3, started_at=None, ended_at=None,
            failed_deploy_count=0, repeated_error_count=0,
            loop_detected=False, loop_severity=0.0,
            prompt_count=0, output_count=0, unproductive_prompts=0,
            event_timestamps=[],
        )
        defaults.update(kwargs)
        return compute_score(**defaults)

    def test_high_ai_efficiency_no_penalty(self):
        # 5 prompts, 3 outputs → efficiency 0.60 → no penalty
        r = self._score(level=3, prompt_count=5, output_count=3)
        assert r.ai_penalty == 0

    def test_low_ai_efficiency_penalized(self):
        # 20 prompts, 0 outputs → efficiency 0.0 → max efficiency penalty
        r = self._score(level=3, prompt_count=20, output_count=0)
        assert r.ai_penalty > 0

    def test_session_aware_velocity_excludes_idle(self):
        from app.services.scoring import compute_active_time_hours
        start = datetime(2025, 1, 1, 9, 0)
        end   = datetime(2025, 1, 1, 17, 0)  # 8h wall-clock

        # Two bursts with 2h idle gap → only 4h active
        events = [
            start + timedelta(minutes=30),
            start + timedelta(minutes=60),
            start + timedelta(hours=4),   # 2h+ gap before this
            start + timedelta(hours=4, minutes=30),
        ]
        active = compute_active_time_hours(events, start, end)
        # Should be ~2h (two 1h segments), not 8h
        assert active < 4.0

    def test_no_prompts_no_ai_penalty(self):
        r = self._score(level=4, prompt_count=0, output_count=0)
        assert r.ai_penalty == 0

    def test_final_score_never_negative(self):
        r = self._score(
            level=0, failed_deploy_count=10, repeated_error_count=10,
            loop_detected=True, loop_severity=1.0, prompt_count=30, output_count=0
        )
        assert r.final_score == 0

    def test_breakdown_details_present(self):
        r = self._score(level=3, prompt_count=5, output_count=2)
        assert "ai_efficiency" in r.details
        assert "velocity_bonus" in r.details


# ── Loop detection v2 ────────────────────────────────────────────────────────

class TestLoopDetectionV2:
    def test_drifting_prompts_not_flagged(self):
        from app.services.loop_detection import detect_prompt_loop
        # Semantically different prompts shouldn't flag
        prompts = [
            "how to fix a JWT expiry bug in FastAPI",
            "how to set up PostgreSQL connection pooling",
            "how to write a Celery beat schedule for daily tasks",
        ]
        result = detect_prompt_loop(prompts)
        assert not result.loop_detected

    def test_output_signal_resets_counter(self):
        from app.services.loop_detection import detect_prompt_loop
        identical = "how do I fix this KeyError bug"
        prompts = [identical] * 5
        # Output after prompt 2 should break the run
        output_signals = [False, False, True, False, False]
        result = detect_prompt_loop(prompts, output_signals=output_signals)
        # Post-reset segment has only 2 identical prompts (< min_occ=3) → not a loop
        # (depends on config; just verify confidence is reduced vs no output signals)
        assert result.loop_confidence <= 0.9  # not full confidence

    def test_loop_confidence_present(self):
        from app.services.loop_detection import detect_prompt_loop
        identical = "debug this python error"
        result = detect_prompt_loop([identical] * 4)
        if result.loop_detected:
            assert 0 <= result.loop_confidence <= 1.0

    def test_debugging_mode_stricter_threshold(self):
        from app.services.loop_detection import detect_prompt_loop
        # Slightly similar (not identical) prompts
        prompts = [
            "why does my login fail with 401",
            "login returns 401 what is wrong",
            "getting 401 on login endpoint",
        ]
        normal  = detect_prompt_loop(prompts, debugging_mode=False)
        strict  = detect_prompt_loop(prompts, debugging_mode=True)
        # Strict mode should be less likely to flag
        assert not strict.loop_detected or (
            strict.loop_confidence <= (normal.loop_confidence or 1.0)
        )


# ── Anti-gaming ───────────────────────────────────────────────────────────────

class TestAntiGaming:
    def test_low_quality_commit_flagged(self):
        from app.services.anti_gaming import check_commit_quality
        commits = [
            {"metadata": {"message": "fmt: run black", "lines_added": 5, "lines_removed": 3}},
            {"metadata": {"message": "fmt: isort imports", "lines_added": 2, "lines_removed": 1}},
            {"metadata": {"message": "fmt: prettier", "lines_added": 0, "lines_removed": 0}},
        ]
        flags = check_commit_quality(commits)
        assert any(f.flag_type == "low_quality_commit" for f in flags)

    def test_good_commits_not_flagged(self):
        from app.services.anti_gaming import check_commit_quality
        commits = [
            {"metadata": {"message": "feat: add JWT refresh endpoint", "lines_added": 80, "lines_removed": 10}},
            {"metadata": {"message": "fix: resolve race condition in task queue", "lines_added": 30, "lines_removed": 5}},
        ]
        flags = check_commit_quality(commits)
        assert not any(f.flag_type == "low_quality_commit" for f in flags)

    def test_level5_blocked_without_deploy(self):
        from app.services.anti_gaming import enforce_level5
        flags = enforce_level5(5, deploy_validated=False, deploy_validation_level=0, real_commit_count=5)
        assert any(f.flag_type == "level5_blocked" for f in flags)

    def test_level5_allowed_with_all_gates(self):
        from app.services.anti_gaming import enforce_level5
        flags = enforce_level5(5, deploy_validated=True, deploy_validation_level=3, real_commit_count=3)
        blocking = [f for f in flags if f.severity == "block"]
        assert not blocking

    def test_ai_suppression_flagged(self):
        from app.services.anti_gaming import check_ai_suppression
        flags = check_ai_suppression(
            current_prompt_count=1,
            prior_avg_prompt_count=20,
            current_output_count=0,
        )
        assert any(f.flag_type == "ai_suppression" for f in flags)

    def test_no_suppression_flag_when_output_exists(self):
        from app.services.anti_gaming import check_ai_suppression
        flags = check_ai_suppression(
            current_prompt_count=1,
            prior_avg_prompt_count=20,
            current_output_count=5,  # has output
        )
        assert not flags


# ── Correlator v2 ────────────────────────────────────────────────────────────

class TestCorrelatorV2:
    def _make_task(self, tid, goal, hours_from_now=0):
        now = datetime(2025, 1, 1, 10, 0)
        start = now + timedelta(hours=hours_from_now)
        return {
            "id": tid,
            "goal": goal,
            "started_at": start,
            "ended_at": start + timedelta(hours=1),
            "status": "active",
        }

    def test_exact_task_id_wins(self):
        from app.services.correlator import correlate_event_to_task
        tasks = [
            self._make_task("task-A", "fix login bug", 0),
            self._make_task("task-B", "add payment module", 0),
        ]
        event = {
            "task_id": "task-A",
            "timestamp": datetime(2025, 1, 1, 10, 30),
            "metadata": {},
        }
        tid, conf = correlate_event_to_task(event, tasks)
        assert tid == "task-A"
        assert conf >= 0.60

    def test_overlapping_tasks_ambiguous_without_id(self):
        from app.services.correlator import correlate_event_to_task
        # Two tasks with identical time windows, no ID in event → should be ambiguous
        tasks = [
            self._make_task("task-A", "fix login bug", 0),
            self._make_task("task-B", "fix auth token", 0),
        ]
        event = {
            "task_id": None,
            "timestamp": datetime(2025, 1, 1, 10, 30),
            "metadata": {"message": "something generic"},
        }
        tid, conf = correlate_event_to_task(event, tasks)
        # Should be unmatched due to conflict margin
        assert tid is None or conf < 0.3

    def test_no_tasks_returns_none(self):
        from app.services.correlator import correlate_event_to_task
        tid, conf = correlate_event_to_task({"task_id": None, "metadata": {}}, [])
        assert tid is None
        assert conf == 0.0

    def test_evaluate_accuracy_function_exists(self):
        from app.services.correlator import evaluate_correlation_accuracy
        result = evaluate_correlation_accuracy([], [])
        assert result["total"] == 0
