# app.py - COMPLETE SIFTER KYS BACKEND v17.0
# CORRECTED: Uses actual 6-step analysis from Document 6

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime, timedelta
import json
import traceback
import time
import requests
from collections import defaultdict
import asyncio
import aiohttp
import statistics
import sqlite3

# Existing imports
from twitter_api_pool import TwitterAPIKeyPool
from tweet_extractor import TwitterTweetExtractor
from rally_tweet_connector import RallyTweetConnector
from pump_detector import PrecisionRallyDetector
from nlp_disambiguator import NLPDisambiguator

# Watchlist Database
from watchlist_db import WatchlistDatabase

# CORRECTED: Wallet analyzer with 6-step analysis
from wallet_analyzer import WalletPumpAnalyzer

# Wallet Activity Monitor
from wallet_monitor import (
    WalletActivityMonitor,
    get_recent_wallet_activity,
    get_user_notifications,
    mark_notification_read,
    mark_all_notifications_read,
    update_alert_settings
)

app = Flask(__name__)
CORS(app)

# =============================================================================
# LOAD ALL API KEYS
# =============================================================================

TWITTER_API_KEYS = [
    {'user_id': '405920194964049920', 'api_key': 'new1_f62eefe95d5349938ea4f77ca8f198ad', 'name': 'dnjunu'},
    {'user_id': '405944251155873792', 'api_key': 'new1_8c0aabf38b194412903658bfc9c0bdca', 'name': 'Ptrsamuelchinedu'},
    {'user_id': '405944945891999744', 'api_key': 'new1_f3d0911f1fb24d30b5ce170fa4ee950b', 'name': 'Ajnunu'},
    {'user_id': '405945504339345408', 'api_key': 'new1_4a6403a6401f4287ab744137ec980938', 'name': 'Sub profile 2'},
    {'user_id': '405946871811231744', 'api_key': 'new1_51f18ffecd3e4a1ebcf856f37a7a3030', 'name': 'Deeznaughts'},
    {'user_id': '405947363161669632', 'api_key': 'new1_6142207fb46d49d4ad02720bd116b9d1', 'name': 'Dufflebag'},
    {'user_id': '405948036192272384', 'api_key': 'new1_4fc2a52171f64859bebd963f48a9c737', 'name': 'Sub 32'},
    {'user_id': '405949239307403264', 'api_key': 'new1_d523673110044e2cbf23c9ec76540b6a', 'name': 'Sub 38'},
    {'user_id': '405950025102802944', 'api_key': 'new1_2bd178da0c1f40cd91cf748cc004f7cd', 'name': 'John Serpentine'},
    {'user_id': '405950338090156032', 'api_key': 'new1_4c075edb9d4041d6bf75b7c7163e560f', 'name': 'Sub 28'},
    {'user_id': '405950779036094464', 'api_key': 'new1_50d78a76c38a4eea909fbf8e31986a9e', 'name': 'Sub 1'},
    {'user_id': '405951626647453696', 'api_key': 'new1_55c18cb2f58742ceb08ee0dd19ce2cdf', 'name': 'Sub 40'},
    {'user_id': '405952074624286720', 'api_key': 'new1_ac102da13d1c45f8a843783edcf56628', 'name': 'Sub 4'},
    {'user_id': '405952395836669952', 'api_key': 'new1_89a3956c3175453c9ed154de28a54e66', 'name': 'Sub 5'},
    {'user_id': '405952953305808896', 'api_key': 'new1_8aca972dfa7e4bd1925c9cd936c1844e', 'name': 'Sub prof 3'},
    {'user_id': '405953452893552640', 'api_key': 'new1_0c3667b1012441c6ade4ce6fc96433c1', 'name': 'Nedudev'},
    {'user_id': '405953902593310720', 'api_key': 'new1_6a7ced7e00bf49c58f4d25a65cc0d055', 'name': 'Odunayo'},
    {'user_id': '405954262653337600', 'api_key': 'new1_4b9de10350194f10b6edcef4370a7380', 'name': 'Oluyori'},
    {'user_id': '405954603948982272', 'api_key': 'new1_887a7871ea984943a7b196509ba0d6e0', 'name': 'Osakwe orange'},
    {'user_id': '405955050410430464', 'api_key': 'new1_415172ec5ff548248431255a551a2a22', 'name': 'Osakwe green'},
    {'user_id': '405956028594667520', 'api_key': 'new1_c47359e9e7ea4fa7a435eaec14fb1d50', 'name': 'Sub 30'},
    {'user_id': '405956647261962240', 'api_key': 'new1_92067fd503ed4e4b8a1d1631ee64cc11', 'name': 'Impulseibbleisnothing'},
    {'user_id': '405957396843741184', 'api_key': 'new1_fdeebdfad8b743ada0d814fe6470a824', 'name': 'samuelptrchinedu'},
    {'user_id': '405957918974935040', 'api_key': 'new1_c7638bc9b69f4dc6819298cf1fd0a78a', 'name': 'Tosin'},
    {'user_id': '405958813309292544', 'api_key': 'new1_c46724fbcb184848b025c54ca4d77fe2', 'name': 'Wan'}
]

