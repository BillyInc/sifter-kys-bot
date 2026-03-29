"""Tests for auth.py — Auth decorator tests."""

import pytest
from unittest.mock import patch, MagicMock
from flask import Flask

from auth import AuthService, AuthUser, require_auth, optional_auth


def _make_app():
    """Create a minimal Flask app with decorated test routes."""
    app = Flask(__name__)
    app.config['TESTING'] = True

    @app.route('/protected')
    @require_auth
    def protected_route():
        from flask import request, jsonify
        return jsonify({'user_id': getattr(request, 'user_id', None)})

    @app.route('/optional')
    @optional_auth
    def optional_route():
        from flask import request, jsonify
        return jsonify({'user_id': request.user_id})

    return app


class TestGetTokenFromHeader:
    """Tests for AuthService.get_token_from_header."""

    def test_extracts_bearer_token(self):
        """Bearer token is extracted correctly from Authorization header."""
        app = Flask(__name__)
        with app.test_request_context(headers={'Authorization': 'Bearer my-jwt-token'}):
            token = AuthService.get_token_from_header()
            assert token == 'my-jwt-token'

    def test_returns_none_for_missing_header(self):
        """Returns None when Authorization header is absent."""
        app = Flask(__name__)
        with app.test_request_context():
            token = AuthService.get_token_from_header()
            assert token is None

    def test_returns_none_for_non_bearer(self):
        """Returns None when Authorization header does not start with 'Bearer '."""
        app = Flask(__name__)
        with app.test_request_context(headers={'Authorization': 'Basic abc123'}):
            token = AuthService.get_token_from_header()
            assert token is None

    def test_returns_none_for_empty_bearer(self):
        """Returns None when header is just 'Bearer ' with no token following."""
        app = Flask(__name__)
        with app.test_request_context(headers={'Authorization': 'Bearer '}):
            # 'Bearer '[7:] == '', which is falsy but still returned as string
            token = AuthService.get_token_from_header()
            assert token == ''


class TestRequireAuth:
    """Tests for @require_auth decorator."""

    @patch('auth.is_supabase_available', return_value=True)
    def test_returns_401_when_no_token(self, _mock_supa):
        """Returns 401 when no Authorization header is provided."""
        app = _make_app()
        client = app.test_client()
        resp = client.get('/protected')
        assert resp.status_code == 401
        assert b'Missing authorization token' in resp.data

    @patch('auth.is_supabase_available', return_value=True)
    @patch.object(AuthService, 'verify_token', return_value=None)
    def test_returns_401_for_invalid_token(self, _mock_verify, _mock_supa):
        """Returns 401 when token verification fails."""
        app = _make_app()
        client = app.test_client()
        resp = client.get('/protected', headers={'Authorization': 'Bearer bad-token'})
        assert resp.status_code == 401
        assert b'Invalid or expired token' in resp.data

    @patch('auth.is_supabase_available', return_value=True)
    @patch.object(AuthService, 'verify_token', return_value=AuthUser(user_id='user-123', email='test@test.com'))
    def test_sets_user_on_request_when_valid(self, _mock_verify, _mock_supa):
        """Sets request.user_id when token is valid."""
        app = _make_app()
        client = app.test_client()
        resp = client.get('/protected', headers={'Authorization': 'Bearer valid-token'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['user_id'] == 'user-123'

    @patch('auth.is_supabase_available', return_value=False)
    def test_skips_auth_when_supabase_unavailable(self, _mock_supa):
        """Allows request through when Supabase is not configured (dev mode)."""
        app = _make_app()
        client = app.test_client()
        resp = client.get('/protected')
        assert resp.status_code == 200


class TestOptionalAuth:
    """Tests for @optional_auth decorator."""

    @patch('auth.AuthService.get_current_user', return_value=None)
    def test_allows_request_without_token(self, _mock_user):
        """Request succeeds even with no token."""
        app = _make_app()
        client = app.test_client()
        resp = client.get('/optional')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['user_id'] is None

    @patch('auth.AuthService.get_current_user', return_value=AuthUser(user_id='user-456', email='a@b.com'))
    def test_sets_user_id_when_token_valid(self, _mock_user):
        """Sets request.user_id when a valid token is provided."""
        app = _make_app()
        client = app.test_client()
        resp = client.get('/optional', headers={'Authorization': 'Bearer good-token'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['user_id'] == 'user-456'
