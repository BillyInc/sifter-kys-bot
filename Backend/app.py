# app.py - FULL UPDATED VERSION with Wallet Analysis

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime, timedelta
import json

# Your existing imports
from twitter_api_pool import TwitterAPIKeyPool
from tweet_extractor import TwitterTweetExtractor
from rally_tweet_connector import RallyTweetConnector
from pump_detector import PrecisionRallyDetector
from nlp_disambiguator import NLPDisambiguator

# Watchlist Database
from watchlist_db import WatchlistDatabase

# NEW: Wallet Analyzer
from wallet_analyzer import WalletPumpAnalyzer

app = Flask(__name__)
CORS(app)

# =============================================================================
# LOAD ALL 23 API KEYS
# =============================================================================

TWITTER_API_KEYS = [
    {'user_id': '405920194964049920', 'api_key': 'new1_f62eefe95d5349938ea4f77ca8f198ad', 'name': 'dnjunu'},
    {'user_id': '405944251155873792', 'api_key': 'new1_8c0aabf38b194412903658bfc9c0bdca', 'name': 'Ptrsamuelchinedu'},
    {'user_id': '405944945891999744', 'api_key': 'new1_f3d0911f1fb24d30b5ce170fa4ee950b', 'name': 'Ajnunu'},
    {'user_id': '405945504339345408', 'api_key': 'new1_4a6403a6401f4287ab744137ec980938', 'name': 'Sub profile 2'},
    {'user_id': '405946871811231744', 'api_key': 'new1_51f18ffecd3e4a1ebcf856f37b7a3030', 'name': 'Deeznaughts'},
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

BIRDEYE_API_KEY = os.environ.get('BIRDEYE_API_KEY', 'dbc2c07045644ae4bc868b6c3cbea6bf')

# =============================================================================
# INITIALIZE API KEY POOL (GLOBAL)
# =============================================================================

twitter_api_pool = TwitterAPIKeyPool(TWITTER_API_KEYS, cooldown_minutes=15)

# =============================================================================
# INITIALIZE WATCHLIST DATABASE
# =============================================================================

watchlist_db = WatchlistDatabase(db_path='watchlists.db')

print(f"""
╔══════════════════════════════════════════════════════════════════╗
║     SIFTER KYS API SERVER v7.0 - WITH WALLET ANALYSIS            ║
║                 FIXED ADDRESS ISSUE                              ║
╚══════════════════════════════════════════════════════════════════╝

✨ FEATURES:
  ✓ 23 Twitter API keys with automatic rotation
  ✓ Failover when keys hit rate limits
  ✓ Full Watchlist API endpoints (Twitter + Wallets)
  ✓ Birdeye price data integration (FIXED: Using correct pair addresses)
  ✓ Wallet analysis with ATH scoring
  ✓ Real-time key pool status tracking

🛠️ FIXES APPLIED:
  ✓ Twitter Analysis: Now uses 'pair_address' for OHLCV data
  ✓ Wallet Analysis: Now uses 'pair_address' for OHLCV data
  ✓ Both endpoints keep 'address' for wallet/overview calls
""")

# =============================================================================
# EXISTING TWITTER ANALYZE ENDPOINT - FIXED
# =============================================================================

@app.route('/api/analyze', methods=['POST'])
def analyze_tokens():
    try:
        data = request.json
        
        if not data.get('tokens'):
            return jsonify({'error': 'tokens array required'}), 400
        
        tokens = data['tokens']
        
        print(f"\n{'='*100}")
        print(f"TWITTER ANALYSIS: {len(tokens)} tokens")
        print(f"Active API Keys: {twitter_api_pool.get_status()['active_keys']}")
        print(f"{'='*100}\n")
        
        all_results = []
        all_top_accounts = {}
        
        for idx, token in enumerate(tokens, 1):
            print(f"\n{'─'*100}")
            print(f"[{idx}/{len(tokens)}] Analyzing {token['ticker']} ({token['name']})")
            print(f"{'─'*100}")
            
            settings = token.get('settings', {})

            try:
                detector = PrecisionRallyDetector(birdeye_api_key=BIRDEYE_API_KEY)
                
                print(f"[{idx}/{len(tokens)}] Fetching price data...")
                
                days_back = settings.get('days_back', 7)
                candle_size = settings.get('candle_size', '5m')
                
                # 🔴🔴🔴 FIX: Use pair_address, NOT address for OHLCV 🔴🔴🔴
                # Birdeye's OHLCV endpoint needs TRADING PAIR address
                pair_address = token.get('pair_address', token['address'])
                chain = token['chain']
                
                print(f"[{idx}/{len(tokens)}] Using pair address: {pair_address[:8]}...")
                print(f"[{idx}/{len(tokens)}] Token address (mint): {token['address'][:8]}...")
                
                ohlcv_data = detector.get_ohlcv_data(
                    pair_address=pair_address,  # ✅ FIXED: Use pair_address
                    chain=chain,
                    days_back=days_back,
                    candle_size=candle_size
                )
                
                if not ohlcv_data:
                    print(f"[{idx}/{len(tokens)}] ❌ No price data available")
                    all_results.append({
                        'token': token,
                        'success': False,
                        'rallies': 0,
                        'error': 'No price data available'
                    })
                    continue
                
                print(f"[{idx}/{len(tokens)}] Detecting pumps...")
                rallies = detector.detect_all_rallies(ohlcv_data)
                
                if not rallies:
                    print(f"[{idx}/{len(tokens)}] ✓ Analysis complete - No pumps detected")
                    all_results.append({
                        'token': token,
                        'success': True,
                        'rallies': 0,
                        'rally_details': [],
                        'top_accounts': [],
                        'pump_info': 'No significant pumps detected'
                    })
                    continue
                
                rally_details = []
                for rally in rallies:
                    start_unix = rally['window'][0]['unix_time']
                    end_unix = rally['window'][-1]['unix_time']
                    
                    volumes = [candle.get('v_usd', 0) for candle in rally['window']]
                    avg_volume = sum(volumes) / len(volumes) if volumes else 0
                    peak_volume = max(volumes) if volumes else 0
                    
                    baseline_volumes = []
                    for candle in ohlcv_data:
                        if candle['unix_time'] < start_unix:
                            baseline_volumes.append(candle.get('v_usd', 0))
                    
                    baseline_avg = sum(baseline_volumes[-10:]) / 10 if len(baseline_volumes) >= 10 else avg_volume
                    volume_spike_ratio = round(peak_volume / baseline_avg, 2) if baseline_avg > 0 else 1.0
                    
                    rally_details.append({
                        'start_time': start_unix,
                        'end_time': end_unix,
                        'total_gain_pct': round(rally['total_gain'], 2),
                        'peak_gain_pct': round(rally['peak_gain'], 2),
                        'rally_type': rally['type'],
                        'candle_count': rally['length'],
                        'green_ratio': round(rally['green_ratio'] * 100, 1),
                        'volume_data': {
                            'avg_volume': avg_volume,
                            'peak_volume': peak_volume,
                            'volume_spike_ratio': volume_spike_ratio
                        }
                    })
                
                print(f"[{idx}/{len(tokens)}] ✓ Found {len(rallies)} pump(s)")
                
                top_accounts = []
                
                try:
                    print(f"[{idx}/{len(tokens)}] Searching Twitter for callers...")
                    
                    tweet_extractor = TwitterTweetExtractor(api_key_pool=twitter_api_pool)
                    
                    nlp_scorer = NLPDisambiguator({
                        'ticker': token['ticker'],
                        'name': token['name'],
                        'contract_address': token['address'],
                        'chain': token['chain']
                    })
                    
                    rally_results = []
                    
                    for rally_idx, rally in enumerate(rallies, 1):
                        rally_start = datetime.fromtimestamp(rally['window'][0]['unix_time'])
                        
                        print(f"[{idx}/{len(tokens)}]   Pump {rally_idx}/{len(rallies)}: Searching tweets...")
                        
                        tweets = tweet_extractor.search_tweets_for_rally(
                            token_ticker=token['ticker'],
                            token_name=token['name'],
                            rally_start_time=rally_start,
                            t_minus_minutes=settings.get('t_minus', 35),
                            t_plus_minutes=settings.get('t_plus', 10)
                        )
                        
                        scored_tweets = []
                        for tweet in tweets:
                            score_result = nlp_scorer.score_tweet(tweet)
                            if score_result['accept']:
                                scored_tweets.append({
                                    'tweet': tweet,
                                    'score': score_result
                                })
                        
                        rally_results.append({
                            'rally': rally,
                            'scored_tweets': scored_tweets
                        })
                    
                    account_stats = {}
                    
                    for result in rally_results:
                        for scored_tweet in result['scored_tweets']:
                            tweet = scored_tweet['tweet']
                            author_id = str(tweet['author_id'])
                            
                            if author_id not in account_stats:
                                account_stats[author_id] = {
                                    'author_id': author_id,
                                    'username': tweet.get('author_username', ''),
                                    'pumps_called': 0,
                                    'timings': [],
                                    'scores': [],
                                    'high_confidence_count': 0
                                }
                            
                            account_stats[author_id]['pumps_called'] += 1
                            account_stats[author_id]['timings'].append(tweet['time_to_rally_minutes'])
                            account_stats[author_id]['scores'].append(scored_tweet['score']['total_score'])
                            
                            if scored_tweet['score']['confidence'] == 'high':
                                account_stats[author_id]['high_confidence_count'] += 1
                    
                    ranked_accounts = []
                    
                    for author_id, stats in account_stats.items():
                        if stats['timings']:
                            avg_timing = sum(stats['timings']) / len(stats['timings'])
                            avg_score = sum(stats['scores']) / len(stats['scores'])
                            earliest = min(stats['timings'])
                            
                            quality_score = min(avg_score * 0.6, 60)
                            confidence_bonus = min(stats['high_confidence_count'] * 10, 20)
                            signal_quality_total = quality_score + confidence_bonus
                            
                            if avg_timing < 0:
                                if -30 <= avg_timing <= -10:
                                    timing_score = abs(avg_timing) * 0.7
                                elif avg_timing < -30:
                                    timing_score = 20
                                else:
                                    timing_score = abs(avg_timing) * 0.7
                            else:
                                timing_score = max(0, 10 - (avg_timing * 0.5))
                            
                            timing_score = min(timing_score, 21)
                            
                            volume_score = 0
                            
                            username = stats.get('username', '')
                            credibility_penalty = 0
                            
                            bot_indicators = ['bot', '1xpz', 'alert', 'scan', 'crypto_']
                            if any(indicator in username.lower() for indicator in bot_indicators):
                                credibility_penalty -= 15
                            
                            if stats['pumps_called'] > 1:
                                credibility_penalty -= 10
                            
                            influence_score = (
                                signal_quality_total +
                                timing_score +
                                volume_score +
                                credibility_penalty
                            )
                            
                            influence_score = max(influence_score, 0)
                            
                            account = {
                                'author_id': author_id,
                                'pumps_called': stats['pumps_called'],
                                'avg_timing': round(avg_timing, 1),
                                'earliest_call': round(earliest, 1),
                                'influence_score': round(influence_score, 1),
                                'high_confidence_count': stats['high_confidence_count']
                            }
                            
                            ranked_accounts.append(account)
                            
                            if author_id not in all_top_accounts:
                                all_top_accounts[author_id] = {
                                    'author_id': author_id,
                                    'tokens_called': [],
                                    'total_influence': 0
                                }
                            
                            all_top_accounts[author_id]['tokens_called'].append(token['ticker'])
                            all_top_accounts[author_id]['total_influence'] += influence_score
                    
                    ranked_accounts.sort(key=lambda x: x['influence_score'], reverse=True)
                    top_20 = ranked_accounts[:20]
                    
                    if top_20:
                        user_ids = [acc['author_id'] for acc in top_20]
                        user_info = tweet_extractor.get_user_info(user_ids)
                        
                        for account in top_20:
                            author_id = account['author_id']
                            if author_id in user_info:
                                account.update(user_info[author_id])
                    
                    top_accounts = top_20
                    print(f"[{idx}/{len(tokens)}] ✓ Found {len(top_accounts)} top callers")
                
                except Exception as twitter_error:
                    print(f"[{idx}/{len(tokens)}] ⚠️ Twitter API error: {str(twitter_error)}")
                    top_accounts = []
                
                all_results.append({
                    'token': token,
                    'success': True,
                    'rallies': len(rallies),
                    'rally_details': rally_details,
                    'top_accounts': top_accounts,
                    'pump_info': f"{len(rallies)} pump(s) detected"
                })
                
                print(f"[{idx}/{len(tokens)}] ✅ Analysis complete\n")
                
            except Exception as e:
                print(f"[{idx}/{len(tokens)}] ❌ Error: {str(e)}")
                all_results.append({
                    'token': token,
                    'success': False,
                    'rallies': 0,
                    'error': str(e)
                })
        
        multi_token_accounts = []
        
        for author_id, data in all_top_accounts.items():
            if len(data['tokens_called']) >= 2:
                multi_token_accounts.append({
                    'author_id': author_id,
                    'tokens_count': len(data['tokens_called']),
                    'tokens_called': data['tokens_called'],
                    'total_influence': round(data['total_influence'], 1)
                })
        
        multi_token_accounts.sort(key=lambda x: x['tokens_count'], reverse=True)
        
        response = {
            'success': True,
            'summary': {
                'total_tokens': len(tokens),
                'successful_analyses': sum(1 for r in all_results if r['success']),
                'failed_analyses': sum(1 for r in all_results if not r['success']),
                'total_pumps': sum(r.get('rallies', 0) for r in all_results),
                'cross_token_accounts': len(multi_token_accounts)
            },
            'results': all_results,
            'cross_token_overlap': multi_token_accounts[:10],
            'api_key_pool_status': twitter_api_pool.get_status()
        }
        
        print(f"\n{'='*100}")
        print(f"TWITTER ANALYSIS COMPLETE")
        print(f"  Total: {len(tokens)} tokens")
        print(f"  Successful: {response['summary']['successful_analyses']}")
        print(f"  Total Pumps: {response['summary']['total_pumps']}")
        print(f"{'='*100}\n")
        
        twitter_api_pool.print_status()
        
        return jsonify(response), 200
        
    except Exception as e:
        print(f"\n[CRITICAL ERROR] {str(e)}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# NEW: WALLET ANALYSIS ENDPOINT - FIXED
# =============================================================================

@app.route('/api/wallets/analyze', methods=['POST'])
def analyze_wallets():
    """
    Wallet analysis endpoint with ALL-TIME HIGH scoring.
    
    Request body:
    {
        "tokens": [
            {
                "ticker": "PEPE",
                "name": "Pepe",
                "address": "token_mint",
                "pair_address": "pair_address",  # Added this
                "chain": "solana",
                "settings": {
                    "days_back": 7,
                    "candle_size": "5m",
                    "wallet_window_before": 35,
                    "wallet_window_after": 0
                }
            }
        ],
        "global_settings": {
            "min_pump_count": 5,
            "wallet_window_before": 35,
            "wallet_window_after": 10
        }
    }
    """
    try:
        data = request.json
        
        if not data.get('tokens'):
            return jsonify({'error': 'tokens array required'}), 400
        
        tokens = data['tokens']
        global_settings = data.get('global_settings', {})
        
        default_window_before = global_settings.get('wallet_window_before', 35)
        default_window_after = global_settings.get('wallet_window_after', 0)
        min_pump_count = global_settings.get('min_pump_count', 3)
        
        print(f"\n{'='*100}")
        print(f"WALLET ANALYSIS: {len(tokens)} tokens")
        print(f"Scoring: ALL-TIME HIGH")
        print(f"Window: T-{default_window_before}min to T+{default_window_after}min")
        print(f"Min Pump Count: {min_pump_count}")
        print(f"{'='*100}\n")
        
        # Step 1: Detect rallies AND store OHLCV data
        detector = PrecisionRallyDetector(birdeye_api_key=BIRDEYE_API_KEY)
        token_rally_data = []
        
        for idx, token in enumerate(tokens, 1):
            print(f"\n[{idx}/{len(tokens)}] RALLY DETECTION: {token['ticker']}")
            
            settings = token.get('settings', {})
            days_back = settings.get('days_back', 7)
            candle_size = settings.get('candle_size', '5m')
            
            # 🔴🔴🔴 FIX: Use pair_address, NOT address for OHLCV 🔴🔴🔴
            # Check if we have pair_address (frontend should send it)
            if 'pair_address' not in token:
                print(f"  ⚠️ No pair_address found, using address as fallback")
                print(f"  ⚠️ Frontend should send 'pair_address' from DexScreener")
                pair_address = token['address']
            else:
                pair_address = token['pair_address']
            
            print(f"  Token mint: {token['address'][:8]}...")
            print(f"  Pair address: {pair_address[:8]}...")
            
            ohlcv_data = detector.get_ohlcv_data(
                pair_address=pair_address,  # ✅ FIXED: Use pair_address
                chain=token.get('chain', 'solana'),
                days_back=days_back,
                candle_size=candle_size
            )
            
            if not ohlcv_data:
                print(f"  ❌ No price data")
                continue
            
            rallies = detector.detect_all_rallies(ohlcv_data)
            
            if rallies:
                window_before = settings.get('wallet_window_before', default_window_before)
                window_after = settings.get('wallet_window_after', default_window_after)
                
                # Store BOTH addresses for different purposes:
                # - 'address' (mint) for wallet analyzer
                # - 'pair_address' for OHLCV (already used above)
                token_rally_data.append({
                    'token': {
                        'ticker': token['ticker'],
                        'name': token['name'],
                        'address': token['address'],  # Token mint for wallet analysis
                        'pair_address': pair_address,  # Pair address for OHLCV
                        'chain': token.get('chain', 'solana')
                    },
                    'rallies': rallies,
                    'ohlcv_data': ohlcv_data,  # Pass OHLCV data for ATH calculation
                    'window_before': window_before,
                    'window_after': window_after
                })
                
                print(f"  ✓ Found {len(rallies)} rallies")
        
        if not token_rally_data:
            return jsonify({
                'success': False,
                'error': 'No rallies detected across any tokens'
            }), 200
        
        # Step 2: Wallet analysis with ATH
        wallet_analyzer = WalletPumpAnalyzer(
            birdeye_api_key=BIRDEYE_API_KEY
        )
        
        # Handle multiple window configurations
        unique_windows = set(
            (t['window_before'], t['window_after']) 
            for t in token_rally_data
        )
        
        if len(unique_windows) == 1:
            window_before = token_rally_data[0]['window_before']
            window_after = token_rally_data[0]['window_after']
            
            top_wallets = wallet_analyzer.analyze_multi_token_wallets(
                token_rally_data,
                window_minutes_before=window_before,
                window_minutes_after=window_after,
                min_pump_count=min_pump_count
            )
        else:
            from collections import Counter
            most_common_window = Counter(unique_windows).most_common(1)[0][0]
            window_before, window_after = most_common_window
            
            print(f"\n⚠️ Multiple window configurations detected")
            print(f"   Using most common: T-{window_before}min to T+{window_after}min")
            
            top_wallets = wallet_analyzer.analyze_multi_token_wallets(
                token_rally_data,
                window_minutes_before=window_before,
                window_minutes_after=window_after,
                min_pump_count=min_pump_count
            )
        
        wallet_analyzer.display_top_wallets(top_wallets, top_n=50)
        
        return jsonify({
            'success': True,
            'summary': {
                'tokens_analyzed': len(token_rally_data),
                'total_rallies': sum(len(t['rallies']) for t in token_rally_data),
                'qualified_wallets': len(top_wallets),
                's_tier': len([w for w in top_wallets if w['tier'] == 'S']),
                'a_tier': len([w for w in top_wallets if w['tier'] == 'A']),
                'b_tier': len([w for w in top_wallets if w['tier'] == 'B'])
            },
            'top_wallets': top_wallets,
            'settings': {
                'window_before': window_before,
                'window_after': window_after,
                'min_pump_count': min_pump_count,
                'scoring_method': 'ALL-TIME HIGH',
                'data_source': 'Birdeye /defi/v3/token/txs'
            }
        }), 200
        
    except Exception as e:
        print(f"\n[WALLET ANALYSIS ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# WALLET WATCHLIST ENDPOINTS
# =============================================================================

@app.route('/api/wallets/watchlist/add', methods=['POST'])
def add_wallet_to_watchlist():
    """Add wallet to watchlist"""
    try:
        data = request.json
        if not data.get('user_id') or not data.get('wallet'):
            return jsonify({'error': 'user_id and wallet required'}), 400
        
        success = watchlist_db.add_wallet_to_watchlist(
            data['user_id'],
            data['wallet']
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': f"Wallet {data['wallet']['wallet_address'][:8]}... added"
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': 'Wallet already in watchlist'
            }), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/wallets/watchlist/get', methods=['GET'])
def get_wallet_watchlist():
    """Get user's watched wallets"""
    try:
        user_id = request.args.get('user_id')
        tier = request.args.get('tier')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        wallets = watchlist_db.get_wallet_watchlist(user_id, tier)
        
        return jsonify({
            'success': True,
            'wallets': wallets,
            'count': len(wallets)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/wallets/watchlist/remove', methods=['POST'])
def remove_wallet_from_watchlist():
    """Remove wallet from watchlist"""
    try:
        data = request.json
        if not data.get('user_id') or not data.get('wallet_address'):
            return jsonify({'error': 'user_id and wallet_address required'}), 400
        
        success = watchlist_db.remove_wallet_from_watchlist(
            data['user_id'],
            data['wallet_address']
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Wallet removed from watchlist'
            }), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to remove wallet'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/wallets/watchlist/update', methods=['POST'])
def update_wallet_watchlist():
    """Update wallet notes/tags"""
    try:
        data = request.json
        if not data.get('user_id') or not data.get('wallet_address'):
            return jsonify({'error': 'user_id and wallet_address required'}), 400
        
        success = watchlist_db.update_wallet_notes(
            data['user_id'],
            data['wallet_address'],
            data.get('notes'),
            data.get('tags')
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Wallet updated'
            }), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to update'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/wallets/watchlist/stats', methods=['GET'])
