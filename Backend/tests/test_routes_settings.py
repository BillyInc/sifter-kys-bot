"""Tests for routes/user_settings.py — User preferences endpoints."""

import pytest
import json
from unittest.mock import patch, MagicMock

from repositories.registry import set_user_settings_repo, reset_all


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_repos():
    yield
    reset_all()


@pytest.fixture
def mock_settings_repo():
    repo = MagicMock()
    set_user_settings_repo(repo)
    return repo


# ===========================================================================
# POST /api/user/settings
# ===========================================================================

class TestSaveUserSettings:
    """Tests for POST /api/user/settings."""

    @patch("auth.is_supabase_available", return_value=False)
    def test_save_settings_success(self, _mock, client, mock_settings_repo):
        resp = client.post(
            "/api/user/settings",
            data=json.dumps({"settings": {"theme": "light", "timezone": "EST"}}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        mock_settings_repo.save_settings.assert_called_once()

    @patch("auth.is_supabase_available", return_value=False)
    def test_save_settings_empty(self, _mock, client, mock_settings_repo):
        """Empty settings dict is still valid — saves empty preferences."""
        resp = client.post(
            "/api/user/settings",
            data=json.dumps({"settings": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        mock_settings_repo.save_settings.assert_called_once()

    @patch("auth.is_supabase_available", return_value=False)
    def test_save_settings_repo_error_returns_500(self, _mock, client, mock_settings_repo):
        mock_settings_repo.save_settings.side_effect = Exception("DB error")
        resp = client.post(
            "/api/user/settings",
            data=json.dumps({"settings": {"theme": "dark"}}),
            content_type="application/json",
        )
        assert resp.status_code == 500

    @patch("auth.is_supabase_available", return_value=False)
    def test_options_returns_ok(self, _mock, client, mock_settings_repo):
        """OPTIONS should return successfully (CORS preflight)."""
        resp = client.options("/api/user/settings")
        assert resp.status_code in (200, 204)


# ===========================================================================
# GET /api/user/settings
# ===========================================================================

class TestGetUserSettings:
    """Tests for GET /api/user/settings."""

    @patch("auth.is_supabase_available", return_value=False)
    def test_get_settings_returns_saved(self, _mock, client, mock_settings_repo):
        mock_settings_repo.get_settings.return_value = {"theme": "light"}
        resp = client.get("/api/user/settings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["settings"]["theme"] == "light"

    @patch("auth.is_supabase_available", return_value=False)
    def test_get_settings_returns_defaults_when_none(self, _mock, client, mock_settings_repo):
        mock_settings_repo.get_settings.return_value = None
        resp = client.get("/api/user/settings")
        assert resp.status_code == 200
        data = resp.get_json()
        # Should return DEFAULT_SETTINGS
        assert data["settings"]["timezone"] == "UTC"
        assert data["settings"]["theme"] == "dark"

    @patch("auth.is_supabase_available", return_value=False)
    def test_get_settings_repo_error_returns_500(self, _mock, client, mock_settings_repo):
        mock_settings_repo.get_settings.side_effect = Exception("DB error")
        resp = client.get("/api/user/settings")
        assert resp.status_code == 500

    @patch("auth.is_supabase_available", return_value=False)
    def test_get_options_returns_ok(self, _mock, client, mock_settings_repo):
        """OPTIONS should return successfully (CORS preflight)."""
        resp = client.options("/api/user/settings")
        assert resp.status_code in (200, 204)