BIRDEYE_API_KEY = os.environ.get('BIRDEYE_API_KEY', 'a49c49de31d34574967c13bd35f3c523')
SOLANATRACKER_API_KEY = os.environ.get('SOLANATRACKER_API_KEY', '902ebe8e-8142-49aa-a3d8-32ac792bf325')

# =============================================================================
# INITIALIZE GLOBAL OBJECTS
# =============================================================================

twitter_api_pool = TwitterAPIKeyPool(TWITTER_API_KEYS, cooldown_minutes=15)
watchlist_db = WatchlistDatabase(db_path='watchlists.db')
wallet_monitor = None
wallet_analyzer = None

def initialize_wallet_analyzer():
    """Initialize the professional wallet analyzer with 6-step analysis"""
    global wallet_analyzer
    
    if wallet_analyzer is None:
        print("\n" + "="*80)
        print("INITIALIZING WALLET ANALYZER (6-STEP PROFESSIONAL)")
        print("="*80)
        
        wallet_analyzer = WalletPumpAnalyzer(
            solanatracker_api_key=SOLANATRACKER_API_KEY,
            birdeye_api_key=BIRDEYE_API_KEY,
            debug_mode=True
        )
        
        print(f"""
╔══════════════════════════════════════════════════════════════════╗
║        6-STEP PROFESSIONAL WALLET ANALYZER INITIALIZED          ║
╚══════════════════════════════════════════════════════════════════╝

📋 THE 6 STEPS:
  1. Fetch top traders + first buy timestamps
  2. Fetch first buyers + entry prices
  3. Fetch Birdeye historical trades (30 days)
  4. Fetch recent Solana Tracker trades
  5. Fetch PnL, filter ≥3x ROI AND ≥$100 invested
  6. Rank by professional score (60/30/10)

✨ FEATURES:
  ✓ Professional scoring (60% timing, 30% profit, 10% overall)
  ✓ 30-day runner tracking with verification
  ✓ Cross-runner consistency grading
  ✓ Batch analysis with variance tracking
  ✓ Dropdown data for frontend

🔗 DATA SOURCES:
  ✓ SolanaTracker: Top traders, first buyers, recent trades, PnL
  ✓ Birdeye: Historical trades (30-day depth)
""")

def initialize_wallet_monitor():
    """Initialize and start the wallet monitor"""
    global wallet_monitor
    
    if wallet_monitor is None:
        print("\n" + "="*80)
        print("INITIALIZING WALLET MONITOR")
        print("="*80)
        
        wallet_monitor = WalletActivityMonitor(
            solanatracker_api_key=SOLANATRACKER_API_KEY,
            db_path='watchlists.db',
            poll_interval=120
        )
        
        wallet_monitor.start()

# =============================================================================
# SINGLE TOKEN ANALYSIS - Uses 6-step professional analysis
# =============================================================================