def get_wallet_watchlist_stats():
    """Get wallet watchlist statistics"""
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        stats = watchlist_db.get_wallet_stats(user_id)
        
        return jsonify({
            'success': True,
            'stats': stats
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# TWITTER WATCHLIST ENDPOINTS (EXISTING)
# =============================================================================

@app.route('/api/watchlist/add', methods=['POST'])
def watchlist_add():
    try:
        data = request.json
        if not data or 'user_id' not in data or 'account' not in data:
            return jsonify({'error': 'user_id and account object are required'}), 400

        user_id = data['user_id']
        account = data['account']

        if 'author_id' not in account:
            return jsonify({'error': 'account must contain author_id'}), 400

        success = watchlist_db.add_to_watchlist(user_id, account)

        if success:
            return jsonify({
                'success': True,
                'message': f"@{account.get('username', 'user')} added to watchlist"
            }), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to add to watchlist'}), 500

    except Exception as e:
        print(f"[WATCHLIST API] Error in /add: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/get', methods=['GET'])
def watchlist_get():
    try:
        user_id = request.args.get('user_id')
        group_id = request.args.get('group_id')

        if not user_id:
            return jsonify({'error': 'user_id is required'}), 400

        accounts = watchlist_db.get_watchlist(
            user_id, 
            group_id=int(group_id) if group_id else None
        )

        return jsonify({
            'success': True,
            'accounts': accounts,
            'count': len(accounts)
        }), 200

    except Exception as e:
        print(f"[WATCHLIST API] Error in /get: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/remove', methods=['POST'])
def watchlist_remove():
    try:
        data = request.json
        if not data or 'user_id' not in data or 'author_id' not in data:
            return jsonify({'error': 'user_id and author_id are required'}), 400

        user_id = data['user_id']
        author_id = data['author_id']

        success = watchlist_db.remove_from_watchlist(user_id, author_id)

        if success:
            return jsonify({
                'success': True,
                'message': f"Account {author_id} removed from watchlist"
            }), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to remove account'}), 500

    except Exception as e:
        print(f"[WATCHLIST API] Error in /remove: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/update', methods=['POST'])
def watchlist_update():
    try:
        data = request.json
        if not data or 'user_id' not in data or 'author_id' not in data:
            return jsonify({'error': 'user_id and author_id are required'}), 400

        user_id = data['user_id']
        author_id = data['author_id']
        notes = data.get('notes')
        tags = data.get('tags')

        success = watchlist_db.update_account_notes(user_id, author_id, notes, tags)

        if success:
            return jsonify({
                'success': True,
                'message': 'Account updated successfully'
            }), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to update account'}), 500

    except Exception as e:
        print(f"[WATCHLIST API] Error in /update: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/stats', methods=['GET'])
def watchlist_stats():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id is required'}), 400

        stats = watchlist_db.get_watchlist_stats(user_id)

        return jsonify({
            'success': True,
            'stats': stats
        }), 200

    except Exception as e:
        print(f"[WATCHLIST API] Error in /stats: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/groups/create', methods=['POST'])
def groups_create():
    try:
        data = request.json
        if not data or 'user_id' not in data or 'group_name' not in data:
            return jsonify({'error': 'user_id and group_name required'}), 400

        user_id = data['user_id']
        group_name = data['group_name']
        description = data.get('description', '')

        group_id = watchlist_db.create_group(user_id, group_name, description)

        if group_id:
            return jsonify({
                'success': True,
                'group_id': group_id,
                'group_name': group_name
            }), 201
        else:
            return jsonify({'success': False, 'error': 'Failed to create group'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/groups', methods=['GET'])
def groups_list():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        groups = watchlist_db.get_user_groups(user_id)

        return jsonify({
            'success': True,
            'groups': groups,
            'count': len(groups)
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# KEY POOL STATUS & HEALTH CHECK
# =============================================================================

@app.route('/api/key_pool/status', methods=['GET'])
def get_key_pool_status():
    status = twitter_api_pool.get_status()
    top_used = twitter_api_pool.get_top_used_keys(5)
    
    return jsonify({
        'success': True,
        'pool_status': status,
        'top_used_keys': top_used
    }), 200


@app.route('/health', methods=['GET'])
def health_check():
    pool_status = twitter_api_pool.get_status()
    
    return jsonify({
        'status': 'healthy',
        'version': '7.0.0',
        'features': {
            'twitter_analysis': True,
            'wallet_analysis': True,
            'twitter_watchlist': True,
            'wallet_watchlist': True
        },
        'twitter_api_keys': {
            'total': pool_status['total_keys'],
            'active': pool_status['active_keys'],
            'rate_limited': pool_status['rate_limited_keys'],
            'failed': pool_status['failed_keys']
        },
        'birdeye_configured': bool(BIRDEYE_API_KEY),
        'watchlist_db': 'initialized'
    })


if __name__ == '__main__':
    print("\n🚀 Starting server on http://localhost:5000\n")
    
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port)