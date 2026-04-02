"""Tests for routes/auth.py — Signup endpoint."""

import pytest
import json
from unittest.mock import patch, MagicMock


# ===========================================================================
# POST /api/auth/signup
# ===========================================================================

class TestHandleSignup:
    """Tests for POST /api/auth/signup."""

    @patch("routes.auth.get_referral_manager")
    def test_signup_success_without_referral(self, mock_get_mgr, client):
        resp = client.post(
            "/api/auth/signup",
            data=json.dumps({"user_id": "u123", "email": "test@test.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        # No referral code → create_referral not called
        mock_get_mgr.return_value.create_referral.assert_not_called()

    @patch("routes.auth.get_referral_manager")
    def test_signup_success_with_referral(self, mock_get_mgr, client):
        mgr = mock_get_mgr.return_value
        mgr.create_referral.return_value = {"success": True}

        resp = client.post(
            "/api/auth/signup",
            data=json.dumps({
                "user_id": "u456",
                "email": "user@example.com",
                "referral_code": "ABC123",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        mgr.create_referral.assert_called_once_with("ABC123", "u456", "user@example.com")

    @patch("routes.auth.get_referral_manager")
    def test_signup_referral_failure_still_200(self, mock_get_mgr, client):
        """Signup succeeds even if referral creation fails."""
        mgr = mock_get_mgr.return_value
        mgr.create_referral.return_value = {"success": False, "error": "invalid code"}

        resp = client.post(
            "/api/auth/signup",
            data=json.dumps({
                "user_id": "u789",
                "email": "test@x.com",
                "referral_code": "BAD",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_signup_missing_user_id_returns_400(self, client):
        resp = client.post(
            "/api/auth/signup",
            data=json.dumps({"email": "test@test.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_signup_missing_email_returns_400(self, client):
        resp = client.post(
            "/api/auth/signup",
            data=json.dumps({"user_id": "u123"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_signup_empty_body_returns_400(self, client):
        resp = client.post(
            "/api/auth/signup",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @patch("routes.auth.get_referral_manager")
    def test_signup_exception_returns_500(self, mock_get_mgr, client):
        mock_get_mgr.side_effect = Exception("DB down")
        resp = client.post(
            "/api/auth/signup",
            data=json.dumps({"user_id": "u1", "email": "a@b.c"}),
            content_type="application/json",
        )
        assert resp.status_code == 500
