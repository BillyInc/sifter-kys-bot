"""Tests for routes/telegram.py — Telegram connection and notification routes."""

import pytest
import json
from unittest.mock import patch, MagicMock

from auth import AuthUser
from repositories.registry import set_telegram_repo, reset_all


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_repos():
    yield
    reset_all()


@pytest.fixture
def mock_telegram_repo():
    repo = MagicMock()
    set_telegram_repo(repo)
    return repo


def _auth_headers():
    return {"Authorization": "Bearer valid-token"}


_VALID_USER = AuthUser(user_id="test-user-tg", email="tg@test.com")


def _auth_patches():
    return [
        patch("auth.is_supabase_available", return_value=True),
        patch.object(
            __import__("auth").AuthService, "verify_token", return_value=_VALID_USER
        ),
    ]


def _mock_notifier(**overrides):
    """Create a MagicMock TelegramNotifier with common defaults."""
    n = MagicMock()
    n.is_user_connected.return_value = overrides.get("connected", True)
    n.get_user_chat_id.return_value = overrides.get("chat_id", "12345")
    n.disconnect_user.return_value = overrides.get("disconnect", True)
    n.toggle_alerts.return_value = overrides.get("toggle", True)
    n.send_wallet_alert.return_value = overrides.get("send_alert", True)
    n._make_request.return_value = overrides.get("make_request", {"ok": True, "result": {"username": "TestBot", "first_name": "Test"}})
    return n


# ===========================================================================
# GET /status
# ===========================================================================