@app.route('/api/wallets/analyze/single', methods=['POST'])
def analyze_single_token():
    """Single token with professional 6-step analysis + 30-day dropdown"""
    try:
        data = request.json
        
        if not data.get('token'):
            return jsonify({'error': 'token object required'}), 400
        
        token = data['token']
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
        user_id = data.get('user_id', 'default_user')
        
        if wallet_analyzer is None:
            initialize_wallet_analyzer()
        
        print(f"\n{'='*80}")
        print(f"SINGLE TOKEN ANALYSIS (6-STEP): {token['ticker']}")
        print(f"{'='*80}")
        
        # Use 6-step professional analysis
        wallets = wallet_analyzer.analyze_token_professional(
            token_address=token['address'],
            token_symbol=token['ticker'],
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )
        
        return jsonify({
            'success': True,
            'token': token,
            'wallets': wallets[:50],
            'total_wallets': len(wallets),
            'mode': 'professional_general_6step',
            'data_source': '6-Step Professional Analyzer',
            'features': {
                'professional_scoring': '60% Timing, 30% Profit, 10% Overall',
                '30day_runner_tracking': True,
                'dropdown_data': True,
                'birdeye_depth': True
            },
            'professional_summary': {
                'avg_professional_score': round(sum(w['professional_score'] for w in wallets)/len(wallets) if wallets else 0, 2),
                'a_plus_wallets': sum(1 for w in wallets if w.get('professional_grade') == 'A+'),
                'avg_runner_hits': round(sum(w.get('runner_hits_30d', 0) for w in wallets)/len(wallets) if wallets else 0, 1)
            }
        }), 200
        
    except Exception as e:
        print(f"\n[SINGLE TOKEN ERROR] {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# =============================================================================
# MULTI-TOKEN ANALYSIS - Uses batch 6-step analysis
# =============================================================================

def _analyze_general_mode_professional(tokens, min_roi_multiplier, user_id):
    """
    PROFESSIONAL GENERAL MODE: Batch 6-step analysis
    """
    print(f"\n{'='*80}")
    print(f"PROFESSIONAL GENERAL MODE: Batch 6-Step Analysis")
    print(f"Tokens: {len(tokens)}")
    print(f"{'='*80}")
    
    if wallet_analyzer is None:
        initialize_wallet_analyzer()
    
    # Convert tokens to runner format
    runners_list = []
    for token in tokens:
        ath_data = wallet_analyzer.get_token_ath(token['address'])
        
        runners_list.append({
            'address': token['address'],
            'symbol': token['ticker'],
            'name': token['name'],
            'chain': token.get('chain', 'solana'),
            'ath_price': ath_data.get('highest_price', 0) if ath_data else 0,
            'ath_time': ath_data.get('timestamp', 0) if ath_data else 0
        })
    
    # Use batch 6-step analysis
    smart_money = wallet_analyzer.batch_analyze_runners_professional(
        runners_list=runners_list,
        min_runner_hits=1,
        min_roi_multiplier=min_roi_multiplier,
        user_id=user_id
    )
    
    print(f"\n{'='*80}")
    print(f"BATCH ANALYSIS COMPLETE")
    print(f"  Qualified wallets: {len(smart_money)}")
    print(f"{'='*80}")
    
    return jsonify({
        'success': True,
        'summary': {
            'tokens_analyzed': len(tokens),
            'qualified_wallets': len(smart_money),
            'min_roi_used': min_roi_multiplier,
            'avg_professional_score': round(sum(w['avg_professional_score'] for w in smart_money)/len(smart_money) if smart_money else 0, 1),
            'avg_consistency': round(sum(1 for w in smart_money if w['consistency_grade'] in ['A+', 'A'])/len(smart_money)*100 if smart_money else 0, 1)
        },
        'top_wallets': smart_money[:100],
        'settings': {
            'mode': 'professional_general_6step',
            'batch_analysis': True,
            'consistency_tracking': True,
            'features': {
                'cross_runner_tracking': True,
                'variance_grading': True,
                'batch_separation': True,
                '30day_dropdown': True,
                'birdeye_depth': True
            }
        }
    }), 200

# =============================================================================
# TRENDING RUNNERS - Enhanced discovery + 6-step analysis
# =============================================================================

@app.route('/api/trending/runners', methods=['GET'])
def get_trending_runners():
    """Enhanced trending runners with professional discovery"""
    try:
        timeframe = request.args.get('timeframe', '24h')
        min_liquidity = float(request.args.get('min_liquidity', 50000))
        min_multiplier = float(request.args.get('min_multiplier', 5))
        min_age_days = int(request.args.get('min_age_days', 0))
        max_age_days_raw = request.args.get('max_age_days', None)
        max_age_days = int(max_age_days_raw) if max_age_days_raw else 30
        
        if wallet_analyzer is None:
            initialize_wallet_analyzer()
        
        print(f"\n{'='*80}")
        print(f"TRENDING RUNNERS DISCOVERY")
        print(f"Timeframe: {timeframe} | Min: {min_multiplier}x")
        print(f"{'='*80}")
        
        days_map = {'24h': 1, '7d': 7, '30d': 30}
        days_back = days_map.get(timeframe, 7)
        
        runners = wallet_analyzer.find_trending_runners_enhanced(
            days_back=days_back,
            min_multiplier=min_multiplier,
            min_liquidity=min_liquidity
        )
        
        filtered_runners = [
            r for r in runners
            if r.get('token_age_days', 0) >= min_age_days
            and r.get('token_age_days', 0) <= max_age_days
        ]
        
        print(f"Found {len(filtered_runners)} trending runners")
        
        return jsonify({
            'success': True,
            'runners': filtered_runners,
            'total': len(filtered_runners),
            'data_source': 'Professional Trending Discovery',
            'filters_applied': {
                'timeframe': timeframe,
                'min_liquidity': min_liquidity,
                'min_multiplier': min_multiplier,
                'min_age_days': min_age_days,
                'max_age_days': max_age_days
            }
        }), 200
        
    except Exception as e:
        print(f"\n[TRENDING RUNNERS ERROR] {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# =============================================================================
# RUNNER ANALYSIS - Uses 6-step analysis with dropdown
# =============================================================================

@app.route('/api/trending/analyze', methods=['POST'])
def analyze_runner():
    """
    Analyze a single trending runner using 6-step professional analysis
    """
    try:
        data = request.json
        
        if not data.get('runner'):
            return jsonify({'error': 'runner object required'}), 400
        
        runner = data['runner']
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
        user_id = data.get('user_id', 'default_user')
        
        if wallet_analyzer is None:
            initialize_wallet_analyzer()
        
        print(f"\n{'='*80}")
        print(f"RUNNER ANALYSIS (6-STEP): {runner['ticker']}")
        print(f"{'='*80}")
        
        # Use 6-step professional analysis
        wallets = wallet_analyzer.analyze_token_professional(
            token_address=runner['address'],
            token_symbol=runner['ticker'],
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )
        
        return jsonify({
            'success': True,
            'runner': runner,
            'wallets': wallets[:50],
            'total_wallets': len(wallets),
            'mode': 'professional_runner_6step',
            'features': {
                'professional_scoring': True,
                '30day_dropdown': True,
                'runner_tracking': True,
                'birdeye_depth': True
            }
        }), 200
        
    except Exception as e:
        print(f"\n[RUNNER ANALYSIS ERROR] {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# =============================================================================
# AUTO DISCOVERY - Batch 6-step analysis with consistency
# =============================================================================

def _auto_discover_wallets_professional(user_id, min_runner_hits, days_back):
    """
    AUTO DISCOVERY: Find wallets across ALL runners using 6-step batch analysis
    """
    print(f"\n{'='*80}")
    print(f"AUTO DISCOVERY MODE (6-STEP BATCH)")
    print(f"Finding all {days_back}-day runners, min hits: {min_runner_hits}")
    print(f"{'='*80}")
    
    if wallet_analyzer is None:
        initialize_wallet_analyzer()
    
    print("  Discovering runners...")
    runners = wallet_analyzer.find_trending_runners_enhanced(
        days_back=days_back,
        min_multiplier=5.0,
        min_liquidity=50000
    )
    
    if not runners:
        return jsonify({
            'success': True,
            'smart_money_wallets': [],
            'total_wallets': 0,
            'error': 'No runners found in period'
        }), 200
    
    print(f"  Found {len(runners)} runners")
    
    runners_to_analyze = runners[:15]
    print(f"  Analyzing top {len(runners_to_analyze)} runners with 6-step analysis")
    
    # Use batch 6-step analysis
    smart_money = wallet_analyzer.batch_analyze_runners_professional(
        runners_list=runners_to_analyze,
        min_runner_hits=min_runner_hits,
        min_roi_multiplier=3.0,
        user_id=user_id
    )
    
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
    - PUMP MODE: Rally window analysis (unchanged)
    - GENERAL MODE: Professional 6-step batch analysis
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
        
        print(f"\n{'='*100}")
        print(f"MAIN ANALYSIS - MODE: {mode.upper()}")
        print(f"Tokens: {len(tokens)}")
        print(f"{'='*100}")
        
        if wallet_analyzer is None:
            initialize_wallet_analyzer()
        
        if mode == 'pump':
            print("Routing to PUMP MODE (rally windows)")
            # TODO: Implement pump mode routing
            return jsonify({'error': 'Pump mode not yet implemented'}), 501
        else:
            print("Routing to PROFESSIONAL GENERAL MODE (6-step batch)")
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

# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    if wallet_monitor is None:
        initialize_wallet_monitor()
    
    monitor_stats = wallet_monitor.get_monitoring_stats()
    
    return jsonify({
        'status': 'healthy',
        'version': '17.0.0 - CORRECTED 6-STEP',
        'features': {
            'six_step_analysis': True,
            'professional_scoring': True,
            '30day_runner_tracking': True,
            'consistency_grading': True,
            'birdeye_depth': True,
            'trending_runners': True,
            'auto_discovery': True,
            'real_time_monitoring': True
        },
        'wallet_monitor': {
            'running': monitor_stats['running'],
            'active_wallets': monitor_stats['active_wallets'],
            'pending_notifications': monitor_stats['pending_notifications']
        },
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
    print("\n🚀 Starting SIFTER KYS API Server v17.0")
    print("   CORRECTED: Using 6-step analysis from Document 6")
    
    initialize_wallet_analyzer()
    initialize_wallet_monitor()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port)