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

    print(f"\n  ✅ Found {len(smart_money)} smart money wallets")

    return jsonify({
        'success': True,
        'smart_money_wallets': smart_money[:50],
        'total_wallets': len(smart_money),
        'runners_scanned': len(runners_to_analyze),
        'analysis_type': 'professional_auto_discovery_6step',
        'features': {
            'batch_analysis': True,
            'consistency_grading': True,
            'variance_scoring': True,
            'cross_runner_tracking': True,
            'batch_separation': True,
            '30day_dropdown': True,
            'birdeye_depth': True
        },
        'criteria': {
            'min_multiplier': 5.0,
            'min_liquidity': 50000,
            'days_back': days_back,
            'min_runner_hits': min_runner_hits
        }
    }), 200

# =============================================================================
# MAIN ANALYZE ROUTE
# =============================================================================

@app.route('/api/wallets/analyze', methods=['POST'])
def analyze_wallets():
    """
    MAIN ANALYSIS ROUTE
    Routes to:
    - Single token: analyze_token_professional
    - Multiple tokens: batch_analyze_runners_professional
    """
    try:
        data = request.json
        
        if not data.get('tokens'):
            return jsonify({'error': 'tokens array required'}), 400
        
        tokens = data['tokens']
        global_settings = data.get('global_settings', {})
        user_id = data.get('user_id', 'default_user')
        
        mode = global_settings.get('mode', 'general')
        min_roi_multiplier = global_settings.get('min_roi_multiplier', 3.0)
        
        if wallet_analyzer is None:
            initialize_wallet_analyzer()
        
        # Single token: use analyze_token_professional
        if len(tokens) == 1:
            token = tokens[0]
            
            print(f"\n{'='*80}")
            print(f"SINGLE TOKEN ANALYSIS (6-STEP): {token['ticker']}")
            print(f"{'='*80}")
            
            wallets = wallet_analyzer.analyze_token_professional(
                token_address=token['address'],
                token_symbol=token['ticker'],
                min_roi_multiplier=min_roi_multiplier,
                user_id=user_id
            )
            
            return jsonify({
                'success': True,
                'summary': {
                    'tokens_analyzed': 1,
                    'qualified_wallets': len(wallets),
                    'min_roi_used': min_roi_multiplier,
                    'avg_professional_score': round(sum(w['professional_score'] for w in wallets)/len(wallets) if wallets else 0, 2),
                    'a_plus_wallets': sum(1 for w in wallets if w.get('professional_grade') == 'A+')
                },
                'top_wallets': wallets[:100],
                'settings': {
                    'mode': 'professional_single_6step',
                    'features': {
                        'professional_scoring': '60% Timing, 30% Profit, 10% Overall',
                        '30day_runner_tracking': True,
                        'dropdown_data': True,
                        'birdeye_depth': True
                    }
                }
            }), 200
        
        # Multiple tokens: batch analysis
        print(f"\n{'='*80}")
        print(f"BATCH ANALYSIS: {len(tokens)} tokens")
        print(f"{'='*80}")
        
        return _analyze_general_mode_professional(tokens, min_roi_multiplier, user_id)
        
    except Exception as e:
        print(f"\n[MAIN ANALYSIS ERROR] {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# =============================================================================
# AUTO DISCOVERY ROUTE
# =============================================================================

@app.route('/api/discover/wallets', methods=['POST'])
def auto_discover_wallets():
    """Auto discovery with 6-step batch analysis"""
    try:
        data = request.json or {}
        user_id = data.get('user_id', 'default_user')
        min_runner_hits = data.get('min_runner_hits', 2)
        days_back = data.get('days_back', 30)
        
        print(f"\n{'='*80}")
        print(f"AUTO DISCOVERY (6-STEP BATCH)")
        print(f"{'='*80}")
        
        return _auto_discover_wallets_professional(user_id, min_runner_hits, days_back)
        
    except Exception as e:
        print(f"\n[AUTO DISCOVERY ERROR] {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# =============================================================================
# WATCHLIST ENDPOINTS (unchanged - keeping for reference)
# =============================================================================

@app.route('/api/watchlist/get', methods=['GET'])
def get_twitter_watchlist_route():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        accounts = watchlist_db.get_watchlist(user_id)
        return jsonify({'success': True, 'accounts': accounts}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wallets/watchlist/get', methods=['GET'])
def get_wallet_watchlist_route():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        wallets = watchlist_db.get_wallet_watchlist(user_id)
        return jsonify({'success': True, 'wallets': wallets}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wallets/watchlist/add', methods=['POST'])
def add_wallet_to_watchlist_route():
    try:
        data = request.json
        user_id = data.get('user_id')
        wallet = data.get('wallet')
        alert_settings = data.get('alert_settings', {})
        
        if not user_id or not wallet:
            return jsonify({'error': 'user_id and wallet required'}), 400
        
        wallet_address = wallet.get('wallet_address')
        if not wallet_address:
            return jsonify({'error': 'wallet.wallet_address required'}), 400
        
        wallet['alert_settings'] = alert_settings
        watchlist_db.add_wallet_to_watchlist(user_id, wallet)
        
        if alert_settings.get('alert_enabled') and wallet_monitor:
            wallet_monitor.add_watched_wallet(
                user_id=user_id,
                wallet_address=wallet_address,
                alert_settings=alert_settings
            )
        
        return jsonify({'success': True, 'message': 'Wallet added to watchlist'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    # Add these after your existing watchlist endpoints (around line 600-700)

# =============================================================================
# PREMIER LEAGUE WATCHLIST ENDPOINTS
# =============================================================================

@app.route('/api/wallets/watchlist/table', methods=['GET'])
def get_watchlist_table():
    """Get Premier League-style watchlist table"""
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        table_data = watchlist_db.get_premier_league_table(user_id)
        
        return jsonify({
            'success': True,
            'table': table_data['wallets'],
            'promotion_queue': table_data['promotion_queue'],
            'stats': table_data['stats']
        }), 200
        
    except Exception as e:
        print(f"Error getting watchlist table: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/wallets/watchlist/suggest-replacement', methods=['POST'])
def suggest_replacement():
    """Find replacement wallets for degrading wallet"""
    try:
        data = request.json
        user_id = data.get('user_id')
        wallet_address = data.get('wallet_address')
        min_score = data.get('min_professional_score', 85)
        
        if not user_id or not wallet_address:
            return jsonify({'error': 'user_id and wallet_address required'}), 400
        
        if wallet_analyzer is None:
            initialize_wallet_analyzer()
        
        replacements = wallet_analyzer.find_replacement_wallets(
            declining_wallet_address=wallet_address,
            user_id=user_id,
            min_professional_score=min_score,
            max_results=3
        )
        
        return jsonify({
            'success': True,
            'replacements': replacements,
            'count': len(replacements)
        }), 200
        
    except Exception as e:
        print(f"[REPLACEMENT FINDER ERROR] {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/wallets/watchlist/replace', methods=['POST'])
def replace_wallet():
    """Replace degrading wallet with new one"""
    try:
        data = request.json
        user_id = data.get('user_id')
        old_wallet = data.get('old_wallet')
        new_wallet_data = data.get('new_wallet')
        
        if not all([user_id, old_wallet, new_wallet_data]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Remove old wallet
        watchlist_db.remove_wallet_from_watchlist(user_id, old_wallet)
        
        # Add new wallet
        watchlist_db.add_wallet_to_watchlist(user_id, {
            'wallet_address': new_wallet_data['wallet'],
            'tier': new_wallet_data.get('tier', 'C'),
            'pump_count': new_wallet_data.get('runner_hits_30d', 0),
            'avg_roi_to_peak': new_wallet_data.get('roi_multiplier', 0) * 100,
            'consistency_score': new_wallet_data.get('consistency_score', 0)
        })
        
        return jsonify({
            'success': True,
            'message': 'Wallet replaced successfully',
            'old_wallet': old_wallet,
            'new_wallet': new_wallet_data['wallet']
        }), 200
        
    except Exception as e:
        print(f"Error replacing wallet: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    if wallet_monitor is None:
        initialize_wallet_monitor()
    
    monitor_stats = wallet_monitor.get_monitoring_stats()

    # ✨ NEW: Telegram status
    telegram_status = {
        'enabled': telegram_notifier is not None,
        'bot_token_set': bool(TELEGRAM_BOT_TOKEN)
    }

    return jsonify({
        'status': 'healthy',
        'version': '17.0.0 - CORRECTED 6-STEP + TELEGRAM',
        'features': {
            'six_step_analysis': True,
            'professional_scoring': True,
            '30day_runner_tracking': True,
            'consistency_grading': True,
            'birdeye_depth': True,
            'trending_runners': True,
            'auto_discovery': True,
            'real_time_monitoring': True,
            'telegram_alerts': telegram_status['enabled']  # ✨ ADD THIS
        },
        'wallet_monitor': {
            'running': monitor_stats['running'],
            'active_wallets': monitor_stats['active_wallets'],
            'pending_notifications': monitor_stats['pending_notifications']
        },
        'telegram': telegram_status,  # ✨ ADD THIS
        'analysis_pipeline': {
            'step_1': 'Top traders + first buy timestamps',
            'step_2': 'First buyers + entry prices',
            'step_3': 'Birdeye historical trades (30 days)',
            'step_4': 'Recent Solana Tracker trades',
            'step_5': 'PnL filtering (≥3x ROI, ≥$100 invested)',
            'step_6': 'Professional scoring (60/30/10)'
        },
        'data_sources': {
            'solana_tracker': ['top-traders', 'first-buyers', 'trades', 'pnl', 'ath'],
            'birdeye': ['historical trades (30-day depth)']
        }
    })

# =============================================================================
# STARTUP
# =============================================================================

if __name__ == '__main__':
    print_startup_banner()

    port = int(os.environ.get("PORT", 5000))
    print(f"\nStarting server on http://localhost:{port}\n")

    app.run(debug=True, host='0.0.0.0', port=port)
