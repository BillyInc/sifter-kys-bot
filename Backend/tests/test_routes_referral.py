"""Tests for routes/referral_points_routes.py — Referral & points endpoints."""

import pytest
import json
from unittest.mock import patch, MagicMock

from auth import AuthUser
from repositories.registry import set_referral_repo, reset_all


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_repos():
    yield
    reset_all()


@pytest.fixture
def mock_referral_repo():
    repo = MagicMock()
    set_referral_repo(repo)
    return repo


def _auth_headers():
    return {"Authorization": "Bearer valid-token"}


_VALID_USER = AuthUser(user_id="ref-user-123", email="ref@test.com")


def _auth_patches():
    return [
        patch("auth.is_supabase_available", return_value=True),
        patch.object(
            __import__("auth").AuthService, "verify_token", return_value=_VALID_USER
        ),
    ]


# ===========================================================================
# GET /api/referral-points/referral-code
# ===========================================================================

class TestGetReferralCode:
    """Tests for GET /api/referral-points/referral-code."""

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_get_code_success(self, mock_get_mgr, client, mock_referral_repo):
        mock_get_mgr.return_value.get_referral_code.return_value = "REF123"
        mock_referral_repo.get_referral_code_stats.return_value = {
            "clicks": 10, "signups": 5, "conversions": 2
        }
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get(
                "/api/referral-points/referral-code",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["code"] == "REF123"
        assert data["stats"]["clicks"] == 10

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_get_code_failure_returns_500(self, mock_get_mgr, client, mock_referral_repo):
        mock_get_mgr.return_value.get_referral_code.return_value = None
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get(
                "/api/referral-points/referral-code",
                headers=_auth_headers(),
            )
        assert resp.status_code == 500

    @patch("auth.is_supabase_available", return_value=True)
    def test_requires_auth(self, _mock, client):
        resp = client.get("/api/referral-points/referral-code")
        assert resp.status_code == 401


# ===========================================================================
# GET /api/referral-points/referral-stats
# ===========================================================================

class TestGetReferralStats:
    """Tests for GET /api/referral-points/referral-stats."""

    def test_get_stats_success(self, client, mock_referral_repo):
        mock_referral_repo.get_referrals_by_referrer.return_value = [
            {"status": "converted", "referee_user_id": "u2", "referee_email": "u2@x.com",
             "referee_tier": "pro", "converted_at": "2025-01-01", "total_earnings": 30.0},
            {"status": "signed_up", "referee_user_id": "u3", "referee_email": "u3@x.com",
             "referee_tier": "free", "converted_at": None, "total_earnings": 0},
        ]
        mock_referral_repo.get_earnings_by_referrer.return_value = [
            {"amount": 30.0, "payment_status": "pending"},
        ]

        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get(
                "/api/referral-points/referral-stats",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["stats"]["total_signups"] == 2
        assert data["stats"]["total_conversions"] == 1
        assert data["stats"]["total_earnings"] == 30.0
        assert data["stats"]["total_pending"] == 30.0
        assert len(data["active_referrals"]) == 1


# ===========================================================================
# POST /api/referral-points/track-click/<code>
# ===========================================================================

class TestTrackClick:
    """Tests for POST /api/referral-points/track-click/<code>."""

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_track_click_success(self, mock_get_mgr, client):
        resp = client.post("/api/referral-points/track-click/ABC123")
        assert resp.status_code == 200
        mock_get_mgr.return_value.track_referral_click.assert_called_once_with("ABC123")

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_track_click_error_returns_500(self, mock_get_mgr, client):
        mock_get_mgr.return_value.track_referral_click.side_effect = Exception("DB")
        resp = client.post("/api/referral-points/track-click/BAD")
        assert resp.status_code == 500


# ===========================================================================
# GET /api/referral-points/validate-code/<code>
# ===========================================================================

class TestValidateCode:
    """Tests for GET /api/referral-points/validate-code/<code>."""

    def test_valid_code(self, client, mock_referral_repo):
        mock_referral_repo.validate_referral_code.return_value = True
        resp = client.get("/api/referral-points/validate-code/GOOD1")
        assert resp.status_code == 200
        assert resp.get_json()["valid"] is True

    def test_invalid_code(self, client, mock_referral_repo):
        mock_referral_repo.validate_referral_code.return_value = None
        resp = client.get("/api/referral-points/validate-code/BAD1")
        assert resp.status_code == 404
        assert resp.get_json()["valid"] is False


# ===========================================================================
# GET /api/referral-points/points
# ===========================================================================

class TestGetPoints:
    """Tests for GET /api/referral-points/points."""

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_get_points_success(self, mock_get_mgr, client):
        mock_get_mgr.return_value.get_user_points.return_value = {
            "total_points": 500, "lifetime_points": 1000, "daily_streak": 3
        }
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get(
                "/api/referral-points/points",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["points"]["total_points"] == 500

    @patch("auth.is_supabase_available", return_value=True)
    def test_requires_auth(self, _mock, client):
        resp = client.get("/api/referral-points/points")
        assert resp.status_code == 401


# ===========================================================================
# POST /api/referral-points/points/award
# ===========================================================================

class TestAwardPoints:
    """Tests for POST /api/referral-points/points/award."""

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_award_run_analysis(self, mock_get_mgr, client):
        mock_get_mgr.return_value.award_points.return_value = 5
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/referral-points/points/award",
                data=json.dumps({"action_type": "run_analysis"}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["points_earned"] == 5
        assert data["action_type"] == "run_analysis"

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_award_daily_login_updates_streak(self, mock_get_mgr, client):
        mgr = mock_get_mgr.return_value
        mgr.update_streak.return_value = 5
        mgr.award_points.return_value = 10

        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/referral-points/points/award",
                data=json.dumps({"action_type": "daily_login"}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        mgr.update_streak.assert_called_once()

    def test_award_missing_action_type_returns_400(self, client):
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/referral-points/points/award",
                data=json.dumps({}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 400


# ===========================================================================
# GET /api/referral-points/points/leaderboard
# ===========================================================================

class TestPointsLeaderboard:
    """Tests for GET /api/referral-points/points/leaderboard."""

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_leaderboard_default(self, mock_get_mgr, client):
        mock_get_mgr.return_value.get_leaderboard.return_value = [
            {"user_id": "u1", "lifetime_points": 500},
            {"user_id": "u2", "lifetime_points": 300},
        ]
        with patch("auth.is_supabase_available", return_value=False):
            resp = client.get("/api/referral-points/points/leaderboard")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["leaderboard"]) == 2
        assert data["type"] == "lifetime"

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_leaderboard_with_auth_shows_rank(self, mock_get_mgr, client):
        mock_get_mgr.return_value.get_leaderboard.return_value = [
            {"user_id": "other", "lifetime_points": 500},
            {"user_id": "ref-user-123", "lifetime_points": 300},
        ]
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get(
                "/api/referral-points/points/leaderboard",
                headers=_auth_headers(),
            )
        data = resp.get_json()
        assert data["user_rank"] == 2

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_leaderboard_respects_limit(self, mock_get_mgr, client):
        mock_get_mgr.return_value.get_leaderboard.return_value = []
        with patch("auth.is_supabase_available", return_value=False):
            resp = client.get("/api/referral-points/points/leaderboard?limit=10&offset=5")
        data = resp.get_json()
        assert data["limit"] == 10
        assert data["offset"] == 5


# ===========================================================================
# GET /api/referral-points/points/history
# ===========================================================================

class TestPointsHistory:
    """Tests for GET /api/referral-points/points/history."""

    def test_get_history_success(self, client, mock_referral_repo):
        mock_referral_repo.get_point_transactions.return_value = [
            {"action_type": "daily_login", "points_earned": 10},
        ]
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get(
                "/api/referral-points/points/history",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["transactions"]) == 1


# ===========================================================================
# GET /api/referral-points/dashboard
# ===========================================================================

class TestDashboard:
    """Tests for GET /api/referral-points/dashboard."""

    @patch("routes.referral_points_routes.get_referral_manager")
    def test_dashboard_success(self, mock_get_mgr, client, mock_referral_repo):
        mgr = mock_get_mgr.return_value
        mgr.get_referral_code.return_value = "DASH1"
        mgr.get_user_points.return_value = {
            "total_points": 100, "lifetime_points": 500, "daily_streak": 2, "level": 3
        }
        mgr.get_leaderboard.return_value = [
            {"user_id": "ref-user-123"},
        ]
        mock_referral_repo.get_referrals_by_referrer.return_value = [
            {"status": "converted", "total_earnings": 50.0},
        ]
        mock_referral_repo.get_referral_code_stats.return_value = {"clicks": 5}

        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get(
                "/api/referral-points/dashboard",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["referrals"]["code"] == "DASH1"
        assert data["points"]["total"] == 100
        assert data["points"]["rank"] == 1
