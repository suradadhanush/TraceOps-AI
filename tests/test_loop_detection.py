"""
Tests for loop detection module.
Note: embedding-based tests require sentence-transformers installed.
"""
import pytest

from app.services.loop_detection import (
    detect_attempt_loop,
    detect_error_loop,
    normalize_error,
)


class TestNormalizeError:
    def test_removes_file_paths(self):
        raw = "Error in /home/user/project/app.py line 42"
        normalized, _ = normalize_error(raw)
        assert "/home/user/project/app.py" not in normalized

    def test_removes_line_numbers(self):
        raw = "SyntaxError, line 99: unexpected token"
        normalized, _ = normalize_error(raw)
        assert "line N" in normalized
        assert "99" not in normalized

    def test_produces_consistent_hash(self):
        raw = "KeyError: 'user_id'"
        _, h1 = normalize_error(raw)
        _, h2 = normalize_error(raw)
        assert h1 == h2

    def test_different_errors_different_hashes(self):
        _, h1 = normalize_error("KeyError: 'user_id'")
        _, h2 = normalize_error("ValueError: invalid literal")
        assert h1 != h2


class TestDetectErrorLoop:
    def test_no_loop_with_unique_errors(self):
        logs = ["KeyError: a", "ValueError: b", "TypeError: c"]
        result = detect_error_loop(logs)
        assert not result.loop_detected

    def test_loop_detected_with_3_repeats(self):
        same = "KeyError: 'user_id'"
        result = detect_error_loop([same, same, same])
        assert result.loop_detected
        assert result.loop_type == "error_loop"
        assert result.severity > 0

    def test_loop_with_path_variation(self):
        # Same logical error, different paths/lines
        e1 = "Error in /home/a/app.py line 10: NullPointerException"
        e2 = "Error in /home/b/app.py line 20: NullPointerException"
        e3 = "Error in /home/c/app.py line 30: NullPointerException"
        result = detect_error_loop([e1, e2, e3])
        assert result.loop_detected  # same after normalization


class TestDetectAttemptLoop:
    def test_no_loop_if_success_present(self):
        attempts = [
            {"status": "failed"},
            {"status": "failed"},
            {"status": "success"},
        ]
        result = detect_attempt_loop(attempts)
        assert not result.loop_detected

    def test_loop_detected_with_all_failures(self):
        attempts = [{"status": "failed"}] * 4
        result = detect_attempt_loop(attempts)
        assert result.loop_detected
        assert result.loop_type == "attempt_loop"

    def test_insufficient_attempts_no_loop(self):
        attempts = [{"status": "failed"}, {"status": "failed"}]
        result = detect_attempt_loop(attempts)
        assert not result.loop_detected
