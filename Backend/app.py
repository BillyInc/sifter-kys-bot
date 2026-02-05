"""Flask application factory and entry point."""
import os
from datetime import datetime, timedelta
import json

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import Config
from routes import analyze_bp, watchlist_bp, health_bp, wallets_bp, telegram_bp


def get_rate_limit_key():
    """Get rate limit key - prefer user ID from auth, fallback to IP."""
    user_id = getattr(request, 'user_id', None)
    if user_id:
        return f"user:{user_id}"
    return get_remote_address()


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    CORS(app, supports_credentials=True)

    # Initialize rate limiter
    limiter = Limiter(
        key_func=get_rate_limit_key,
        app=app,
        default_limits=Config.RATELIMIT_DEFAULT,
        storage_uri=Config.RATELIMIT_STORAGE_URI,
        strategy=Config.RATELIMIT_STRATEGY
    )

    # Register blueprints
    app.register_blueprint(analyze_bp)
    app.register_blueprint(watchlist_bp)
    app.register_blueprint(wallets_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(telegram_bp)

    # Apply rate limits to specific endpoints
    _apply_rate_limits(limiter)

    # Register error handlers
    _register_error_handlers(app)

    return app


def _apply_rate_limits(limiter: Limiter):
    """Apply rate limits to endpoints."""
    # Analyze endpoint - stricter limits
    limiter.limit(
        Config.ANALYZE_RATE_LIMIT_HOUR,
        error_message="Analysis rate limit exceeded. Max 5 analyses per hour."
    )(analyze_bp)
    limiter.limit(
        Config.ANALYZE_RATE_LIMIT_DAY,
        error_message="Daily analysis limit exceeded. Max 20 analyses per day."
    )(analyze_bp)

    # Watchlist write endpoints
    limiter.limit(Config.WATCHLIST_WRITE_LIMIT)(
        watchlist_bp
    )

    # Wallet endpoints - similar limits to analyze
    limiter.limit(Config.ANALYZE_RATE_LIMIT_HOUR)(wallets_bp)

    # Health endpoint exempt from rate limiting
    limiter.exempt(health_bp)

    # Telegram webhook exempt from rate limiting (needs to be fast)
    limiter.exempt(telegram_bp)


def _register_error_handlers(app: Flask):
    """Register error handlers."""

    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({
            'error': 'Rate limit exceeded',
            'message': str(e.description),
            'retry_after': e.description
        }), 429

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({
            'error': 'Internal server error',
            'message': str(e)
        }), 500


def print_startup_banner():
    """Print startup banner with configuration status."""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║   SIFTER KYS API SERVER v7.0 - AUTH + WALLET + TELEGRAM         ║
╚══════════════════════════════════════════════════════════════════╝

Features:
  - Supabase JWT Authentication
  - Rate limiting (per-user and per-IP)
  - Twitter caller analysis
  - Wallet analysis with ATH scoring
  - Real-time wallet activity monitoring
  - Telegram alerts integration

Rate Limits:
  - /api/analyze: 5/hour, 20/day
  - /api/wallets/*: 5/hour
  - /api/watchlist/*: 30-60/hour
  - /api/telegram/*: exempt (webhook)
  - Default: 50/hour, 200/day

Configuration Status:
""")

    if Config.is_twitter_configured():
        print(f"  [OK] Twitter API: Configured ({Config.TWITTER_BEARER_TOKEN[:10]}...)")
    else:
        print("  [!]  Twitter API: NOT CONFIGURED (caller analysis will be skipped)")

    if Config.is_birdeye_configured():
        print(f"  [OK] Birdeye API: Configured ({Config.BIRDEYE_API_KEY[:10]}...)")
    else:
        print("  [X]  Birdeye API: NOT CONFIGURED")

    if Config.is_supabase_configured():
        print("  [OK] Supabase Auth: Configured")
    else:
        print("  [!]  Supabase Auth: NOT CONFIGURED (auth middleware disabled)")

    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if telegram_token:
        print(f"  [OK] Telegram Bot: Configured ({telegram_token[:10]}...)")
    else:
        print("  [!]  Telegram Bot: NOT CONFIGURED (alerts disabled)")


# Create the application instance
app = create_app()


if __name__ == '__main__':
    print_startup_banner()

    port = int(os.environ.get("PORT", 5000))
    print(f"\nStarting server on http://localhost:{port}\n")

    app.run(debug=True, host='0.0.0.0', port=port)
