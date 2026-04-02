"""Tests for routes/wallets.py — Wallet route handlers."""

import pytest
import json
from unittest.mock import patch, MagicMock

from repositories.registry import (
    set_analysis_job_repo,
    set_analysis_history_repo,
    set_user_repo,
    set_wallet_watchlist_repo,
    reset_all,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_repos():
    """Reset DI registry after each test."""
    yield
    reset_all()


@pytest.fixture
def mock_job_repo():
    repo = MagicMock()
    set_analysis_job_repo(repo)
    return repo


@pytest.fixture
def mock_history_repo():
    repo = MagicMock()
    set_analysis_history_repo(repo)
    return repo


@pytest.fixture
def mock_user_repo():
    repo = MagicMock()
    repo.get_subscription_tier.return_value = "free"
    set_user_repo(repo)
    return repo


# ===========================================================================
# compute_consistency (helper function in wallets.py)
# ===========================================================================

class TestComputeConsistency:
    """Tests for compute_consistency helper."""

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
        score = compute_consistency(runners)
        assert score == 100  # zero variance

    def test_returns_lower_score_for_high_variance(self):
        from routes.wallets import compute_consistency
        runners = [
            {"entry_to_ath_multiplier": 2},
            {"entry_to_ath_multiplier": 100},
        ]
        score = compute_consistency(runners)
        assert score < 50

    def test_ignores_zero_multipliers(self):
        from routes.wallets import compute_consistency
        runners = [
            {"entry_to_ath_multiplier": 0},
            {"entry_to_ath_multiplier": 10},
            {"entry_to_ath_multiplier": 10},
        ]
        score = compute_consistency(runners)
        assert score == 100  # only 10,10 counted => zero variance

    def test_clamps_to_zero(self):
        from routes.wallets import compute_consistency
        runners = [
            {"entry_to_ath_multiplier": 1},
            {"entry_to_ath_multiplier": 1000},
        ]
        score = compute_consistency(runners)
        assert score == 0


# ===========================================================================
# _job_dedup_key
# ===========================================================================

class TestJobDedupKey:
    """Tests for _job_dedup_key."""

    def test_deterministic(self):
        from routes.wallets import _job_dedup_key
        tokens = [{"address": "A"}, {"address": "B"}]
        k1 = _job_dedup_key("user1", tokens)
        k2 = _job_dedup_key("user1", tokens)
        assert k1 == k2

    def test_different_order_same_key(self):
        """Token order should not matter — tokens are sorted."""
        from routes.wallets import _job_dedup_key
        k1 = _job_dedup_key("u", [{"address": "A"}, {"address": "B"}])
        k2 = _job_dedup_key("u", [{"address": "B"}, {"address": "A"}])
        assert k1 == k2

    def test_different_users_different_keys(self):
        from routes.wallets import _job_dedup_key
        k1 = _job_dedup_key("u1", [{"address": "A"}])
        k2 = _job_dedup_key("u2", [{"address": "A"}])
        assert k1 != k2


# ===========================================================================
# GET /api/wallets/jobs/<job_id>
# ===========================================================================

class TestGetJobStatus:
    """Tests for GET /api/wallets/jobs/<job_id>."""

    def test_returns_404_when_job_not_found(self, client, mock_job_repo):
        mock_job_repo.get_job.return_value = None
        resp = client.get("/api/wallets/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_returns_results_when_completed(self, client, mock_job_repo):
        mock_job_repo.get_job.return_value = {
            "status": "completed",
            "results": {"wallets": [{"wallet": "W1"}]},
        }
        resp = client.get("/api/wallets/jobs/job-123")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "wallets" in data

    def test_returns_status_when_pending(self, client, mock_job_repo):
        mock_job_repo.get_job.return_value = {
            "status": "processing",
            "progress": 50,
        }
        resp = client.get("/api/wallets/jobs/job-123")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "processing"

    def test_returns_500_when_failed(self, client, mock_job_repo):
        mock_job_repo.get_job.return_value = {
            "status": "failed",
            "error": "API timeout",
        }
        resp = client.get("/api/wallets/jobs/job-123")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["status"] == "failed"


# ===========================================================================
# GET /api/wallets/jobs/<job_id>/progress
# ===========================================================================

class TestGetJobProgress:
    """Tests for GET /api/wallets/jobs/<job_id>/progress."""

    def test_returns_progress_data(self, client, mock_job_repo):
        mock_job_repo.get_job.return_value = {
            "status": "processing",
            "progress": 60,
            "phase": "pnl_fetch",
            "tokens_total": 3,
            "tokens_completed": 1,
        }
        resp = client.get("/api/wallets/jobs/job-123/progress")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["progress"] == 60
        assert data["phase"] == "pnl_fetch"

    def test_returns_404_when_missing(self, client, mock_job_repo):
        mock_job_repo.get_job.return_value = None
        resp = client.get("/api/wallets/jobs/nonexistent/progress")
        assert resp.status_code == 404


# ===========================================================================
# GET /api/wallets/history
# ===========================================================================

class TestAnalysisHistory:
    """Tests for history endpoints."""

    @patch("auth.is_supabase_available", return_value=False)
    def test_get_history_returns_list(self, _mock_supa, client, mock_history_repo):
        mock_history_repo.get_history.return_value = [
            {"id": "1", "resultType": "single"},
        ]
        resp = client.get("/api/wallets/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["recents"]) == 1

    @patch("auth.is_supabase_available", return_value=False)
    def test_get_history_respects_limit(self, _mock_supa, client, mock_history_repo):
        mock_history_repo.get_history.return_value = []
        resp = client.get("/api/wallets/history?limit=10&offset=5")
        assert resp.status_code == 200
        mock_history_repo.get_history.assert_called_once()
        args = mock_history_repo.get_history.call_args[0]
        assert args[1] == 10  # limit
        assert args[2] == 5   # offset

    @patch("auth.is_supabase_available", return_value=False)
    def test_save_history_requires_entry(self, _mock_supa, client, mock_history_repo):
        resp = client.post(
            "/api/wallets/history",
            data=json.dumps({"entry": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @patch("auth.is_supabase_available", return_value=False)
    def test_save_history_success(self, _mock_supa, client, mock_history_repo):
        resp = client.post(
            "/api/wallets/history",
            data=json.dumps({"entry": {"resultType": "single", "data": {}}}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        mock_history_repo.save_entry.assert_called_once()

    @patch("auth.is_supabase_available", return_value=False)
    def test_delete_history_entry(self, _mock_supa, client, mock_history_repo):
        resp = client.delete(
            "/api/wallets/history/some-uuid",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        mock_history_repo.delete_entry.assert_called_once()

    @patch("auth.is_supabase_available", return_value=False)
    def test_clear_all_history(self, _mock_supa, client, mock_history_repo):
        resp = client.delete(
            "/api/wallets/history/all",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        mock_history_repo.clear_all.assert_called_once()
