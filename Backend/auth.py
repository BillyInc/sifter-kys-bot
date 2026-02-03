"""Authentication middleware and utilities."""
from dataclasses import dataclass
from functools import wraps
from typing import Optional

from flask import request, jsonify

from services.supabase_client import get_supabase_client, is_supabase_available


@dataclass
class AuthUser:
    """Authenticated user data."""
    user_id: str
    email: Optional[str] = None


class AuthService:
    """Service for JWT authentication using Supabase."""

    @staticmethod
    def get_token_from_header() -> Optional[str]:
        """Extract JWT token from Authorization header."""
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]
        return None

    @staticmethod
    def verify_token(token: str) -> Optional[AuthUser]:
        """
        Verify JWT token using Supabase client.
        Uses Supabase's auth.get_user() which handles JWKS verification.

        Returns:
            AuthUser if valid, None if invalid or auth not configured.
        """
        if not is_supabase_available():
            return None

        try:
            client = get_supabase_client()
            response = client.auth.get_user(token)

            if response and response.user:
                return AuthUser(
                    user_id=response.user.id,
                    email=response.user.email
                )
            return None
        except Exception:
            return None

    @classmethod
    def get_current_user(cls) -> Optional[AuthUser]:
        """Get current authenticated user from request."""
        token = cls.get_token_from_header()
        if not token:
            return None
        return cls.verify_token(token)


def require_auth(f):
    """Decorator to require authentication for routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Skip auth in development if not configured
        if not is_supabase_available():
            return f(*args, **kwargs)

        token = AuthService.get_token_from_header()
        if not token:
            return jsonify({'error': 'Missing authorization token'}), 401

        user = AuthService.verify_token(token)
        if not user:
            return jsonify({'error': 'Invalid or expired token'}), 401

        # Add user info to request context
        request.user_id = user.user_id
        request.user_email = user.email

        return f(*args, **kwargs)
    return decorated


def optional_auth(f):
    """Decorator for optional authentication - doesn't fail if no token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = AuthService.get_current_user()

        if user:
            request.user_id = user.user_id
            request.user_email = user.email
        else:
            request.user_id = None
            request.user_email = None

        return f(*args, **kwargs)
    return decorated
