from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import traceback
import hashlib
import hmac
import requests as http_requests
import sqlite3
import pandas as pd
import io

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
CORS(app)  # Enable CORS for frontend requests

# Initialize watchlist database
watchlist_db = WatchlistDatabase('watchlists.db')

# Whop Configuration
WHOP_API_KEY = 'your_whop_api_key_here'  # Get from Whop dashboard
WHOP_PRODUCT_ID = 'your_product_id'
WHOP_WEBHOOK_SECRET = 'your_webhook_secret'


# Helper function to parse time ranges
def parse_time_range(time_range_str):
    """
    Convert time range string to window type
    Now supports both launch-anchored and relative windows
    """
    # Return the string as-is, will be handled by new OHLCV method
    return time_range_str


# Helper to format rally data for frontend
def format_rally_for_frontend(rally, rally_start, scored_tweets):
    """Convert rally data to frontend-friendly format"""
    return {
        'id': rally['start_idx'],
        'start_time': rally_start.strftime('%Y-%m-%d %H:%M:%S'),
        'end_time': datetime.fromtimestamp(rally['window'][-1]['unix_time']).strftime('%Y-%m-%d %H:%M:%S'),
        't_minus_35': (rally_start - timedelta(minutes=35)).strftime('%Y-%m-%d %H:%M:%S'),
        't_plus_10': (datetime.fromtimestamp(rally['window'][-1]['unix_time']) + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S'),
        'gain': round(rally['total_gain'], 2),
        'peak_gain': round(rally['peak_gain'], 2),
        'type': rally['type'],
        'length': rally['length'],
        'green_ratio': round(rally['green_ratio'] * 100, 1),
        'green_count': rally['green_count'],
        'red_count': rally['red_count'],
        'max_drawdown': round(rally['max_drawdown'], 2),
        'volume': rally['combined_volume'],
        'tweets_found': len(scored_tweets),
        'high_confidence_tweets': len([t for t in scored_tweets if t['score']['confidence'] == 'high']),
        'medium_confidence_tweets': len([t for t in scored_tweets if t['score']['confidence'] == 'medium'])
    }


# Helper to extract account rankings
def extract_account_rankings(rally_results):
    """
    Analyze all rallies and rank accounts by:
    - Number of pumps called
    - Average timing (how early)
    - Consistency
    """
    account_stats = {}
    
    for result in rally_results:
        for scored_tweet in result['scored_tweets']:
            tweet = scored_tweet['tweet']
            score = scored_tweet['score']
            author_id = tweet['author_id']
            
            if author_id not in account_stats:
                account_stats[author_id] = {
                    'author_id': author_id,
                    'pumps_called': 0,
                    'total_tweets': 0,
                    'timings': [],
                    'avg_score': 0,
                    'scores': [],
                    'high_confidence_count': 0,
                    'earliest_call': 0
                }
            
            account_stats[author_id]['pumps_called'] += 1
            account_stats[author_id]['total_tweets'] += 1
            account_stats[author_id]['timings'].append(tweet['time_to_rally_minutes'])
            account_stats[author_id]['scores'].append(score['total_score'])
            
            if score['confidence'] == 'high':
                account_stats[author_id]['high_confidence_count'] += 1
    
    # Calculate averages and rank
    ranked_accounts = []
    
    for author_id, stats in account_stats.items():
        if stats['timings']:
            avg_timing = sum(stats['timings']) / len(stats['timings'])
            avg_score = sum(stats['scores']) / len(stats['scores'])
            earliest_call = min(stats['timings'])
            
            # Calculate influence score (weighted composite)
            influence_score = (
                (stats['pumps_called'] * 30) +  # More pumps = better
                (max(0, -avg_timing) * 2) +      # Earlier = better
                (stats['high_confidence_count'] * 15) +  # Quality matters
                (avg_score * 0.5)                # NLP score matters
            )
            
            ranked_accounts.append({
                'author_id': author_id,
                'pumps_called': stats['pumps_called'],
                'total_tweets': stats['total_tweets'],
                'avg_timing': round(avg_timing, 1),
                'earliest_call': round(earliest_call, 1),
                'avg_score': round(avg_score, 1),
                'high_confidence_count': stats['high_confidence_count'],
                'influence_score': round(influence_score, 1)
            })
    
    # Sort by influence score
    ranked_accounts.sort(key=lambda x: x['influence_score'], reverse=True)
    
    return ranked_accounts


def check_whop_subscription(user_id: str) -> dict:
    """
    Check Whop subscription status for user
    
    Args:
        user_id: User identifier (wallet address or email)
    
    Returns:
        Dictionary with subscription status
    """
    try:
        # Call Whop API to check subscription
        headers = {
            'Authorization': f'Bearer {WHOP_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # Query Whop for user's memberships
        response = http_requests.get(
            f'https://api.whop.com/v1/memberships',
            headers=headers,
            params={'user': user_id}
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Check if user has active subscription
            for membership in data.get('memberships', []):
                if membership.get('status') == 'active':
                    # Determine tier based on product
                    product_id = membership.get('product_id')
                    
                    if product_id == f'{WHOP_PRODUCT_ID}_pro':
                        return {'active': True, 'tier': 'pro'}
                    elif product_id == f'{WHOP_PRODUCT_ID}_basic':
                        return {'active': True, 'tier': 'basic'}
            
            return {'active': False, 'tier': 'free'}
        
        else:
            print(f"[WHOP] API error: {response.status_code}")
            return {'active': False, 'tier': 'free'}
    
    except Exception as e:
        print(f"[WHOP] Error checking subscription: {e}")
        return {'active': False, 'tier': 'free'}


def get_tier_features(tier: str) -> dict:
    """
    Get feature access for subscription tier
    
    Args:
        tier: Subscription tier (free, basic, pro)
    
    Returns:
        Dictionary of features and limits
    """
    tier_features = {
        'free': {
            'basic_analysis': True,
            'batch_analysis': False,
            'batch_limit': 0,
            'expanded_sna': False,
            'network_graph': False,
            'watchlist': False,
            'watchlist_limit': 0,
            'api_access': False
        },
        'basic': {
            'basic_analysis': True,
            'batch_analysis': True,
            'batch_limit': 10,
            'expanded_sna': True,
            'network_graph': False,
            'watchlist': True,
            'watchlist_limit': 50,
            'api_access': False
        },
        'pro': {
            'basic_analysis': True,
            'batch_analysis': True,
            'batch_limit': 50,
            'expanded_sna': True,
            'network_graph': True,
            'watchlist': True,
            'watchlist_limit': 999,
            'api_access': True
        }
    }
    
    return tier_features.get(tier, tier_features['free'])


def verify_whop_signature(payload: bytes, signature: str) -> bool:
    """
    Verify Whop webhook signature
    
    Args:
        payload: Raw request body
        signature: X-Whop-Signature header
    
    Returns:
        True if signature is valid
    """
    try:
        expected_signature = hmac.new(
            WHOP_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
    
    except Exception as e:
        print(f"[WHOP] Signature verification error: {e}")
        return False


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'version': '2.0.0'})


@app.route('/api/check-access', methods=['POST'])
def check_access():
    """
    Check if user has access based on wallet address or Whop subscription
    
    Expected JSON body:
    {
        "wallet_address": "0x123..." or "user_id": "user123"
    }
    """
    try:
        data = request.json
        wallet_address = data.get('wallet_address')
        user_id = data.get('user_id', wallet_address)
        
        if not user_id:
            return jsonify({'error': 'wallet_address or user_id required'}), 400
        
        # Check if user exists in database
        conn = sqlite3.connect('watchlists.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT subscription_tier FROM users WHERE user_id = ?
        ''', (user_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            tier = result[0]
        else:
            # New user - create with free tier
            watchlist_db.create_user(user_id, wallet_address)
            tier = 'free'
        
        # Check Whop subscription status
        whop_status = check_whop_subscription(user_id)
        
        if whop_status['active']:
            tier = whop_status['tier']
            
            # Update user tier in database
            conn = sqlite3.connect('watchlists.db')
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET subscription_tier = ? WHERE user_id = ?
            ''', (tier, user_id))
            conn.commit()
            conn.close()
        
        # Define feature access
        features = get_tier_features(tier)
        
        return jsonify({
            'authorized': True,
            'tier': tier,
            'features': features,
            'user_id': user_id
        }), 200
        
    except Exception as e:
        print(f"[ACCESS] Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/analyze', methods=['POST'])
def analyze_token():
    """
    Main analysis endpoint - NOW WITH LAUNCH-ANCHORED WINDOWS
    
    Expected JSON body:
    {
        "token_address": "contract_address",
        "twitter_token": "user_bearer_token",
        "birdeye_key": "optional_birdeye_key",
        "time_range": "first_7d",
        "pump_timeframe": "5m"
    }
    """
    try:
        data = request.json
        
        # Validate required fields
        if not data.get('token_address'):
            return jsonify({'error': 'token_address is required'}), 400
        
        if not data.get('twitter_token'):
            return jsonify({'error': 'twitter_token is required'}), 400
        
        # Extract parameters
        token_address = data['token_address']
        twitter_token = data['twitter_token']
        birdeye_key = data.get('birdeye_key', '35d3d50f74d94c439f6913a7e82cf994')
        time_range = data.get('time_range', 'first_7d')
        pump_timeframe = data.get('pump_timeframe', '5m')
        
        print(f"\n[API] Starting analysis for token: {token_address}")
        print(f"[API] Time range: {time_range}")
        print(f"[API] Pump timeframe: {pump_timeframe}")
        
        # === Get token launch time ===
        detector = PrecisionRallyDetector(birdeye_api_key=birdeye_key)
        
        # First get token metadata
        pair_data = detector.get_token_data(token_address)
        if not pair_data:
            return jsonify({'error': 'Token not found'}), 404
        
        # Get launch timestamp
        launch_timestamp = None
        if time_range.startswith('first_'):
            launch_timestamp = detector.get_token_launch_time(token_address)
        
        # Build token profile
        token_profile = {
            'ticker': pair_data['baseToken']['symbol'],
            'name': pair_data['baseToken']['name'],
            'contract': token_address,
            'chain': pair_data['chainId'],
            'dex': pair_data['dexId'],
            'launch_time': launch_timestamp
        }
        
        # Get OHLCV data with launch-anchored window
        pair_address = pair_data['pairAddress']
        chain_name = detector.get_chain_name(pair_data['chainId'])
        
        ohlcv_data = detector.get_ohlcv_data_with_launch(
            pair_address=pair_address,
            chain=chain_name,
            launch_timestamp=launch_timestamp,
            window_type=time_range
        )
        
        if not ohlcv_data:
            return jsonify({'error': 'No price data available'}), 404
        
        # Detect rallies
        rallies = detector.detect_all_rallies(ohlcv_data)
        
        if not rallies:
            return jsonify({
                'error': 'No rallies detected',
                'message': f'No significant pumps found in {time_range}'
            }), 404
        
        # === Continue with Twitter analysis ===
        tweet_extractor = TwitterTweetExtractor(bearer_token=twitter_token)
        nlp_scorer = NLPDisambiguator(token_profile)
        
        # Test Twitter connection
        if not tweet_extractor.test_connection():
            return jsonify({
                'error': 'Twitter API connection failed',
                'message': 'Please check your Twitter Bearer Token'
            }), 401
        
        # Extract tweets for each rally
        rally_results = []
        
        for rally in rallies:
            rally_start = datetime.fromtimestamp(rally['window'][0]['unix_time'])
            rally_end = datetime.fromtimestamp(rally['window'][-1]['unix_time'])
            
            # Search tweets
            tweets = tweet_extractor.search_tweets_for_rally(
                token_ticker=token_profile['ticker'],
                token_name=token_profile['name'],
                rally_start_time=rally_start,
                t_minus_minutes=35,
                t_plus_minutes=10
            )
            
            # Score tweets
            scored_tweets = []
            for tweet in tweets:
                score_result = nlp_scorer.score_tweet(tweet)
                if score_result['accept']:
                    scored_tweets.append({
                        'tweet': tweet,
                        'score': score_result
                    })
            
            scored_tweets.sort(key=lambda x: x['score']['total_score'], reverse=True)
            
            rally_results.append({
                'rally': rally,
                'rally_start': rally_start,
                'tweets': tweets,
                'scored_tweets': scored_tweets
            })
        
        # Format rallies for frontend
        formatted_rallies = []
        for result in rally_results:
            formatted_rally = format_rally_for_frontend(
                result['rally'],
                result['rally_start'],
                result['scored_tweets']
            )
            formatted_rallies.append(formatted_rally)
        
        # Extract and rank accounts
        ranked_accounts = extract_account_rankings(rally_results)
        top_accounts = ranked_accounts[:10]
        
        # Fetch user info for top accounts
        if top_accounts:
            user_ids = [acc['author_id'] for acc in top_accounts]
            user_info = tweet_extractor.get_user_info(user_ids)
            
            # Merge user info with rankings
            for account in top_accounts:
                author_id = str(account['author_id'])
                if author_id in user_info:
                    account['username'] = user_info[author_id]['username']
                    account['name'] = user_info[author_id]['name']
                    account['followers'] = user_info[author_id]['followers']
                    account['verified'] = user_info[author_id]['verified']
                else:
                    account['username'] = f"user_{author_id}"
                    account['name'] = 'Unknown User'
                    account['followers'] = 0
                    account['verified'] = False
        
        # === SOCIAL NETWORK ANALYSIS ===
        print("[API] Running Social Network Analysis...")
        
        network_analysis = {
            'total_unique_accounts': len(ranked_accounts),
            'coordinated': False,
            'topology': 'unknown',
            'reciprocity': 0.0,
            'message': 'Network analysis requires Twitter API elevated access'
        }
        
        # Only run SNA if we have enough accounts
        if len(ranked_accounts) >= 3:
            try:
                import tweepy
                client = tweepy.Client(bearer_token=twitter_token)
                sna = SocialNetworkAnalyzer(client)
                
                # Use top 20 accounts for SNA (balance between accuracy and API limits)
                sna_account_ids = [str(acc['author_id']) for acc in ranked_accounts[:20]]
                
                # Build network graph
                sna.build_network_from_accounts(sna_account_ids, max_depth=1)
                
                # Generate full SNA report
                sna_report = sna.generate_network_report()
                
                # Prepare tweet timing data for temporal analysis
                tweets_by_user = {}
                for result in rally_results:
                    for scored_tweet in result['scored_tweets']:
                        tweet = scored_tweet['tweet']
                        author_id = str(tweet['author_id'])
                        
                        if author_id not in tweets_by_user:
                            tweets_by_user[author_id] = []
                        
                        tweets_by_user[author_id].append(tweet['created_at'])
                
                # Run temporal coordination analysis
                temporal_analysis = sna.analyze_temporal_coordination(tweets_by_user)
                
                # Merge SNA results with influence metrics
                influence_metrics = sna_report.get('influence_metrics', {})
                for account in top_accounts:
                    author_id = str(account['author_id'])
                    if author_id in influence_metrics:
                        account['sna_metrics'] = influence_metrics[author_id]
                
                # Update network analysis with real data
                network_analysis = {
                    'total_unique_accounts': len(ranked_accounts),
                    'total_nodes': sna_report['summary']['total_nodes'],
                    'total_edges': sna_report['summary']['total_edges'],
                    'density': sna_report['summary']['density'],
                    'coordinated': sna_report['summary']['likely_coordinated'],
                    'coordination_indicators': sna_report['summary']['coordination_indicators'],
                    'topology': sna_report['topology']['type'],
                    'topology_details': sna_report['topology'],
                    'reciprocity': sna_report['reciprocity'],
                    'bridges': sna_report['bridges'],
                    'communities': len(set(sna_report['communities'].values())) if sna_report['communities'] else 0,
                    'temporal_coordination': temporal_analysis,
                    'visualization_data': sna.export_graph_for_visualization()
                }
                
                print(f"[API] SNA Complete: {network_analysis['topology']} topology, coordinated={network_analysis['coordinated']}")
                
            except ImportError as e:
                print(f"[API] SNA skipped: Missing dependency ({e})")
                network_analysis['message'] = f"SNA unavailable: {str(e)}"
            
            except Exception as e:
                print(f"[API] SNA error: {e}")
                network_analysis['message'] = f"SNA failed: {str(e)}"
        
        # Build response
        response = {
            'success': True,
            'token': token_profile,
            'analysis_params': {
                'time_range': time_range,
                'pump_timeframe': pump_timeframe,
                'launch_anchored': time_range.startswith('first_')
            },
            'summary': {
                'total_pumps': len(formatted_rallies),
                'total_tweets': sum(len(r['scored_tweets']) for r in rally_results),
                'unique_accounts': len(ranked_accounts),
                'high_confidence_tweets': sum(r['high_confidence_tweets'] for r in formatted_rallies)
            },
            'pumps': formatted_rallies,
            'accounts': top_accounts,
            'network': network_analysis,
            'quota_used': tweet_extractor.tweets_used_this_month
        }
        
        print(f"[API] Analysis complete! Found {len(formatted_rallies)} pumps, {len(ranked_accounts)} unique accounts")
        
        return jsonify(response), 200
        
    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'error': 'Analysis failed',
            'message': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/expanded-sna', methods=['POST'])
def expanded_sna_analysis():
    """
    Analyze interactions between top accounts over extended timeframe
    
    Expected JSON body:
    {
        "account_ids": ["123", "456", "789"],
        "account_usernames": ["user1", "user2", "user3"],
        "twitter_token": "bearer_token",
        "timeframe": "7d"  // Options: "3d", "7d", "30d", "all"
    }
    """
    try:
        data = request.json
        
        # Validate
        if not data.get('account_ids') or not data.get('account_usernames'):
            return jsonify({'error': 'account_ids and account_usernames required'}), 400
        
        if not data.get('twitter_token'):
            return jsonify({'error': 'twitter_token required'}), 400
        
        account_ids = data['account_ids']
        account_usernames = data['account_usernames']
        twitter_token = data['twitter_token']
        timeframe = data.get('timeframe', '7d')
        
        # Parse timeframe
        timeframe_mapping = {
            '3d': 3,
            '7d': 7,
            '30d': 30,
            'all': 365  # Max 1 year for Twitter API
        }
        days_back = timeframe_mapping.get(timeframe, 7)
        
        print(f"\n[API] Expanded SNA for {len(account_ids)} accounts over {days_back} days")
        
        # Initialize analyzer
        import tweepy
        client = tweepy.Client(bearer_token=twitter_token)
        analyzer = ExpandedSNAAnalyzer(client)
        
        # Run analysis
        results = analyzer.analyze_expanded_network(
            account_usernames=account_usernames,
            account_ids=account_ids,
            days_back=days_back
        )
        
        # Assess coordination
        coordination_assessment = {
            'high_reciprocity': results['metrics'].get('reciprocity', 0) > 0.7,
            'high_clustering': results['metrics'].get('clustering', 0) > 0.6,
            'tight_component': results['metrics'].get('largest_component_size', 0) > len(account_ids) * 0.5
        }
        
        coordination_score = sum(coordination_assessment.values())
        
        results['coordination'] = {
            'likely_coordinated': coordination_score >= 2,
            'coordination_score': coordination_score,
            'indicators': coordination_assessment
        }
        
        print(f"[API] Expanded SNA complete: {results['summary']['total_interactions']} interactions found")
        
        return jsonify({
            'success': True,
            'results': results
        }), 200
        
    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'error': 'Expanded SNA failed',
            'message': str(e)
        }), 500


@app.route('/api/batch-analyze', methods=['POST'])
def batch_analyze():
    """
    Analyze multiple tokens from CSV or token list
    
    Expected JSON body:
    {
        "tokens": [
            {"address": "addr1", "ticker": "TOKEN1", "name": "Token One"},
            {"address": "addr2", "ticker": "TOKEN2", "name": "Token Two"}
        ],
        "twitter_token": "bearer_token",
        "birdeye_key": "optional_key",
        "time_range": "first_7d"
    }
    
    OR with CSV data:
    {
        "csv_data": "address,ticker,name\naddr1,TOKEN1,Token One\n...",
        "twitter_token": "bearer_token",
        "birdeye_key": "optional_key",
        "time_range": "first_7d"
    }
    """
    try:
        data = request.json
        
        # Validate
        if not data.get('twitter_token'):
            return jsonify({'error': 'twitter_token required'}), 400
        
        twitter_token = data['twitter_token']
        birdeye_key = data.get('birdeye_key', '35d3d50f74d94c439f6913a7e82cf994')
        time_range = data.get('time_range', 'first_7d')
        
        # Parse token list (either from JSON or CSV)
        if data.get('csv_data'):
            # Parse CSV
            try:
                df = pd.read_csv(io.StringIO(data['csv_data']))
                
                # Validate CSV columns
                if 'address' not in df.columns:
                    return jsonify({'error': 'CSV must have "address" column'}), 400
                
                token_list = []
                for _, row in df.iterrows():
                    token_list.append({
                        'address': row['address'],
                        'ticker': row.get('ticker', 'UNKNOWN'),
                        'name': row.get('name', '')
                    })
                
            except Exception as e:
                return jsonify({'error': f'Failed to parse CSV: {str(e)}'}), 400
        
        elif data.get('tokens'):
            token_list = data['tokens']
        
        else:
            return jsonify({'error': 'Either "tokens" array or "csv_data" required'}), 400
        
        # Limit batch size
        if len(token_list) > 50:
            return jsonify({'error': 'Maximum 50 tokens per batch'}), 400
        
        print(f"\n[API] Batch analysis for {len(token_list)} tokens")
        
        # Initialize batch analyzer
        batch_analyzer = BatchTokenAnalyzer()
        
        # Initialize rally-tweet connector
        connector = RallyTweetConnector(
            birdeye_api_key=birdeye_key,
            twitter_bearer_token=twitter_token
        )
        
        # Analyze all tokens
        results = batch_analyzer.analyze_multiple_tokens(
            token_list=token_list,
            rally_tweet_connector=connector,
            time_range=time_range
        )
        
        # Extract cross-token accounts
        cross_token_accounts = batch_analyzer.extract_cross_token_accounts()
        
        # Rank accounts
        ranked_accounts = batch_analyzer.rank_cross_token_accounts(min_tokens=2)
        
        # Detect coordination
        coordination = batch_analyzer.detect_coordination_across_tokens()
        
        # Build response
        response = {
            'success': True,
            'summary': {
                'total_tokens': len(token_list),
                'successful_analyses': sum(1 for r in results if r['results']),
                'failed_analyses': sum(1 for r in results if not r['results']),
                'unique_accounts': len(cross_token_accounts),
                'multi_token_accounts': len(ranked_accounts),
                'coordinated_pairs': coordination['total_pairs_detected']
            },
            'token_results': [
                {
                    'token': r['token'],
                    'success': bool(r['results']),
                    'pumps_found': len(r['results']) if r['results'] else 0,
                    'error': r.get('error')
                }
                for r in results
            ],
            'top_accounts': ranked_accounts[:20],
            'coordination': coordination,
            'quota_used': connector.tweet_extractor.tweets_used_this_month
        }
        
        print(f"[API] Batch analysis complete!")
        print(f"      {response['summary']['successful_analyses']}/{len(token_list)} tokens analyzed")
        print(f"      {len(ranked_accounts)} accounts found in 2+ tokens")
        
        return jsonify(response), 200
        
    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'error': 'Batch analysis failed',
            'message': str(e)
        }), 500


