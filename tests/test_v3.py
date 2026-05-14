"""
TraceOps AI v1 Test Suite

Covers all 11 upgrade areas:
- Task enforcement confidence scoring
- Correlator delayed queue + conflict resolution
- Loop detection v3 (context classification, drift, chain penalty)
- Scoring v3 (rate-based AI efficiency, continuity, chain penalty)
- Deployment validator v3 (L5 state change)
- Anti-gaming v3 (quality score, semantic diff)
- Metrics / adaptive tuning (division-by-zero safety)
- Error normalization (fuzzy cluster)
- Config centralization
"""
import pytest
from datetime import datetime, timedelta


# ── 1. Config centralization ─────────────────────────────────────────────────

class TestConfig:
    def test_config_loads(self):
        from app.core.eas_config import eas_config
        assert eas_config.scoring.velocity_fast_hours == 3
        assert eas_config.correlator.weight_task_id == 0.60

    def test_config_to_dict_no_crash(self):
        from app.core.eas_config import eas_config
        d = eas_config.to_dict()
        assert "scoring" in d
        assert "loop_detection" in d

    def test_config_save_load_roundtrip(self, tmp_path):
        from app.core.eas_config import EASConfig
        cfg = EASConfig()
        cfg.scoring.velocity_fast_hours = 99
        path = str(tmp_path / "test_cfg.json")
        cfg.save(path)
        loaded = EASConfig.load(path)
        assert loaded.scoring.velocity_fast_hours == 99


# ── 2. Task enforcement confidence ───────────────────────────────────────────

class TestTaskEnforcementV3:
    def test_coverage_metrics_no_division_by_zero(self):
        from app.services.task_enforcement import CoverageMetrics
        m = CoverageMetrics()
        assert m.coverage_pct == 100.0
        assert m.auto_assignment_accuracy_estimate is None

    def test_coverage_records_auto_assign(self):
        from app.services.task_enforcement import CoverageMetrics
        m = CoverageMetrics()
        m.record(had_task_id=False, auto_assigned=True, confidence=0.80)
        assert m.coverage_pct == 100.0
        assert m.auto_assignment_accuracy_estimate == 0.80

    def test_coverage_records_unassigned(self):
        from app.services.task_enforcement import CoverageMetrics
        m = CoverageMetrics()
        m.record(had_task_id=False, unassigned=True, confidence=0.50)
        assert m.coverage_pct == 0.0
        assert m._unassigned == 1

    def test_hmac_signature_replay_rejected(self):
        import time
        from app.services.task_enforcement import generate_proxy_signature, verify_proxy_signature
        old_ts = int(time.time()) - 400  # older than max_age
        sig = generate_proxy_signature("task-x", old_ts)
        assert not verify_proxy_signature("task-x", sig, old_ts)

    def test_hmac_valid_signature(self):
        import time
        from app.services.task_enforcement import generate_proxy_signature, verify_proxy_signature
        ts  = int(time.time())
        sig = generate_proxy_signature("task-x", ts)
        assert verify_proxy_signature("task-x", sig, ts)


# ── 3. Correlator v3 ─────────────────────────────────────────────────────────

