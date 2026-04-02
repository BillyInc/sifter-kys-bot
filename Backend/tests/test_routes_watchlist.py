"""Tests for routes/watchlist.py — Watchlist route handlers."""

import pytest
import json
from unittest.mock import patch, MagicMock

from auth import AuthUser
from repositories.registry import set_watchlist_repo, reset_all


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_repos():
    yield
    reset_all()


@pytest.fixture
def mock_watchlist_repo():
    repo = MagicMock()
    set_watchlist_repo(repo)
    return repo


def _auth_headers():
    return {"Authorization": "Bearer valid-token"}


def _post_json(client, url, data, headers=None):
    return client.post(
        url,
        data=json.dumps(data),
        content_type="application/json",
        headers=headers or _auth_headers(),
    )


# We need auth to actually set request.user_id, so mock verify_token.
_VALID_USER = AuthUser(user_id="test-user-123", email="test@test.com")

def _auth_patches():
    """Return a stack of patches that make @require_auth pass with a user."""
    return [
        patch("auth.is_supabase_available", return_value=True),
        patch.object(
            __import__("auth").AuthService, "verify_token", return_value=_VALID_USER
        ),
    ]


# ===========================================================================
# POST /api/watchlist/add
# ===========================================================================

class TestAddToWatchlist:
    """Tests for POST /api/watchlist/add."""

    def test_add_success(self, client, mock_watchlist_repo):
        mock_watchlist_repo.add_to_watchlist.return_value = True
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(client, "/api/watchlist/add", {"account": {"name": "test"}})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_add_missing_account_returns_400(self, client, mock_watchlist_repo):
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(client, "/api/watchlist/add", {})
        assert resp.status_code == 400

    def test_add_failure_returns_500(self, client, mock_watchlist_repo):
        mock_watchlist_repo.add_to_watchlist.return_value = False
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(client, "/api/watchlist/add", {"account": {"name": "test"}})
        assert resp.status_code == 500

    @patch("auth.is_supabase_available", return_value=True)
    def test_add_requires_auth(self, _mock, client, mock_watchlist_repo):
        """Returns 401 without auth header."""
        resp = client.post(
            "/api/watchlist/add",
            data=json.dumps({"account": {"name": "test"}}),
            content_type="application/json",
        )
        assert resp.status_code == 401


# ===========================================================================
# GET /api/watchlist/get
# ===========================================================================

class TestGetWatchlist:
    """Tests for GET /api/watchlist/get."""

    def test_get_returns_accounts(self, client, mock_watchlist_repo):
        mock_watchlist_repo.get_watchlist.return_value = [
            {"author_id": "123", "username": "alpha_trader"},
        ]
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get("/api/watchlist/get", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["accounts"]) == 1

    def test_get_returns_empty_list(self, client, mock_watchlist_repo):
        mock_watchlist_repo.get_watchlist.return_value = []
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get("/api/watchlist/get", headers=_auth_headers())
        data = resp.get_json()
        assert data["accounts"] == []


# ===========================================================================
# POST /api/watchlist/remove
# ===========================================================================

class TestRemoveFromWatchlist:
    """Tests for POST /api/watchlist/remove."""

    def test_remove_success(self, client, mock_watchlist_repo):
        mock_watchlist_repo.remove_from_watchlist.return_value = True
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(client, "/api/watchlist/remove", {"author_id": "123"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_remove_missing_author_id_returns_400(self, client, mock_watchlist_repo):
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(client, "/api/watchlist/remove", {})
        assert resp.status_code == 400

    def test_remove_failure_returns_500(self, client, mock_watchlist_repo):
        mock_watchlist_repo.remove_from_watchlist.return_value = False
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(client, "/api/watchlist/remove", {"author_id": "123"})
        assert resp.status_code == 500


# ===========================================================================
# POST /api/watchlist/update
# ===========================================================================

class TestUpdateWatchlistAccount:
    """Tests for POST /api/watchlist/update."""

    def test_update_success(self, client, mock_watchlist_repo):
        mock_watchlist_repo.update_account_notes.return_value = True
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(
                client, "/api/watchlist/update",
                {"author_id": "123", "notes": "good caller", "tags": ["alpha"]},
            )
        assert resp.status_code == 200

    def test_update_missing_author_id_returns_400(self, client, mock_watchlist_repo):
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(client, "/api/watchlist/update", {"notes": "test"})
        assert resp.status_code == 400

    def test_update_failure_returns_500(self, client, mock_watchlist_repo):
        mock_watchlist_repo.update_account_notes.return_value = False
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(
                client, "/api/watchlist/update",
                {"author_id": "123", "notes": "test"},
            )
        assert resp.status_code == 500


# ===========================================================================
# GET /api/watchlist/groups
# ===========================================================================

class TestGetWatchlistGroups:
    """Tests for GET /api/watchlist/groups."""

    def test_returns_groups(self, client, mock_watchlist_repo):
        mock_watchlist_repo.get_user_groups.return_value = [
            {"id": 1, "group_name": "Top Callers"},
        ]
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get("/api/watchlist/groups", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["groups"]) == 1


# ===========================================================================
# POST /api/watchlist/groups/create
# ===========================================================================

class TestCreateWatchlistGroup:
    """Tests for POST /api/watchlist/groups/create."""

    def test_create_success(self, client, mock_watchlist_repo):
        mock_watchlist_repo.create_group.return_value = 42
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(
                client, "/api/watchlist/groups/create",
                {"group_name": "Whale Wallets", "description": "50x+ wallets"},
            )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["group_id"] == 42

    def test_create_missing_name_returns_400(self, client, mock_watchlist_repo):
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(client, "/api/watchlist/groups/create", {})
        assert resp.status_code == 400

    def test_create_failure_returns_500(self, client, mock_watchlist_repo):
        mock_watchlist_repo.create_group.return_value = None
        with _auth_patches()[0], _auth_patches()[1]:
            resp = _post_json(
                client, "/api/watchlist/groups/create",
                {"group_name": "test"},
            )
        assert resp.status_code == 500


# ===========================================================================
# GET /api/watchlist/stats
# ===========================================================================

class TestGetWatchlistStats:
    """Tests for GET /api/watchlist/stats."""

    def test_returns_stats(self, client, mock_watchlist_repo):
        mock_watchlist_repo.get_watchlist_stats.return_value = {
            "total_accounts": 12, "total_groups": 3,
        }
        with _auth_patches()[0], _auth_patches()[1]:
            resp = client.get("/api/watchlist/stats", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["stats"]["total_accounts"] == 12