@app.route('/api/cross-token-comparison/<author_id>', methods=['POST'])
def cross_token_comparison(author_id):
    """
    Get detailed comparison of one account across multiple tokens
    
    This requires batch analysis to be run first and stored
    For now, this is a placeholder - you'd need session storage or database
    """
    return jsonify({
        'error': 'Not implemented',
        'message': 'Run batch analysis first, then use stored results'
    }), 501


@app.route('/api/export-batch-csv', methods=['POST'])
def export_batch_csv():
    """
    Export batch analysis results to CSV
    
    Expected JSON body:
    {
        "cross_token_accounts": {...},
        "filename": "optional_filename.csv"
    }
    """
    try:
        data = request.json
        
        if not data.get('cross_token_accounts'):
            return jsonify({'error': 'cross_token_accounts data required'}), 400
        
        # Prepare CSV data
        csv_data = []
        
        for account in data['cross_token_accounts']:
            csv_data.append({
                'Author ID': account.get('author_id', ''),
                'Username': account.get('username', ''),
                'Name': account.get('name', ''),
                'Tokens Called': account.get('tokens_count', 0),
                'Total Pumps': account.get('total_pumps', 0),
                'Avg Timing (min)': round(account.get('avg_timing_overall', 0), 1),
                'Earliest Call (min)': round(account.get('earliest_call_overall', 0), 1),
                'Cross-Token Influence': account.get('cross_token_influence', 0),
                'Token List': ', '.join([t.get('ticker', '') for t in account.get('tokens_called', [])])
            })
        
        # Create DataFrame
        df = pd.DataFrame(csv_data)
        df = df.sort_values('Cross-Token Influence', ascending=False)
        
        # Convert to CSV string
        csv_string = df.to_csv(index=False)
        
        return jsonify({
            'success': True,
            'csv_data': csv_string,
            'filename': data.get('filename', 'cross_token_analysis.csv')
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': 'CSV export failed',
            'message': str(e)
        }), 500


