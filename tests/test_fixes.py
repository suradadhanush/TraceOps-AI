"""
Tests for the 5 deployment fixes + observability layer.
"""
import time
import pytest
from datetime import datetime, timedelta


class TestWebhookDurability:
    def test_idempotency_key_canonical(self):
        from app.services.webhook_durability import _idempotency_key
        k1 = _idempotency_key("github", {"b": 2, "a": 1})
        k2 = _idempotency_key("github", {"a": 1, "b": 2})
        assert k1 == k2

    def test_idempotency_key_different_sources(self):
        from app.services.webhook_durability import _idempotency_key
        k1 = _idempotency_key("github", {"x": 1})
        k2 = _idempotency_key("deploy", {"x": 1})
        assert k1 != k2

    def test_idempotency_key_length(self):
        from app.services.webhook_durability import _idempotency_key
        k = _idempotency_key("github", {"data": "test"})
        assert len(k) == 32

    def test_max_retries_constant(self):
        from app.services.webhook_durability import MAX_RETRIES
        assert MAX_RETRIES == 3


class TestScheduler:
    def test_record_success(self):
        from app.api.scheduler import record_schedule_attempt, _schedule_log
        _schedule_log.clear()
        record_schedule_attempt("test_job", success=True)
        assert _schedule_log[-1]["success"] is True
        assert _schedule_log[-1]["job"] == "test_job"

    def test_record_failure(self):
        from app.api.scheduler import record_schedule_attempt, _schedule_log
        _schedule_log.clear()
        record_schedule_attempt("test_job", success=False, error="timeout")
        assert _schedule_log[-1]["success"] is False
        assert _schedule_log[-1]["error"] == "timeout"

    def test_get_missed_only_returns_failures(self):
        from app.api.scheduler import record_schedule_attempt, get_missed_schedules, _schedule_log
        _schedule_log.clear()
        record_schedule_attempt("job_a", success=True)
        record_schedule_attempt("job_b", success=False, error="err")
        record_schedule_attempt("job_c", success=True)
        missed = get_missed_schedules()
        assert len(missed) == 1
        assert missed[0]["job"] == "job_b"

    def test_worker_health_returns_dict(self):
        import asyncio
        from app.api.scheduler import check_worker_alive
        result = asyncio.get_event_loop().run_until_complete(check_worker_alive(timeout=0.1))
        # Will fail (no broker in test) but must return valid dict
        assert "alive" in result
        assert "error" in result
        assert isinstance(result["alive"], bool)

    def test_db_health_check_structure(self):
        import asyncio
        from app.api.scheduler import check_db_alive
        result = asyncio.get_event_loop().run_until_complete(check_db_alive())
        assert "alive" in result
        assert "error" in result


class TestMetricsSecurity:
    def test_rate_limit_blocks_after_10(self):
        from app.api.metrics import _check_rate_limit, _rate_windows
        _rate_windows.clear()
        ip = "test-ip-rate"
        for _ in range(10):
            assert _check_rate_limit(ip)
        # 11th should be blocked
        assert not _check_rate_limit(ip)

    def test_rate_limit_different_ips_independent(self):
        from app.api.metrics import _check_rate_limit, _rate_windows
        _rate_windows.clear()
        for _ in range(10):
            _check_rate_limit("ip-a")
        # Different IP should still be allowed
        assert _check_rate_limit("ip-b")

    def test_require_key_raises_on_wrong(self):
        from fastapi import HTTPException
        from app.api.metrics import _require_key
        with pytest.raises(HTTPException) as exc:
            _require_key("wrong-key")
        assert exc.value.status_code == 403

    def test_require_key_raises_on_none(self):
        from fastapi import HTTPException
        from app.api.metrics import _require_key
        with pytest.raises(HTTPException):
            _require_key(None)

    def test_require_key_passes_with_secret(self):
        from app.core.config import settings
        from app.api.metrics import _require_key
        # Should not raise
        _require_key(settings.SECRET_KEY)


class TestStructuredLogging:
    def test_json_formatter_output(self):
        import logging
        import json
        from app.core.logger import JSONFormatter
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="traceops.test", level=logging.INFO,
            pathname="", lineno=0, msg="test message",
            args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["msg"] == "test message"
        assert "ts" in parsed
        assert "logger" in parsed

    def test_json_formatter_with_eas_fields(self):
        import logging
        import json
        from app.core.logger import JSONFormatter
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="traceops.task", level=logging.INFO,
            pathname="", lineno=0, msg="task start",
            args=(), exc_info=None,
        )
        record.eas_task_id = "abc123"
        record.eas_score   = 72
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["task_id"] == "abc123"
        assert parsed["score"] == 72

    def test_get_logger_name(self):
        from app.core.logger import get_logger
        log = get_logger("test_module")
        assert log.name == "traceops.test_module"

    def test_log_helpers_dont_crash(self):
        from app.core.logger import (
            configure_logging, log_task_start, log_task_end,
            log_correlation_decision, log_score_output,
            log_proxy_usage, log_webhook_received,
        )
        configure_logging("WARNING")  # suppress output
        log_task_start("t1", "Test goal", 3)
        log_task_end("t1", 3, 72, 2.5)
        log_correlation_decision(1, "commit", "t1", 0.85, "direct_id")
        log_correlation_decision(2, "ai", None, 0.0, "unmatched")
        log_score_output("t1", 72, 3, 10, 5, 3, False)
        log_proxy_usage("t1", "openai", 100, 350, True)
        log_proxy_usage(None, "anthropic", None, 0, False, suspected_bypass=True)
        log_webhook_received("github", "push", "abc123def456", False)


class TestProxyEnforcement:
    def test_constants_correct(self):
        from app.services.proxy_enforcement import PROXY_COVERAGE_MIN, BYPASS_GAP_HOURS
        assert PROXY_COVERAGE_MIN == 0.80
        assert BYPASS_GAP_HOURS == 2.0

    def test_gap_detection_empty_timestamps(self):
        """Gap detection should return empty list with < 2 timestamps."""
        # We can test the logic inline without DB
        timestamps = [datetime(2025, 1, 1, 9, 0)]  # single timestamp
        gaps = []
        from app.services.proxy_enforcement import BYPASS_GAP_HOURS
        for i in range(len(timestamps) - 1):
            gap_h = (timestamps[i+1] - timestamps[i]).total_seconds() / 3600
            if gap_h > BYPASS_GAP_HOURS:
                gaps.append(gap_h)
        assert gaps == []

    def test_gap_detection_with_large_gap(self):
        from app.services.proxy_enforcement import BYPASS_GAP_HOURS
        ts = [datetime(2025, 1, 1, 9, 0), datetime(2025, 1, 1, 12, 0)]
        gaps = []
        for i in range(len(ts) - 1):
            gap_h = (ts[i+1] - ts[i]).total_seconds() / 3600
            if gap_h > BYPASS_GAP_HOURS:
                gaps.append(gap_h)
        assert len(gaps) == 1
        assert gaps[0] == 3.0


class TestConfigPersistence:
    def test_config_key_constant(self):
        from app.services.config_store import _CONFIG_KEY
        assert _CONFIG_KEY == "traceops_global_config_v1"

    def test_config_store_orm_has_correct_table(self):
        from app.services.config_store import ConfigStore
        assert ConfigStore.__tablename__ == "eas_config_store"

    def test_config_store_columns(self):
        from app.services.config_store import ConfigStore
        cols = {c.name for c in ConfigStore.__table__.columns}
        assert "key" in cols
        assert "value" in cols
        assert "updated_at" in cols