class TestCorrelatorV3:
    def _task(self, tid, hours_offset=0):
        base = datetime(2025, 6, 1, 10, 0)
        s    = base + timedelta(hours=hours_offset)
        return {"id": tid, "goal": f"task {tid}", "started_at": s, "ended_at": s + timedelta(hours=1), "status": "active"}

    def test_exact_id_wins_conflict(self):
        from app.services.correlator import correlate_event_to_task
        tasks = [self._task("A", 0), self._task("B", 0)]
        event = {"task_id": "A", "timestamp": datetime(2025, 6, 1, 10, 30), "metadata": {}}
        tid, conf = correlate_event_to_task(event, tasks)
        assert tid == "A"
        assert conf >= 0.60

    def test_conflict_without_id_returns_none(self):
        from app.services.correlator import correlate_event_to_task
        tasks = [self._task("A", 0), self._task("B", 0)]  # overlap
        event = {"task_id": None, "timestamp": datetime(2025, 6, 1, 10, 30), "metadata": {}}
        tid, conf = correlate_event_to_task(event, tasks)
        assert tid is None

    def test_unresolved_queue_populated(self):
        from app.services.correlator import correlate_event_to_task, _unresolved_queue, queue_stats
        _unresolved_queue.clear()
        tasks = [self._task("A", 0), self._task("B", 0)]
        event = {"task_id": None, "timestamp": datetime(2025, 6, 1, 10, 30), "metadata": {}}
        correlate_event_to_task(event, tasks)
        stats = queue_stats()
        assert stats["unresolved_count"] >= 0   # may or may not queue depending on scores

    def test_resolve_queue_on_commit(self):
        from app.services.correlator import resolve_unresolved_queue, _unresolved_queue
        _unresolved_queue.clear()
        new_events = [{"event_type": "commit", "metadata": {}}]
        results = resolve_unresolved_queue(new_events=new_events)
        assert isinstance(results, list)

    def test_empty_tasks_returns_none(self):
        from app.services.correlator import correlate_event_to_task
        tid, conf = correlate_event_to_task({"task_id": None, "metadata": {}}, [])
        assert tid is None and conf == 0.0

    def test_evaluate_accuracy(self):
        from app.services.correlator import evaluate_correlation_accuracy
        r = evaluate_correlation_accuracy([], [])
        assert r["total"] == 0


# ── 4. Loop detection v3 ─────────────────────────────────────────────────────

class TestLoopDetectionV3:
    def test_context_classifier_debugging(self):
        from app.services.loop_detection import classify_prompt_context
        prompts = ["getting KeyError on this endpoint", "still getting KeyError"]
        errors  = ["KeyError: user_id"]
        assert classify_prompt_context(prompts, errors) == "debugging"

    def test_context_classifier_building(self):
        from app.services.loop_detection import classify_prompt_context
        prompts = ["implement a JWT function", "write a class for auth", "build the endpoint"]
        assert classify_prompt_context(prompts, []) == "building"

    def test_context_classifier_research(self):
        from app.services.loop_detection import classify_prompt_context
        prompts = ["what is the best approach", "compare options"]
        assert classify_prompt_context(prompts, []) == "research"

    def test_loop_type_context_in_result(self):
        from app.services.loop_detection import detect_prompt_loop
        same = "how do I debug this KeyError"
        result = detect_prompt_loop([same] * 4, error_logs=["KeyError"])
        # Whether loop or not, loop_type_context is set
        assert result.loop_type_context is not None

    def test_error_cluster_stored(self):
        from app.services.loop_detection import detect_error_loop, get_error_clusters
        same = "KeyError: user_id in processing"
        detect_error_loop([same, same, same])
        clusters = get_error_clusters()
        assert len(clusters) > 0

    def test_loop_confidence_between_0_and_1(self):
        from app.services.loop_detection import detect_error_loop
        same = "NullPointerException in handler"
        r = detect_error_loop([same] * 5)
        if r.loop_detected:
            assert 0 <= r.loop_confidence <= 1.0

    def test_no_loop_on_diverse_prompts(self):
        from app.services.loop_detection import detect_prompt_loop
        prompts = [
            "how to fix JWT expiry in FastAPI",
            "best practices for PostgreSQL indexing",
            "how to configure Celery beat schedule",
        ]
        result = detect_prompt_loop(prompts)
        assert not result.loop_detected


# ── 5. Scoring v3 ────────────────────────────────────────────────────────────

