"""Routes module for Flask blueprints."""
from .analyze import analyze_bp
from .watchlist import watchlist_bp
from .health import health_bp
from .wallets import wallets_bp
from .telegram import telegram_bp
from .support import support_bp
from .user_settings import user_settings_bp
from .whop_webhook import whop_bp
from .referral_points_routes import referral_points_bp
from .auth import auth_bp
from .token_routes import tokens_bp
from .recents import recents_bp

__all__ = [
    'analyze_bp',
    'watchlist_bp',
    'health_bp',
    'wallets_bp',
    'telegram_bp',
    'support_bp',
    'user_settings_bp',
    'whop_bp',
    'referral_points_bp',
    'auth_bp',
    'tokens_bp',
    'recents_bp',
]