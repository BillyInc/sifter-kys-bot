"""Flask application factory and entry point."""
import os
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config
from routes import analyze_bp, watchlist_bp, health_bp, wallets_bp, telegram_bp
from rq import Queue
from redis import Redis
from routes import support_bp
from routes import user_settings_bp
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from routes import whop_bp
from routes import referral_points_bp
from routes import auth_bp
from routes import tokens_bp


telegram_polling_started = False


def get_rate_limit_key():
    """Get rate limit key - prefer user ID from auth, fallback to IP."""
    user_id = getattr(request, 'user_id', None)
    if user_id:
        return f"user:{user_id}"
    return get_remote_address()


def init_scheduler(app):
    """Initialize background scheduler for cron jobs"""
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        func=lambda: run_cron_job(app, 'daily'),
        trigger=CronTrigger(hour=3, minute=0),
        id='daily_stats_refresh',
        name='Daily stats refresh',
        replace_existing=True
    )

    scheduler.add_job(
        func=lambda: run_cron_job(app, 'weekly'),
        trigger=CronTrigger(day_of_week='sun', hour=4, minute=0),
        id='weekly_rerank',
        name='Weekly rerank',
        replace_existing=True
    )

    scheduler.add_job(
        func=lambda: run_cron_job(app, 'four_week'),
        trigger=CronTrigger(day='*/28', hour=5, minute=0),
        id='four_week_check',
        name='4-week degradation check',
        replace_existing=True
    )

    scheduler.start()
    print("[SCHEDULER] ✅ Background jobs scheduled")
    print("  - Daily refresh: 3am UTC")
    print("  - Weekly rerank: Sunday 4am UTC")
    print("  - 4-week check: Every 28 days at 5am UTC")

    return scheduler


def run_cron_job(app, job_type):
    """Run cron job with app context"""
    with app.app_context():
        from services.watchlist_stats_updater import get_updater
        updater = get_updater()

        if job_type == 'daily':
            updater.daily_stats_refresh()
        elif job_type == 'weekly':
            updater.weekly_rerank_all()
        elif job_type == 'four_week':
            updater.four_week_degradation_check()


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    CORS(app, resources={
        r"/*": {
            "origins": ["http://localhost:5173", "http://localhost:3000", "https://sifter-kys-bot.onrender.com"],
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
            "allow_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True,
            "expose_headers": ["Content-Type", "Authorization"]
        }
    })

    limiter = Limiter(
        key_func=get_rate_limit_key,
        app=app,
        default_limits=Config.RATELIMIT_DEFAULT,
        storage_uri=Config.RATELIMIT_STORAGE_URI,
        strategy=Config.RATELIMIT_STRATEGY,
        enabled=False
    )

    from services.telegram_notifier import TelegramNotifier
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "8338094173:AAEv_xAXoCi0RFNT6eVYIfejIPTnHOsI_sk")
    telegram_notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
    app.config['TELEGRAM_NOTIFIER'] = telegram_notifier

    if telegram_notifier:
        print("\n[TELEGRAM] ✅ Notifier initialized")
    else:
        print("\n[TELEGRAM] ⚠️ Notifier disabled (no token)")

    # Register blueprints
    app.register_blueprint(analyze_bp)
    app.register_blueprint(watchlist_bp)
    app.register_blueprint(wallets_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(telegram_bp, url_prefix='/api/telegram')
    app.register_blueprint(support_bp)
    app.register_blueprint(user_settings_bp)
    app.register_blueprint(whop_bp)
    app.register_blueprint(referral_points_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(tokens_bp)

    redis_conn = Redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))
    app.config['RQ_QUEUE'] = Queue(connection=redis_conn, default_timeout=600)

    app.config['SCHEDULER'] = init_scheduler(app)

    _apply_rate_limits(limiter)
    _register_error_handlers(app)

    def run_startup_tasks(app_instance):
        with app_instance.app_context():
            print("\n[SYSTEM] 🚀 Bootstrapping background services...")
            preload_trending_cache()
            start_wallet_monitoring()

    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        startup_thread = threading.Thread(target=run_startup_tasks, args=(app,), daemon=True)
        startup_thread.start()

    return app


def preload_trending_cache():
    """
    Queue lightweight runner list warmup jobs only.
    Does NOT run full 6-step analysis on startup.
    Full analysis only runs when user clicks Analyze.
    Saves ~300 credits per boot on free tier.
    """
    try:
        print("[CACHE WARMUP] Queuing runner list warmup (7d + 14d)...")
        from services.worker_tasks import preload_trending_cache as _warmup
        _warmup()
        print("  ✅ Warmup jobs queued")
    except Exception as e:
        print(f"  ⚠️ Cache warmup failed: {e}")


def start_wallet_monitoring():
    """
    Start background wallet monitoring.
    WalletActivityMonitor takes solanatracker_api_key (NOT birdeye_api_key).
    """
    try:
        print("\n[WALLET MONITORING] Starting real-time monitoring...")
        from services.wallet_monitor import WalletActivityMonitor
        from config import Config
        from flask import current_app
        telegram_notifier = current_app.config.get('TELEGRAM_NOTIFIER')

        # ✅ CORRECT: pass solanatracker_api_key, not birdeye_api_key
        monitor = WalletActivityMonitor(
            solanatracker_api_key=Config.SOLANATRACKER_API_KEY,
            poll_interval=120,
            telegram_notifier=telegram_notifier
        )
        current_app.config['WALLET_MONITOR'] = monitor
        monitor.start()
        print("  ✅ Wallet monitoring started (polling every 2 minutes)\n")
    except Exception as e:
        print(f"  ⚠️ Monitoring start failed: {e}\n")
        import traceback
        traceback.print_exc()


def _apply_rate_limits(limiter: Limiter):
    limiter.limit(Config.ANALYZE_RATE_LIMIT_HOUR)(analyze_bp)
    limiter.limit(Config.ANALYZE_RATE_LIMIT_DAY)(analyze_bp)
    limiter.limit(Config.WATCHLIST_WRITE_LIMIT)(watchlist_bp)
    limiter.limit(Config.ANALYZE_RATE_LIMIT_HOUR)(wallets_bp)
    limiter.exempt(health_bp)
    limiter.exempt(telegram_bp)


def _register_error_handlers(app: Flask):
    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({'error': 'Rate limit exceeded', 'message': str(e.description)}), 429

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500


def print_startup_banner():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║   SIFTER KYS API SERVER v7.0 - AUTH + WALLET + TELEGRAM          ║
╚══════════════════════════════════════════════════════════════════╝
    """)


app = create_app()

if __name__ == '__main__':
    print_startup_banner()
    port = int(os.environ.get("PORT", 5000))
    print(f"\nStarting server on http://localhost:{port}\n")
    app.run(debug=True, host='0.0.0.0', port=port)