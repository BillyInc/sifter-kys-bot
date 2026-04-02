"""Tests for services/worker_tasks.py — Background task modules."""

import pytest
import time
import json
import threading
from unittest.mock import patch, MagicMock, PropertyMock


# ===========================================================================
# APICircuitBreaker
# ===========================================================================

class TestAPICircuitBreaker:
    """Tests for the APICircuitBreaker."""

    def test_successful_call_resets_failure_count(self):
        from services.worker_tasks import APICircuitBreaker
        cb = APICircuitBreaker("test", failure_threshold=3, recovery_timeout=60)
        cb.failure_count = 2
        result = cb.call(lambda: "ok")
        assert result == "ok"
        assert cb.failure_count == 0

    def test_opens_after_threshold_failures(self):
        from services.worker_tasks import APICircuitBreaker
        cb = APICircuitBreaker("test", failure_threshold=2, recovery_timeout=60)

        def fail():
            raise ValueError("boom")

        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(fail)

        assert cb.is_open is True
        assert cb.failure_count == 2

    def test_rejects_calls_when_open(self):
        from services.worker_tasks import APICircuitBreaker
        cb = APICircuitBreaker("test", failure_threshold=1, recovery_timeout=9999)
        cb.is_open = True
        cb.last_failure_time = time.time()

        with pytest.raises(Exception, match="Circuit breaker.*is open"):
            cb.call(lambda: "should not run")

    def test_attempts_recovery_after_timeout(self):
        from services.worker_tasks import APICircuitBreaker
        cb = APICircuitBreaker("test", failure_threshold=1, recovery_timeout=0)
        cb.is_open = True
        cb.last_failure_time = time.time() - 1  # expired

        result = cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.is_open is False
        assert cb.failure_count == 0

    def test_recovery_attempt_can_fail(self):
        from services.worker_tasks import APICircuitBreaker
        cb = APICircuitBreaker("test", failure_threshold=1, recovery_timeout=0)
        cb.is_open = True
        cb.last_failure_time = time.time() - 1

        def fail():
            raise RuntimeError("still broken")

        with pytest.raises(RuntimeError):
            cb.call(fail)
        assert cb.is_open is True


# ===========================================================================
# HeartbeatManager
# ===========================================================================

class TestHeartbeatManager:
    """Tests for HeartbeatManager (now a no-op shim under Celery)."""

    def test_start_is_noop(self):
        from services.worker_tasks import HeartbeatManager
        hb = HeartbeatManager()
        hb.start()  # should not raise

    def test_stop_is_noop(self):
        from services.worker_tasks import HeartbeatManager
        hb = HeartbeatManager()
        hb.stop()  # should not raise

    def test_accepts_job_arg_for_backward_compat(self):
        from services.worker_tasks import HeartbeatManager
        hb = HeartbeatManager(job=MagicMock(), interval=10)
        hb.start()
        hb.stop()


# ===========================================================================
# SoftTimeoutError + timeout decorator
# ===========================================================================

class TestSoftTimeoutError:
    """Tests for SoftTimeoutError (now a Celery SoftTimeLimitExceeded subclass)."""

    def test_soft_timeout_error_is_exception(self):
        from services.worker_tasks import SoftTimeoutError
        assert issubclass(SoftTimeoutError, Exception)

    def test_soft_timeout_error_is_celery_soft_time_limit(self):
        from celery.exceptions import SoftTimeLimitExceeded
        from services.worker_tasks import SoftTimeoutError
        assert issubclass(SoftTimeoutError, SoftTimeLimitExceeded)


# ===========================================================================
# _safe_heartbeat_job
# ===========================================================================

class TestSafeHeartbeatJob:
    """Tests for _safe_heartbeat_job (now always returns None under Celery)."""

    def test_returns_none(self):
        from services.worker_tasks import _safe_heartbeat_job
        assert _safe_heartbeat_job() is None


# ===========================================================================
# _handle_failed_job (dead letter queue)
# ===========================================================================

class TestHandleCeleryTaskFailure:
    """Tests for _handle_celery_task_failure dead letter handler."""

    @patch("services.worker_tasks._get_redis")
    def test_pushes_to_dead_letter_queue(self, mock_get_redis):
        mock_r = MagicMock()
        mock_get_redis.return_value = mock_r

        from services.worker_tasks import _handle_celery_task_failure

        _handle_celery_task_failure(
            task_id="task-123",
            exc=ValueError("test error"),
            args=("arg1",),
            kwargs={},
            einfo="traceback string",
            queue_name="high",
        )

        mock_r.lpush.assert_called_once()
        key = mock_r.lpush.call_args[0][0]
        assert key == "dead_letter:high"

        payload = json.loads(mock_r.lpush.call_args[0][1])
        assert payload["job_id"] == "task-123"
        assert "test error" in payload["error"]

    @patch("services.worker_tasks._get_redis")
    def test_handles_exception_gracefully(self, mock_get_redis):
        """Does not raise even if Redis fails."""
        mock_get_redis.side_effect = Exception("Redis down")
        from services.worker_tasks import _handle_celery_task_failure

        # Should not raise
        _handle_celery_task_failure(
            task_id="t", exc=Exception("boom"), args=(), kwargs={},
            einfo="tb", queue_name="q",
        )


# ===========================================================================
# TTL / timeout constants
# ===========================================================================

class TestConstants:
    """Sanity checks for critical constants."""

    def test_ttl_constants_are_positive(self):
        from services.worker_tasks import (
            LOG_TTL, PIPELINE_TTL, DEAD_LETTER_TTL, HISTORY_CACHE_TTL,
        )
        assert LOG_TTL > 0
        assert PIPELINE_TTL > 0
        assert DEAD_LETTER_TTL > 0
        assert HISTORY_CACHE_TTL > 0

    def test_job_timeout_constants_are_positive(self):
        from services.worker_tasks import (
            JT_PHASE1_WORKER, JT_COORD, JT_PNL_BATCH,
            JT_MERGE, JT_SCORER, JT_RUNNER_BATCH,
            JT_MERGE_FINAL, JT_AGGREGATE,
        )
        for val in [JT_PHASE1_WORKER, JT_COORD, JT_PNL_BATCH,
                     JT_MERGE, JT_SCORER, JT_RUNNER_BATCH,
                     JT_MERGE_FINAL, JT_AGGREGATE]:
            assert val > 0

    def test_pipeline_ttl_greater_than_log_ttl(self):
        from services.worker_tasks import LOG_TTL, PIPELINE_TTL
        assert PIPELINE_TTL > LOG_TTL