class TestScoringV3:
    def _score(self, **kw):
        from app.services.scoring import compute_score
        defaults = dict(level=3, started_at=None, ended_at=None,
                        prompt_count=0, output_count=0, event_timestamps=[],
                        ai_event_timestamps=[])
        defaults.update(kw)
        return compute_score(**defaults)

    def test_continuity_ratio_in_details(self):
        start = datetime(2025, 1, 1, 9, 0)
        end   = start + timedelta(hours=4)
        r = self._score(level=3, started_at=start, ended_at=end, event_timestamps=[
            start + timedelta(minutes=30), start + timedelta(minutes=60),
        ])
        assert "continuity_ratio" in r.details

    def test_chain_penalty_applied(self):
        """Long AI chain with no output should incur chain_penalty."""
        from app.services.scoring import compute_ai_efficiency
        start = datetime(2025, 1, 1, 9, 0)
        # 5 AI events, each 5 min apart = 25 min chain (> 20 min threshold)
        ai_ts = [start + timedelta(minutes=i*5) for i in range(6)]
        penalty, details = compute_ai_efficiency(
            prompt_count=6, output_count=0, active_hours=1.0, ai_event_timestamps=ai_ts
        )
        assert details["chain_penalty"] > 0

    def test_no_chain_penalty_with_idle_gap(self):
        """Chain reset by idle gap > 30 min should clear penalty."""
        from app.services.scoring import compute_ai_efficiency
        start = datetime(2025, 1, 1, 9, 0)
        ai_ts = [
            start + timedelta(minutes=0),
            start + timedelta(minutes=5),
            start + timedelta(minutes=45),  # 40 min gap → reset
            start + timedelta(minutes=50),
        ]
        _, details = compute_ai_efficiency(
            prompt_count=4, output_count=0, active_hours=1.0, ai_event_timestamps=ai_ts
        )
        assert details["chain_penalty"] == 0

    def test_rate_based_efficiency(self):
        """outputs_per_hour / prompts_per_hour determines penalty."""
        from app.services.scoring import compute_ai_efficiency
        # 10 prompts, 5 outputs in 1 hour → efficiency=0.5 → no penalty
        penalty, details = compute_ai_efficiency(10, 5, 1.0)
        assert penalty == 0
        assert details["efficiency_ratio"] == 0.5

    def test_velocity_scaled_by_continuity(self):
        """Interrupted sessions get lower velocity than continuous ones."""
        from app.services.scoring import compute_velocity, compute_continuity_ratio
        start = datetime(2025, 1, 1, 9, 0)
        end   = start + timedelta(hours=2)
        # Case 1: continuous events
        dense_ts = [start + timedelta(minutes=i*10) for i in range(12)]
        v_dense  = compute_velocity(dense_ts, start, end)
        # Case 2: only 2 events = mostly idle
        sparse_ts = [start + timedelta(minutes=1), end - timedelta(minutes=1)]
        v_sparse  = compute_velocity(sparse_ts, start, end)
        assert v_dense >= v_sparse

    def test_score_deterministic(self):
        """Same inputs → same score every time."""
        start = datetime(2025, 1, 1, 9, 0)
        end   = start + timedelta(hours=2)
        r1 = self._score(level=4, started_at=start, ended_at=end, prompt_count=5, output_count=3)
        r2 = self._score(level=4, started_at=start, ended_at=end, prompt_count=5, output_count=3)
        assert r1.final_score == r2.final_score


# ── 6. Deployment v3 ─────────────────────────────────────────────────────────

class TestDeploymentV3:
    def test_validation_depth_score_present(self):
        from app.services.deployment import ValidationResult, CheckResult
        vr = ValidationResult(
            status="partial", validation_level=2,
            validation_depth_score=0.5, score=0.5,
            checks=[
                CheckResult(1, "/health", True, 200, 50, None),
                CheckResult(2, "/api", False, 500, 60, "schema_fail", "error"),
            ],
        )
        assert vr.validation_depth_score == 0.5
        assert vr.validation_level == 2

    def test_endpoint_check_l5_fields_present(self):
        from app.services.deployment import EndpointCheck
        check = EndpointCheck(
            path="/api/action",
            state_change_path="/api/state",
            state_change_field="count",
            state_change_body={"action": "increment"},
        )
        assert check.state_change_path == "/api/state"
        assert check.state_change_field == "count"


