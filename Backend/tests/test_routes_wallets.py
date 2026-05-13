"""Tests for routes/wallets.py token-analysis route contracts."""

import json
from unittest.mock import MagicMock, patch


class _Chain:
    def __init__(self, data=None):
        self.data = data if data is not None else []

    def insert(self, *_args, **_kwargs):
        return self

    def update(self, *_args, **_kwargs):
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        return self


class _Supabase:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []

    def schema(self, *_args, **_kwargs):
        return self

    def table(self, *_args, **_kwargs):
        return _Chain(self.rows)


class TestComputeConsistency:
    def test_returns_50_when_less_than_two_points(self):
        from routes.wallets import compute_consistency
        assert compute_consistency([]) == 50
        assert compute_consistency([{"entry_to_ath_multiplier": 5}]) == 50

    def test_returns_high_score_for_low_variance(self):
        from routes.wallets import compute_consistency
        runners = [
            {"entry_to_ath_multiplier": 10},
            {"entry_to_ath_multiplier": 10},
            {"entry_to_ath_multiplier": 10},
        ]
        assert compute_consistency(runners) == 100

    def test_clamps_to_zero(self):
        from routes.wallets import compute_consistency
        runners = [
            {"entry_to_ath_multiplier": 1},
            {"entry_to_ath_multiplier": 1000},
        ]
        assert compute_consistency(runners) == 0


class TestAnalysisDispatch:
    @patch("services.worker_tasks.perform_wallet_analysis")
    @patch("routes.wallets._remember_celery_task")
    @patch("services.supabase_client.get_supabase_client")
    def test_single_token_dispatches_to_high_queue(
        self, mock_supabase, _mock_remember, mock_task, client
    ):
        mock_supabase.return_value = _Supabase()
        mock_task.apply_async.return_value.id = "celery-task-1"

        resp = client.post(
            "/api/wallets/analyze",
            data=json.dumps({
                "user_id": "user-1",
                "tokens": [{"address": "TokenA", "ticker": "AAA"}],
                "global_settings": {"min_roi_multiplier": 3.0},
            }),
            content_type="application/json",
        )

        assert resp.status_code == 202
        mock_task.apply_async.assert_called_once()
        assert mock_task.apply_async.call_args.kwargs["queue"] == "high"

    @patch("services.worker_tasks.perform_wallet_analysis")
    @patch("routes.wallets._remember_celery_task")
    @patch("services.supabase_client.get_supabase_client")
    def test_multi_token_dispatches_to_batch_queue(
        self, mock_supabase, _mock_remember, mock_task, client
    ):
        mock_supabase.return_value = _Supabase()
        mock_task.apply_async.return_value.id = "celery-task-2"

        resp = client.post(
            "/api/wallets/analyze",
            data=json.dumps({
                "user_id": "user-1",
                "tokens": [
                    {"address": "TokenA", "ticker": "AAA"},
                    {"address": "TokenB", "ticker": "BBB"},
                ],
            }),
            content_type="application/json",
        )

        assert resp.status_code == 202
        mock_task.apply_async.assert_called_once()
        assert mock_task.apply_async.call_args.kwargs["queue"] == "batch"

    @patch("services.worker_tasks.perform_trending_batch_analysis")
    @patch("routes.wallets._remember_celery_task")
    @patch("services.supabase_client.get_supabase_client")
    def test_trending_batch_dispatches_to_batch_queue(
        self, mock_supabase, _mock_remember, mock_task, client
    ):
        mock_supabase.return_value = _Supabase()
        mock_task.apply_async.return_value.id = "celery-task-3"

        resp = client.post(
            "/api/wallets/trending/analyze-batch",
            data=json.dumps({
                "user_id": "user-1",
                "runners": [{"address": "TokenA", "symbol": "AAA"}],
                "min_runner_hits": 2,
                "min_roi_multiplier": 3.0,
            }),
            content_type="application/json",
        )

        assert resp.status_code == 202
        mock_task.apply_async.assert_called_once()
        assert mock_task.apply_async.call_args.kwargs["queue"] == "batch"


class TestJobStatus:
    @patch("services.supabase_client.get_supabase_client")
    def test_returns_results_when_completed(self, mock_supabase, client):
        mock_supabase.return_value = _Supabase([
            {"status": "completed", "results": {"wallets": [{"wallet": "W1"}]}}
        ])

        resp = client.get("/api/wallets/jobs/job-123")
        assert resp.status_code == 200
        assert "wallets" in resp.get_json()

    @patch("services.supabase_client.get_supabase_client")
    def test_progress_returns_tracking_fields(self, mock_supabase, client):
        mock_supabase.return_value = _Supabase([
            {
                "status": "processing",
                "progress": 60,
                "phase": "pnl_fetch",
                "tokens_total": 3,
                "tokens_completed": 1,
            }
        ])

        resp = client.get("/api/wallets/jobs/job-123/progress")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["progress"] == 60
        assert data["phase"] == "pnl_fetch"
