"""Flask application factory and entry point."""
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config
from routes import analyze_bp, watchlist_bp, health_bp, wallets_bp, telegram_bp
from rq import Queue
from redis import Redis
telegram_polling_started = False


def get_rate_limit_key():
    """Get rate limit key - prefer user ID from auth, fallback to IP."""
    user_id = getattr(request, 'user_id', None)
    if user_id:
        return f"user:{user_id}"
    return get_remote_address()




def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    CORS(app, supports_credentials=True, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })
    
   
    # Initialize rate limiter
    limiter = Limiter(
        key_func=get_rate_limit_key,
        app=app,
        default_limits=Config.RATELIMIT_DEFAULT,
        storage_uri=Config.RATELIMIT_STORAGE_URI,
        strategy=Config.RATELIMIT_STRATEGY
    )
    
    
    from services.telegram_notifier import TelegramNotifier
    TELEGRAM_BOT_TOKEN = "8338094173:AAEv_xAXoCi0RFNT6eVYIfejIPTnHOsI_sk"
    telegram_notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
    app.config['TELEGRAM_NOTIFIER'] = telegram_notifier
    
    if telegram_notifier:
        print("\n[TELEGRAM] ✅ Notifier initialized")
        print("[TELEGRAM] Bot: @SifterDueDiligenceBot")
    else:
        print("\n[TELEGRAM] ⚠️ Notifier disabled (no token)")

    # Register blueprints
    app.register_blueprint(analyze_bp)
    app.register_blueprint(watchlist_bp)
    app.register_blueprint(wallets_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(telegram_bp)
    
    redis_conn = Redis(host='localhost', port=6379, db=0)
    app.config['RQ_QUEUE'] = Queue(connection=redis_conn, default_timeout=600)

    # Apply rate limits
    _apply_rate_limits(limiter)
    _register_error_handlers(app)

    return app





# ✅ MOVE preload_trending_cache OUTSIDE create_app (before create_app definition)
def preload_trending_cache():
    """Preload trending runners cache on startup"""
    try:
        print("\n[CACHE WARMUP] Preloading trending runners...")
        from routes.wallets import get_wallet_analyzer
        
        analyzer = get_wallet_analyzer()
        
        # Preload common timeframes with error handling
        for days_back in [7, 14]:
            try:
                print(f"  → Warming {days_back}d cache...")
                runners = analyzer.find_trending_runners_enhanced(
                    days_back=days_back,
                    min_multiplier=5.0,
                    min_liquidity=50000
                )
                print(f"  ✓ {days_back}d: {len(runners)} runners")
                for runner in runners[:5]:
                    analyzer.analyze_token_professional(runner['address'])
            except Exception as e:
                print(f"  ⚠️ {days_back}d cache failed: {e}")
                continue  # Don't crash - continue to next timeframe
        
        print("  ✅ Cache warmup complete\n")
    except Exception as e:
        print(f"  ⚠️ Cache warmup failed: {e}\n")
        # Don't crash the server - just log and continue


def _apply_rate_limits(limiter: Limiter):
    """Apply rate limits to endpoints."""
    limiter.limit(Config.ANALYZE_RATE_LIMIT_HOUR, error_message="Analysis rate limit exceeded.")(analyze_bp)
    limiter.limit(Config.ANALYZE_RATE_LIMIT_DAY, error_message="Daily analysis limit exceeded.")(analyze_bp)
    limiter.limit(Config.WATCHLIST_WRITE_LIMIT)(watchlist_bp)
    limiter.limit(Config.ANALYZE_RATE_LIMIT_HOUR)(wallets_bp)
    limiter.exempt(health_bp)
    limiter.exempt(telegram_bp)


def _register_error_handlers(app: Flask):
    """Register error handlers."""
    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({'error': 'Rate limit exceeded', 'message': str(e.description)}), 429

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500


def print_startup_banner():
    """Print startup banner."""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║   SIFTER KYS API SERVER v7.0 - AUTH + WALLET + TELEGRAM         ║
╚══════════════════════════════════════════════════════════════════╝
""")
    # ... rest of banner ...


# Create app instance
app = create_app()


@app.before_request
def setup_telegram():
    """Setup Telegram but don't auto-start polling"""
    global telegram_polling_started
    if not telegram_polling_started and app.config.get('TELEGRAM_NOTIFIER'):
        telegram_polling_started = True
        print("[TELEGRAM] ✅ Notifier ready (polling disabled for now)")
        
if __name__ == '__main__':
    print_startup_banner()
    
    # ✅ Only preload cache if NOT in reloader process
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        preload_trending_cache()
    
    port = int(os.environ.get("PORT", 5000))
    print(f"\nStarting server on http://localhost:{port}\n")
    app.run(debug=True, host='0.0.0.0', port=port)