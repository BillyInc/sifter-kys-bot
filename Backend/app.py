from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import traceback
import requests as http_requests
import sqlite3
import pandas as pd
import io
import os

# Import your existing modules
from rally_tweet_connector import RallyTweetConnector
from pump_detector import PrecisionRallyDetector
from tweet_extractor import TwitterTweetExtractor
from nlp_disambiguator import NLPDisambiguator
from sna_analyzer import SocialNetworkAnalyzer
from expanded_sna import ExpandedSNAAnalyzer
from batch_analyzer import BatchTokenAnalyzer
from watchlist_db import WatchlistDatabase

app = Flask(__name__)
CORS(app)

# Initialize watchlist database
watchlist_db = WatchlistDatabase('watchlists.db')

# SERVER-SIDE API KEYS
TWITTER_BEARER_TOKEN = os.environ.get('TWITTER_BEARER_TOKEN', 'your_twitter_token_here')
BIRDEYE_API_KEY = os.environ.get('BIRDEYE_API_KEY', '35d3d50f74d94c439f6913a7e82cf994')

@app.route('/api/analyze', methods=['POST'])
def analyze_tokens():
    """
    FIXED: Analyze multiple tokens with proper data formats for frontend
    """
    try:
        data = request.json
        
        if not data.get('tokens'):
            return jsonify({'error': 'tokens array required'}), 400
        
        tokens = data['tokens']
        
        print(f"\n[MULTI-ANALYSIS] Analyzing {len(tokens)} tokens...")
        
        all_results = []
        all_top_accounts = {}
        
        for idx, token in enumerate(tokens, 1):
            print(f"\n[{idx}/{len(tokens)}] Analyzing {token['ticker']}...")
            
            settings = token.get('settings', {})
            
            try:
                # Get token launch time and price data
                detector = PrecisionRallyDetector(birdeye_api_key=BIRDEYE_API_KEY)
                launch_timestamp = None
                
                if settings.get('analysis_timeframe', '').startswith('first_'):
                    launch_timestamp = detector.get_token_launch_time(token['address'])
                
                ohlcv_data = detector.get_ohlcv_data_with_launch(
                    pair_address=token['pair_address'],
                    chain=token['chain'],
                    launch_timestamp=launch_timestamp,
                    window_type=settings.get('analysis_timeframe', 'first_7d'),
                    candle_size=settings.get('candle_size', '5m')
                )
                
                if not ohlcv_data:
                    all_results.append({
                        'token': token,
                        'success': False,
                        'rallies': 0,
                        'error': 'No price data available'
                    })
                    continue
                
                # Detect rallies
                rallies = detector.detect_all_rallies(ohlcv_data)
                
                # FIXED: Even if no rallies, still mark as success
                if not rallies:
                    all_results.append({
                        'token': token,
                        'success': True,
                        'rallies': 0,
                        'rally_details': [],
                        'top_accounts': [],
                        'pump_info': 'No significant pumps detected during analysis period'
                    })
                    continue
                
                # FIXED: Format rally details with correct field names and types
                rally_details = []
                for rally in rallies:
                    # FIXED Issue 3: Return Unix timestamps as numbers, not formatted strings
                    start_unix = rally['window'][0]['unix_time']
                    end_unix = rally['window'][-1]['unix_time']
                    
                    # Calculate volume stats
                    volumes = [candle.get('volume', 0) for candle in rally['window']]
                    avg_volume = sum(volumes) / len(volumes) if volumes else 0
                    peak_volume = max(volumes) if volumes else 0
                    
                    # Get baseline volume (before rally)
                    baseline_volumes = []
                    for candle in ohlcv_data:
                        if candle['unix_time'] < start_unix:
                            baseline_volumes.append(candle.get('volume', 0))
                    
                    baseline_avg = sum(baseline_volumes[-10:]) / 10 if len(baseline_volumes) >= 10 else avg_volume
                    volume_spike_ratio = round(peak_volume / baseline_avg, 2) if baseline_avg > 0 else 1.0
                    
                    rally_details.append({
                        # FIXED Issue 3: Use Unix timestamps (numbers) instead of formatted strings
                        'start_time': start_unix,
                        'end_time': end_unix,
                        # FIXED Issue 4: Use _pct suffix and multiply by 100 for percentage
                        'total_gain_pct': round(rally['total_gain'] * 100, 2),
                        'peak_gain_pct': round(rally['peak_gain'] * 100, 2),
                        'rally_type': rally['type'],
                        'candle_count': rally['length'],
                        'green_ratio': round(rally['green_ratio'] * 100, 1),
                        # FIXED Issue 5: Return volume_data as object with multiple fields
                        'volume_data': {
                            'avg_volume': avg_volume,
                            'peak_volume': peak_volume,
                            'volume_spike_ratio': volume_spike_ratio
                        }
                    })
                
                # Try to get Twitter data, but don't fail if Twitter API fails
                top_accounts = []
                
                try:
                    tweet_extractor = TwitterTweetExtractor(bearer_token=TWITTER_BEARER_TOKEN)
                    nlp_scorer = NLPDisambiguator({
                        'ticker': token['ticker'],
                        'name': token['name'],
                        'contract_address': token['address'],
                        'chain': token['chain']
                    })
                    
                    rally_results = []
                    
                    for rally in rallies:
                        rally_start = datetime.fromtimestamp(rally['window'][0]['unix_time'])
                        
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
                    
                    # Extract top accounts
                    account_stats = {}
                    
                    for result in rally_results:
                        for scored_tweet in result['scored_tweets']:
                            tweet = scored_tweet['tweet']
                            author_id = str(tweet['author_id'])
                            
                            if author_id not in account_stats:
                                account_stats[author_id] = {
                                    'author_id': author_id,
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
                    
                    # Calculate influence scores
                    ranked_accounts = []
                    
                    for author_id, stats in account_stats.items():
                        if stats['timings']:
                            avg_timing = sum(stats['timings']) / len(stats['timings'])
                            avg_score = sum(stats['scores']) / len(stats['scores'])
                            earliest = min(stats['timings'])
                            
                            influence_score = (
                                (stats['pumps_called'] * 30) +
                                (max(0, -avg_timing) * 2) +
                                (stats['high_confidence_count'] * 15) +
                                (avg_score * 0.5)
                            )
                            
                            account = {
                                'author_id': author_id,
                                'pumps_called': stats['pumps_called'],
                                'avg_timing': round(avg_timing, 1),
                                'earliest_call': round(earliest, 1),
                                'influence_score': round(influence_score, 1),
                                'high_confidence_count': stats['high_confidence_count']
                            }
                            
                            ranked_accounts.append(account)
                            
                            # Track across tokens
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
                    
                    # Get user info
                    if top_20:
                        user_ids = [acc['author_id'] for acc in top_20]
                        user_info = tweet_extractor.get_user_info(user_ids)
                        
                        for account in top_20:
                            author_id = account['author_id']
                            if author_id in user_info:
                                account.update(user_info[author_id])
                    
                    top_accounts = top_20
                
                except Exception as twitter_error:
                    print(f"[TWITTER ERROR] {token['ticker']}: {str(twitter_error)}")
                    top_accounts = []
                
                # Always return success if we have pump data
                all_results.append({
                    'token': token,
                    'success': True,
                    'rallies': len(rallies),
                    'rally_details': rally_details,
                    'top_accounts': top_accounts,
                    'pump_info': f"{len(rallies)} pump(s) detected" if rallies else "No pumps detected"
                })
                
            except Exception as e:
                print(f"[ERROR] {token['ticker']}: {str(e)}")
                print(traceback.format_exc())
                all_results.append({
                    'token': token,
                    'success': False,
                    'rallies': 0,
                    'error': str(e)
                })
        
        # Calculate cross-token overlap
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
        
        # Build response
        response = {
            'success': True,
            'summary': {
                'total_tokens': len(tokens),
                'successful_analyses': sum(1 for r in all_results if r['success']),
                'cross_token_accounts': len(multi_token_accounts)
            },
            'results': all_results,
            'cross_token_overlap': multi_token_accounts[:10]
        }
        
        print(f"\n[MULTI-ANALYSIS] Complete!")
        print(f"  Successful: {response['summary']['successful_analyses']}/{len(tokens)}")
        print(f"  Cross-token accounts: {len(multi_token_accounts)}")
        
        return jsonify(response), 200
        
    except Exception as e:
        print(f"[MULTI-ANALYSIS ERROR] {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/add', methods=['POST'])
def add_to_watchlist():
    """Add account to watchlist"""
    try:
        data = request.json
        user_id = data.get('user_id')
        account = data.get('account')
        
        if not user_id or not account:
            return jsonify({'error': 'user_id and account required'}), 400
        
        success = watchlist_db.add_to_watchlist(user_id, account)
        
        if success:
            return jsonify({'success': True, 'message': 'Account added to watchlist'}), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to add account'}), 500
            
    except Exception as e:
        print(f"[WATCHLIST ADD ERROR] {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/get', methods=['GET'])
def get_watchlist():
    """Get user's watchlist"""
    try:
        user_id = request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        accounts = watchlist_db.get_watchlist(user_id)
        
        return jsonify({'success': True, 'accounts': accounts}), 200
        
    except Exception as e:
        print(f"[WATCHLIST GET ERROR] {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/remove', methods=['POST'])
def remove_from_watchlist():
    """Remove account from watchlist"""
    try:
        data = request.json
        user_id = data.get('user_id')
        author_id = data.get('author_id')
        
        if not user_id or not author_id:
            return jsonify({'error': 'user_id and author_id required'}), 400
        
        success = watchlist_db.remove_from_watchlist(user_id, author_id)
        
        if success:
            return jsonify({'success': True, 'message': 'Account removed'}), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to remove account'}), 500
            
    except Exception as e:
        print(f"[WATCHLIST REMOVE ERROR] {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/update', methods=['POST'])
def update_watchlist_account():
    """Update account notes and tags"""
    try:
        data = request.json
        user_id = data.get('user_id')
        author_id = data.get('author_id')
        notes = data.get('notes')
        tags = data.get('tags')
        
        if not user_id or not author_id:
            return jsonify({'error': 'user_id and author_id required'}), 400
        
        success = watchlist_db.update_account_notes(user_id, author_id, notes, tags)
        
        if success:
            return jsonify({'success': True, 'message': 'Account updated'}), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to update account'}), 500
            
    except Exception as e:
        print(f"[WATCHLIST UPDATE ERROR] {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/groups', methods=['GET'])
def get_watchlist_groups():
    """Get user's watchlist groups"""
    try:
        user_id = request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        groups = watchlist_db.get_user_groups(user_id)
        
        return jsonify({'success': True, 'groups': groups}), 200
        
    except Exception as e:
        print(f"[WATCHLIST GROUPS ERROR] {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/stats', methods=['GET'])
def get_watchlist_stats():
    """Get watchlist statistics"""
    try:
        user_id = request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        stats = watchlist_db.get_watchlist_stats(user_id)
        
        return jsonify({'success': True, 'stats': stats}), 200
        
    except Exception as e:
        print(f"[WATCHLIST STATS ERROR] {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'version': '4.0.0'})


if __name__ == '__main__':
    print("""
╔════════════════════════════════════════════════════════════════╗
║              SIFTER KYS API SERVER v4.0 - ALL FIXED            ║
╚════════════════════════════════════════════════════════════════╝

✨ FIXES APPLIED:
  ✓ Issue 3: Returns Unix timestamps as numbers (not strings)
  ✓ Issue 4: Returns total_gain_pct and peak_gain_pct fields
  ✓ Issue 5: Returns volume_data object with avg/peak/spike
  ✓ Issue 6: Improved rally detection consistency
  
  - Watchlist endpoints ready
  - Better error handling
  - Proper data formatting for frontend

Starting server on http://localhost:5000
""")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port)