@app.route('/api/watchlist', methods=['GET'])
def get_watchlist():
    """
    Get user's watchlist
    
    Query params:
        user_id: User identifier (required)
        group_id: Optional group filter
    """
    try:
        user_id = request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        group_id = request.args.get('group_id', type=int)
        
        accounts = watchlist_db.get_watchlist(user_id, group_id)
        stats = watchlist_db.get_watchlist_stats(user_id)
        
        return jsonify({
            'success': True,
            'accounts': accounts,
            'stats': stats
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/add', methods=['POST'])
def add_to_watchlist():
    """
    Add account to watchlist
    
    Expected JSON body:
    {
        "user_id": "user123",
        "account": {
            "author_id": "123456789",
            "username": "cryptowhale",
            "name": "Crypto Whale",
            "followers": 10000,
            "verified": false,
            "influence_score": 85.5,
            "avg_timing": -25.5,
            "pumps_called": 5,
            "tags": ["solana", "alpha"],
            "notes": "Very early on BONK"
        }
    }
    """
    try:
        data = request.json
        
        if not data.get('user_id') or not data.get('account'):
            return jsonify({'error': 'user_id and account required'}), 400
        
        success = watchlist_db.add_to_watchlist(
            user_id=data['user_id'],
            account=data['account']
        )
        
        if success:
            return jsonify({'success': True, 'message': 'Added to watchlist'}), 200
        else:
            return jsonify({'error': 'Failed to add to watchlist'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/remove', methods=['POST'])
def remove_from_watchlist():
    """
    Remove account from watchlist
    
    Expected JSON body:
    {
        "user_id": "user123",
        "author_id": "123456789"
    }
    """
    try:
        data = request.json
        
        if not data.get('user_id') or not data.get('author_id'):
            return jsonify({'error': 'user_id and author_id required'}), 400
        
        success = watchlist_db.remove_from_watchlist(
            user_id=data['user_id'],
            author_id=data['author_id']
        )
        
        if success:
            return jsonify({'success': True, 'message': 'Removed from watchlist'}), 200
        else:
            return jsonify({'error': 'Failed to remove from watchlist'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/update', methods=['POST'])
def update_watchlist_account():
    """
    Update account notes and tags
    
    Expected JSON body:
    {
        "user_id": "user123",
        "author_id": "123456789",
        "notes": "Updated notes",
        "tags": ["tag1", "tag2"]
    }
    """
    try:
        data = request.json
        
        if not data.get('user_id') or not data.get('author_id'):
            return jsonify({'error': 'user_id and author_id required'}), 400
        
        success = watchlist_db.update_account_notes(
            user_id=data['user_id'],
            author_id=data['author_id'],
            notes=data.get('notes'),
            tags=data.get('tags')
        )
        
        if success:
            return jsonify({'success': True, 'message': 'Updated successfully'}), 200
        else:
            return jsonify({'error': 'Failed to update'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/groups', methods=['GET'])
def get_watchlist_groups():
    """
    Get user's watchlist groups
    
    Query params:
        user_id: User identifier (required)
    """
    try:
        user_id = request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        groups = watchlist_db.get_user_groups(user_id)
        
        return jsonify({
            'success': True,
            'groups': groups
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/groups/create', methods=['POST'])
def create_watchlist_group():
    """
    Create a new watchlist group
    
    Expected JSON body:
    {
        "user_id": "user123",
        "group_name": "Solana Alpha",
        "description": "Best Solana callers"
    }
    """
    try:
        data = request.json
        
        if not data.get('user_id') or not data.get('group_name'):
            return jsonify({'error': 'user_id and group_name required'}), 400
        
        group_id = watchlist_db.create_group(
            user_id=data['user_id'],
            group_name=data['group_name'],
            description=data.get('description', '')
        )
        
        if group_id:
            return jsonify({
                'success': True,
                'group_id': group_id,
                'message': 'Group created successfully'
            }), 200
        else:
            return jsonify({'error': 'Failed to create group'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/watchlist/history/<author_id>', methods=['GET'])
def get_account_history(author_id):
    """
    Get performance history for an account
    
    Query params:
        user_id: User identifier (required)
    """
    try:
        user_id = request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        history = watchlist_db.get_account_history(user_id, author_id)
        
        return jsonify({
            'success': True,
            'history': history
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/whop-webhook', methods=['POST'])
def whop_webhook():
    """
    Handle Whop webhooks for subscription events
    
    Whop sends webhooks when:
    - User subscribes
    - Subscription renewed
    - Subscription cancelled
    """
    try:
        # Verify webhook signature
        signature = request.headers.get('X-Whop-Signature')
        payload = request.data
        
        if not verify_whop_signature(payload, signature):
            return jsonify({'error': 'Invalid signature'}), 401
        
        data = request.json
        event_type = data.get('type')
        
        if event_type == 'membership.created':
            # New subscription
            user_id = data.get('user', {}).get('id')
            tier = data.get('product', {}).get('name', 'basic')
            
            # Update user in database
            conn = sqlite3.connect('watchlists.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, subscription_tier)
                VALUES (?, ?)
            ''', (user_id, tier))
            conn.commit()
            conn.close()
            
            print(f"[WHOP] New subscription: {user_id} -> {tier}")
        
        elif event_type == 'membership.cancelled':
            # Subscription cancelled
            user_id = data.get('user', {}).get('id')
            
            # Downgrade to free
            conn = sqlite3.connect('watchlists.db')
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET subscription_tier = 'free' WHERE user_id = ?
            ''', (user_id,))
            conn.commit()
            conn.close()
            
            print(f"[WHOP] Subscription cancelled: {user_id}")
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"[WHOP] Webhook error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/upgrade-prompt', methods=['POST'])
def upgrade_prompt():
    """
    Return upgrade prompt info when user hits a paid feature
    
    Expected JSON body:
    {
        "user_id": "user123",
        "feature": "batch_analysis"
    }
    """
    try:
        data = request.json
        user_id = data.get('user_id')
        feature = data.get('feature')
        
        # Get user's current tier
        conn = sqlite3.connect('watchlists.db')
        cursor = conn.cursor()
        cursor.execute('SELECT subscription_tier FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        current_tier = result[0] if result else 'free'
        
        # Feature requirements
        feature_requirements = {
            'batch_analysis': 'basic',
            'expanded_sna': 'basic',
            'network_graph': 'pro',
            'watchlist': 'basic',
            'api_access': 'pro'
        }
        
        required_tier = feature_requirements.get(feature, 'basic')
        
        return jsonify({
            'current_tier': current_tier,
            'required_tier': required_tier,
            'upgrade_url': f'https://whop.com/your-product-link?plan={required_tier}',
            'message': f'This feature requires {required_tier.capitalize()} tier. Upgrade now!'
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rally-details/<int:rally_id>', methods=['POST'])
def get_rally_details(rally_id):
    """
    Get detailed tweet information for a specific rally
    
    This endpoint would need to store rally results temporarily
    or re-run analysis. For now, it's a placeholder.
    """
    return jsonify({
        'error': 'Not implemented',
        'message': 'Store rally results in session or database first'
    }), 501


@app.route('/api/account-profile/<author_id>', methods=['POST'])
def get_account_profile(author_id):
    """
    Get detailed profile for a specific account
    Including all their tweets across rallies
    """
    try:
        data = request.json
        twitter_token = data.get('twitter_token')
        
        if not twitter_token:
            return jsonify({'error': 'twitter_token required'}), 400
        
        # Initialize extractor
        extractor = TwitterTweetExtractor(bearer_token=twitter_token)
        
        # Get user info
        user_info = extractor.get_user_info([author_id])
        
        if str(author_id) not in user_info:
            return jsonify({'error': 'User not found'}), 404
        
        profile = user_info[str(author_id)]
        
        return jsonify({
            'success': True,
            'profile': profile
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': 'Failed to fetch profile',
            'message': str(e)
        }), 500


# ============================================================================
# HOMEPAGE ROUTE - Add this to fix 404
# ============================================================================

@app.route('/')
def homepage():
    """Homepage with API documentation"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>SIFTER KYS API Server</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }
            h2 { color: #555; margin-top: 30px; }
            .endpoint { background: #f9f9f9; padding: 15px; margin: 10px 0; border-left: 4px solid #4CAF50; }
            .method { display: inline-block; padding: 3px 10px; background: #4CAF50; color: white; border-radius: 3px; margin-right: 10px; font-weight: bold; }
            .path { font-family: monospace; color: #333; }
            .desc { color: #666; margin-top: 5px; }
            .status { float: right; background: #4CAF50; color: white; padding: 3px 8px; border-radius: 3px; }
            a { color: #4CAF50; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 SIFTER KYS API Server v2.0</h1>
            <div class="status">🟢 RUNNING</div>
            
            <p>Welcome to the Social Network Analysis API for cryptocurrency pump detection.</p>
            
            <h2>📡 Available Endpoints</h2>
            
            <div class="endpoint">
                <span class="method">POST</span>
                <span class="path">/api/analyze</span>
                <div class="desc">Analyze a single token for pump activity and Twitter coordination</div>
            </div>
            
            <div class="endpoint">
                <span class="method">POST</span>
                <span class="path">/api/batch-analyze</span>
                <div class="desc">Analyze multiple tokens from CSV or list</div>
            </div>
            
            <div class="endpoint">
                <span class="method">GET</span>
                <span class="path">/api/watchlist</span>
                <div class="desc">Get user's watchlist of tracked accounts</div>
            </div>
            
            <div class="endpoint">
                <span class="method">GET</span>
                <span class="path">/health</span>
                <div class="desc">Health check endpoint</div>
            </div>
            
            <h2>🔧 Quick Testing</h2>
            <ul>
                <li><a href="/health" target="_blank">Test Health Endpoint</a></li>
                <li>Use <strong>Postman</strong> or <strong>curl</strong> to test POST endpoints</li>
                <li>API documentation available in server startup message</li>
            </ul>
            
            <h2>📊 Server Info</h2>
            <p><strong>Port:</strong> 5000</p>
            <p><strong>Debug Mode:</strong> Active</p>
            <p><strong>Features:</strong> Launch-anchored windows, SNA, Batch analysis, Whop integration</p>
            
            <hr>
            <p style="color: #888; font-size: 0.9em;">
                Check the console for the complete API documentation with all available endpoints.
            </p>
        </div>
    </body>
    </html>
    '''

# This should be the last route before the app.run() block


if __name__ == '__main__':
    print("""
╔════════════════════════════════════════════════════════════════╗
║              SIFTER KYS API SERVER v2.0                        ║
╚════════════════════════════════════════════════════════════════╝

✨ NEW FEATURES:
  - Launch-anchored time windows (first_24h, first_7d, etc.)
  - Expanded Social Network Analysis
  - Batch token analysis (CSV support)
  - Cross-token caller tracking
  - Watchlist management
  - Whop subscription integration

API Endpoints:
  Authentication & Access:
    POST /api/check-access           - Check user subscription tier
    POST /api/upgrade-prompt          - Get upgrade information
    POST /api/whop-webhook            - Handle Whop events
  
  Core Analysis:
    POST /api/analyze                 - Analyze single token
    POST /api/batch-analyze           - Analyze multiple tokens
    POST /api/expanded-sna            - Deep network analysis
  
  Watchlist:
    GET  /api/watchlist               - Get watchlist
    POST /api/watchlist/add           - Add to watchlist
    POST /api/watchlist/remove        - Remove from watchlist
    POST /api/watchlist/update        - Update notes/tags
    GET  /api/watchlist/groups        - Get groups
    POST /api/watchlist/groups/create - Create group
    GET  /api/watchlist/history/<id>  - Get account history
  
  Utilities:
    POST /api/export-batch-csv        - Export batch results
    POST /api/rally-details/<id>      - Get rally details
    POST /api/account-profile/<id>    - Get account profile
    GET  /health                      - Health check

Starting server on http://localhost:5000
""")
    
    app.run(debug=True, host='0.0.0.0', port=5000)