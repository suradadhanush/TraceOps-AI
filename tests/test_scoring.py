"""
Tests for the deterministic scoring engine.
"""
from datetime import datetime, timedelta

import pytest

from app.services.scoring import (
    ScoreBreakdown,
    compute_score,
    compute_stability_penalty,
    compute_velocity,
    compute_ai_penalty,
)


class TestComputeVelocity:
    def test_fast_task_gets_10(self):
        start = datetime(2025, 1, 1, 9, 0)
        end = datetime(2025, 1, 1, 11, 0)  # 2h
        assert compute_velocity(start, end) == 10

    def test_medium_task_gets_5(self):
        start = datetime(2025, 1, 1, 9, 0)
        end = datetime(2025, 1, 1, 13, 0)  # 4h
        assert compute_velocity(start, end) == 5

    def test_slow_task_gets_0(self):
        start = datetime(2025, 1, 1, 9, 0)
        end = datetime(2025, 1, 1, 18, 0)  # 9h
        assert compute_velocity(start, end) == 0

    def test_missing_timestamps_returns_0(self):
        assert compute_velocity(None, None) == 0

    def test_boundary_exactly_3h_gets_10(self):
        start = datetime(2025, 1, 1, 9, 0)
        end = start + timedelta(hours=2, minutes=59, seconds=59)
        assert compute_velocity(start, end) == 10


class TestStabilityPenalty:
    def test_no_failures_no_penalty(self):
        assert compute_stability_penalty(0, 0) == 0

    def test_one_failed_deploy(self):
        assert compute_stability_penalty(1, 0) == 5

    def test_repeated_errors(self):
        assert compute_stability_penalty(0, 2) == 6  # 2 * 3

    def test_combined_penalty(self):
        assert compute_stability_penalty(2, 3) == 19  # 10 + 9

    def test_penalty_capped_at_30(self):
        assert compute_stability_penalty(10, 10) == 30


class TestAIPenalty:
    def test_no_issues(self):
        assert compute_ai_penalty(False, 0.0, 0) == 0

    def test_loop_detected(self):
        penalty = compute_ai_penalty(True, 0.5, 0)
        assert penalty >= 5

    def test_unproductive_prompts(self):
        assert compute_ai_penalty(False, 0.0, 3) == 6  # 3 * 2

    def test_combined_capped_at_20(self):
        penalty = compute_ai_penalty(True, 1.0, 20)
        assert penalty == 20


class TestComputeScore:
    def test_perfect_score(self):
        start = datetime(2025, 1, 1, 9, 0)
        end = start + timedelta(hours=1)
        result = compute_score(5, start, end, 0, 0, False, 0.0, 0)
        assert result.final_score == 60  # 50 + 10
        assert result.outcome_score == 50
        assert result.velocity == 10

    def test_zero_level_no_penalty(self):
        result = compute_score(0, None, None, 0, 0, False, 0.0, 0)
        assert result.final_score == 0

    def test_invalid_level_raises(self):
        with pytest.raises(ValueError):
            compute_score(6, None, None)

    def test_score_never_negative(self):
        start = datetime(2025, 1, 1, 9, 0)
        end = start + timedelta(hours=10)
        result = compute_score(0, start, end, 10, 10, True, 1.0, 20)
        assert result.final_score == 0

    def test_score_clamped_at_100(self):
        start = datetime(2025, 1, 1, 9, 0)
        end = start + timedelta(hours=1)
        result = compute_score(5, start, end, 0, 0, False, 0.0, 0)
        assert result.final_score <= 100

    def test_breakdown_is_consistent(self):
        start = datetime(2025, 1, 1, 9, 0)
        end = start + timedelta(hours=4)
        result = compute_score(3, start, end, 1, 1, False, 0.0, 2)
        # 30 + 5 - 5 - 3 - 4 = 23
        assert result.outcome_score == 30
        assert result.velocity == 5
        assert result.stability_penalty == 8  # 5+3
        assert result.ai_penalty == 4  # 2*2
        assert result.final_score == 23