class TestTelegramStatus:
    """Tests for GET /status."""

    def test_status_connected(self, client):
        notifier = _mock_notifier(connected=True, chat_id="999")
        with patch("routes.telegram.telegram_notifier", notifier), \
             patch("auth.is_supabase_available", return_value=False):
            resp = client.get("/api/telegram/status", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["connected"] is True
        assert data["chat_id"] == "999"

    def test_status_not_connected(self, client):
        notifier = _mock_notifier(connected=False)
        with patch("routes.telegram.telegram_notifier", notifier), \
             patch("auth.is_supabase_available", return_value=False):
            resp = client.get("/api/telegram/status")
        data = resp.get_json()
        assert data["connected"] is False

    def test_status_telegram_not_configured(self, client):
        with patch("routes.telegram.telegram_notifier", None), \
             patch("auth.is_supabase_available", return_value=False):
            resp = client.get("/api/telegram/status")
        assert resp.status_code == 503


# ===========================================================================
# POST /connect/link
# ===========================================================================

class TestGenerateConnectionLink:
    """Tests for POST /connect/link."""

    def test_generates_link(self, client, mock_telegram_repo):
        notifier = _mock_notifier()
        with patch("routes.telegram.telegram_notifier", notifier), \
             _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/telegram/connect/link",
                data=json.dumps({}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "telegram_link" in data
        assert "connection_token" in data
        assert data["expires_in"] == 900

    def test_connect_link_not_configured(self, client):
        with patch("routes.telegram.telegram_notifier", None), \
             patch("auth.is_supabase_available", return_value=False):
            resp = client.post(
                "/api/telegram/connect/link",
                data=json.dumps({}),
                content_type="application/json",
            )
        assert resp.status_code == 503


# ===========================================================================
# POST /disconnect
# ===========================================================================

class TestDisconnectTelegram:
    """Tests for POST /disconnect."""

    def test_disconnect_success(self, client):
        notifier = _mock_notifier(disconnect=True)
        with patch("routes.telegram.telegram_notifier", notifier), \
             _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/telegram/disconnect",
                data=json.dumps({}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_disconnect_not_found(self, client):
        notifier = _mock_notifier(disconnect=False)
        with patch("routes.telegram.telegram_notifier", notifier), \
             _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/telegram/disconnect",
                data=json.dumps({}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 404


# ===========================================================================
# POST /alerts/toggle
# ===========================================================================

class TestToggleAlerts:
    """Tests for POST /alerts/toggle."""

    def test_toggle_on(self, client):
        notifier = _mock_notifier(toggle=True)
        with patch("routes.telegram.telegram_notifier", notifier), \
             _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/telegram/alerts/toggle",
                data=json.dumps({"enabled": True}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.get_json()["alerts_enabled"] is True

    def test_toggle_failure(self, client):
        notifier = _mock_notifier(toggle=False)
        with patch("routes.telegram.telegram_notifier", notifier), \
             _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/telegram/alerts/toggle",
                data=json.dumps({"enabled": False}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 500


# ===========================================================================
# POST /test
# ===========================================================================

class TestSendTestAlert:
    """Tests for POST /test."""

    def test_send_test_success(self, client):
        notifier = _mock_notifier(connected=True, send_alert=True)
        with patch("routes.telegram.telegram_notifier", notifier), \
             _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/telegram/test",
                data=json.dumps({}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_send_test_not_connected(self, client):
        notifier = _mock_notifier(connected=False)
        with patch("routes.telegram.telegram_notifier", notifier), \
             _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/telegram/test",
                data=json.dumps({}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 400
        assert "not connected" in resp.get_json()["error"]

    def test_send_test_failure(self, client):
        notifier = _mock_notifier(connected=True, send_alert=False)
        with patch("routes.telegram.telegram_notifier", notifier), \
             _auth_patches()[0], _auth_patches()[1]:
            resp = client.post(
                "/api/telegram/test",
                data=json.dumps({}),
                content_type="application/json",
                headers=_auth_headers(),
            )
        assert resp.status_code == 500


# ===========================================================================
# POST /webhook
# ===========================================================================

class TestTelegramWebhook:
    """Tests for POST /webhook."""

    def test_webhook_message_queued(self, client):
        notifier = _mock_notifier()
        with patch("routes.telegram.telegram_notifier", notifier), \
             patch.dict("os.environ", {"TELEGRAM_SECRET_TOKEN": ""}, clear=False):
            resp = client.post(
                "/api/telegram/webhook",
                data=json.dumps({"message": {"text": "/start", "chat": {"id": 1}}}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_webhook_callback_query(self, client):
        notifier = _mock_notifier()
        with patch("routes.telegram.telegram_notifier", notifier), \
             patch.dict("os.environ", {"TELEGRAM_SECRET_TOKEN": ""}, clear=False):
            resp = client.post(
                "/api/telegram/webhook",
                data=json.dumps({"callback_query": {"data": "approve"}}),
                content_type="application/json",
            )
        assert resp.status_code == 200

    def test_webhook_empty_body_returns_400(self, client):
        notifier = _mock_notifier()
        with patch("routes.telegram.telegram_notifier", notifier):
            resp = client.post(
                "/api/telegram/webhook",
                data=json.dumps(None),
                content_type="application/json",
            )
        assert resp.status_code == 400

    def test_webhook_not_configured(self, client):
        with patch("routes.telegram.telegram_notifier", None):
            resp = client.post(
                "/api/telegram/webhook",
                data=json.dumps({"message": {}}),
                content_type="application/json",
            )
        assert resp.status_code == 503


# ===========================================================================
# GET /bot/info
# ===========================================================================

class TestBotInfo:
    """Tests for GET /bot/info."""

    def test_bot_info_success(self, client):
        notifier = _mock_notifier()
        with patch("routes.telegram.telegram_notifier", notifier):
            resp = client.get("/api/telegram/bot/info")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "bot" in data
        assert data["bot"]["username"] == "TestBot"

    def test_bot_info_failure(self, client):
        notifier = _mock_notifier(make_request={"ok": False})
        with patch("routes.telegram.telegram_notifier", notifier):
            resp = client.get("/api/telegram/bot/info")
        assert resp.status_code == 500

    def test_bot_info_not_configured(self, client):
        with patch("routes.telegram.telegram_notifier", None):
            resp = client.get("/api/telegram/bot/info")
        assert resp.status_code == 503


# ===========================================================================
# GET /ping
# ===========================================================================

class TestPing:
    """Tests for GET /ping."""

    def test_ping(self, client):
        resp = client.get("/api/telegram/ping")
        assert resp.status_code == 200
        assert resp.get_json()["pong"] is True