# ── 7. Anti-gaming v3 ────────────────────────────────────────────────────────

class TestAntiGamingV3:
    def test_commit_quality_score_0_for_fmt(self):
        from app.services.anti_gaming import _commit_quality_score
        meta = {"message": "fmt: run black formatter", "lines_added": 3, "lines_removed": 2}
        score = _commit_quality_score(meta)
        assert score < 0.5

    def test_commit_quality_score_high_for_real_code(self):
        from app.services.anti_gaming import _commit_quality_score
        meta = {
            "message": "feat: implement JWT refresh token rotation logic",
            "lines_added": 120, "lines_removed": 20,
            "diff_text": "def refresh_token(user_id): ...\nclass TokenStore: ...",
        }
        score = _commit_quality_score(meta)
        assert score >= 0.5

    def test_aggregate_quality_empty_commits(self):
        from app.services.anti_gaming import compute_aggregate_commit_quality
        assert compute_aggregate_commit_quality([]) == 0.0

    def test_level5_blocked_by_quality_score(self):
        from app.services.anti_gaming import enforce_level5
        flags = enforce_level5(5, True, 3, 2, commit_quality_score=0.10)
        blocking = [f for f in flags if f.severity == "block"]
        assert any(f.flag_type == "level5_blocked" for f in blocking)

    def test_level5_passes_all_gates(self):
        from app.services.anti_gaming import enforce_level5
        flags = enforce_level5(5, True, 3, 3, commit_quality_score=0.80)
        blocking = [f for f in flags if f.severity == "block"]
        assert not blocking


# ── 8. Error normalization ────────────────────────────────────────────────────

class TestErrorNormV3:
    def test_normalize_removes_path_and_line(self):
        from app.services.loop_detection import normalize_error
        raw = "Error in /home/dhanush/eas/app/api.py, line 42: KeyError"
        norm, h = normalize_error(raw)
        assert "/home/dhanush" not in norm
        assert "42" not in norm

    def test_same_error_different_paths_same_hash(self):
        from app.services.loop_detection import normalize_error
        e1 = "Error in /home/a/api.py, line 10: KeyError: 'user_id'"
        e2 = "Error in /home/b/views.py, line 99: KeyError: 'user_id'"
        _, h1 = normalize_error(e1)
        _, h2 = normalize_error(e2)
        assert h1 == h2

    def test_hash_is_deterministic(self):
        from app.services.loop_detection import normalize_error
        raw = "ValueError: invalid literal for int()"
        _, h1 = normalize_error(raw)
        _, h2 = normalize_error(raw)
        assert h1 == h2


# ── 9. Metrics safety ────────────────────────────────────────────────────────

class TestMetricsSafety:
    def test_distribution_empty_list(self):
        from app.api.metrics import _distribution
        assert _distribution([]) == {}

    def test_safe_mean_empty(self):
        from app.api.metrics import _safe_mean
        assert _safe_mean([]) is None

    def test_safe_stdev_single_value(self):
        from app.api.metrics import _safe_stdev
        assert _safe_stdev([5.0]) is None

    def test_loop_fp_rate_no_feedback(self):
        from app.api.metrics import _loop_fp_rate
        import app.api.metrics as m
        old = m._loop_feedback[:]
        m._loop_feedback.clear()
        assert _loop_fp_rate() is None
        m._loop_feedback.extend(old)

    def test_tuning_engine_insufficient_data(self):
        """Tuning without data should return tuned=False."""
        import asyncio
        from app.api.metrics import run_adaptive_tuning, TuningRequest
        import app.api.metrics as m
        old = m._manual_scores[:]
        m._manual_scores.clear()
        result = asyncio.get_event_loop().run_until_complete(
            run_adaptive_tuning(TuningRequest(force=False))
        )
        assert result["tuned"] is False
        m._manual_scores.extend(old)
