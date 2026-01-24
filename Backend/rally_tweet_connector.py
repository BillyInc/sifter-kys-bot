import os
from datetime import datetime, timedelta

from pump_detector import PrecisionRallyDetector
from tweet_extractor import TwitterTweetExtractor
from nlp_disambiguator import NLPDisambiguator


class RallyTweetConnector:
    def __init__(self, birdeye_api_key=None, twitter_bearer_token=None):
        """
        Connect rally detection with tweet extraction
        Now uses environment variables by default
        
        Args:
            birdeye_api_key: Optional Birdeye API key (uses env var if None)
            twitter_bearer_token: Optional Twitter Bearer Token (uses env var if None)
        """
        # Use provided keys or fallback to environment variables
        self.birdeye_api_key = birdeye_api_key or os.environ.get('BIRDEYE_API_KEY')
        self.twitter_bearer_token = twitter_bearer_token or os.environ.get('TWITTER_BEARER_TOKEN')
        
        # Initialize components
        self.rally_detector = PrecisionRallyDetector(birdeye_api_key=self.birdeye_api_key)
        self.tweet_extractor = TwitterTweetExtractor(bearer_token=self.twitter_bearer_token)
    
    def analyze_token_with_tweets(self, token_address, time_range='first_7d', 
                                  candle_size='5m', t_minus=35, t_plus=10):
        """
        Main pipeline: Detect rallies → Extract tweets → Score → Display
        
        Args:
            token_address: Token contract address
            time_range: Analysis timeframe ('first_7d', 'last_7d', etc.)
            candle_size: Candle size ('1m', '5m', '15m', '1h', '4h', '1d')
            t_minus: Minutes before rally to search (configurable)
            t_plus: Minutes after rally to search (configurable)
        """
        print("\n" + "="*100)
        print("RALLY + TWEET ANALYSIS PIPELINE")
        print("="*100 + "\n")
        
        # STEP 1: Get token metadata
        print("[STEP 1/4] Fetching token metadata...")
        pair_data = self.rally_detector.get_token_data(token_address)
        
        if not pair_data:
            print("❌ Failed to fetch token data")
            return None
        
        # Build token profile
        token_profile = {
            'ticker': pair_data['baseToken']['symbol'],
            'name': pair_data['baseToken']['name'],
            'contract_address': token_address,
            'chain': pair_data['chainId'],
            'dex': pair_data['dexId']
        }
        
        print(f"\n✓ Token Profile:")
        print(f"  Ticker: {token_profile['ticker']}")
        print(f"  Name: {token_profile['name']}")
        print(f"  Chain: {token_profile['chain']}")
        print(f"  DEX: {token_profile['dex']}\n")
        
        # STEP 2: Detect rallies
        print(f"[STEP 2/4] Detecting rallies...")
        print(f"  Time range: {time_range}")
        print(f"  Candle size: {candle_size}")
        
        pair_address = pair_data['pairAddress']
        chain_name = self.rally_detector.get_chain_name(pair_data['chainId'])
        
        # Get launch time if needed
        launch_timestamp = None
        if time_range.startswith('first_'):
            launch_timestamp = self.rally_detector.get_token_launch_time(token_address)
        
        # Get OHLCV data
        ohlcv_data = self.rally_detector.get_ohlcv_data_with_launch(
            pair_address=pair_address,
            chain=chain_name,
            launch_timestamp=launch_timestamp,
            window_type=time_range,
            candle_size=candle_size
        )
        
        if not ohlcv_data:
            print("❌ Failed to fetch OHLCV data")
            return None
        
        # Detect rallies
        rallies = self.rally_detector.detect_all_rallies(ohlcv_data)
        
        if not rallies:
            print("\n❌ No rallies detected in the specified time period")
            return None
        
        print(f"\n✓ Detected {len(rallies)} rally/rallies\n")
        
        # STEP 3: Extract tweets for each rally
        print(f"[STEP 3/4] Extracting tweets for each rally...")
        print(f"  Tweet search window: T-{t_minus} to T+{t_plus} minutes")
        
        nlp_scorer = NLPDisambiguator(token_profile)
        rally_results = []
        
        for idx, rally in enumerate(rallies, 1):
            rally_start = datetime.fromtimestamp(rally['window'][0]['unix_time'])
            rally_end = datetime.fromtimestamp(rally['window'][-1]['unix_time'])
            
            print(f"\n{'─'*100}")
            print(f"RALLY #{idx}")
            print(f"  Start: {rally_start.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  End: {rally_end.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Gain: +{rally['total_gain']:.1f}%")
            print(f"{'─'*100}")
            
            # Extract tweets with configurable window
            tweets = self.tweet_extractor.search_tweets_for_rally(
                token_ticker=token_profile['ticker'],
                token_name=token_profile['name'],
                rally_start_time=rally_start,
                t_minus_minutes=t_minus,
                t_plus_minutes=t_plus
            )
            
            if not tweets:
                print(f"   → No tweets found for this rally\n")
                rally_results.append({
                    'rally': rally,
                    'rally_start': rally_start,
                    'tweets': [],
                    'scored_tweets': []
                })
                continue
            
            # Score tweets
            print(f"\n[SCORING] Applying NLP disambiguation to {len(tweets)} tweets...")
            
            scored_tweets = []
            
            for tweet in tweets:
                score_result = nlp_scorer.score_tweet(tweet)
                
                if score_result['accept']:
                    scored_tweets.append({
                        'tweet': tweet,
                        'score': score_result
                    })
            
            scored_tweets.sort(key=lambda x: x['score']['total_score'], reverse=True)
            
            print(f"   → {len(scored_tweets)} tweets passed filtering")
            
            high_conf = [t for t in scored_tweets if t['score']['confidence'] == 'high']
            medium_conf = [t for t in scored_tweets if t['score']['confidence'] == 'medium']
            
            print(f"   → Confidence breakdown:")
            print(f"      • High confidence: {len(high_conf)}")
            print(f"      • Medium confidence: {len(medium_conf)}\n")
            
            # Display top tweets
            if scored_tweets:
                print(f"   TOP 5 TWEETS:")
                for i, st in enumerate(scored_tweets[:5], 1):
                    tweet = st['tweet']
                    score = st['score']
                    
                    print(f"\n   [{i}] Score: {score['total_score']} | Confidence: {score['confidence'].upper()}")
                    print(f"       Time: T{tweet['time_to_rally_minutes']:+.0f}m | Author: @{tweet['author_id']}")
                    print(f"       Text: {tweet['text'][:80]}...")
                    print(f"       Flags: {', '.join(score['flags'][:3])}")
            
            rally_results.append({
                'rally': rally,
                'rally_start': rally_start,
                'tweets': tweets,
                'scored_tweets': scored_tweets
            })
        
        # STEP 4: Display summary
        print(f"\n{'='*100}")
        print("ANALYSIS COMPLETE")
        print(f"{'='*100}\n")
        
        self._display_summary(rally_results, token_profile)
        
        return rally_results
    
    def _display_summary(self, rally_results, token_profile):
        """Display final summary"""
        print(f"TOKEN: {token_profile['ticker']} ({token_profile['name']})")
        print(f"RALLIES ANALYZED: {len(rally_results)}\n")
        
        for idx, result in enumerate(rally_results, 1):
            rally = result['rally']
            scored_tweets = result['scored_tweets']
            
            print(f"Rally #{idx}:")
            print(f"  Start: {result['rally_start'].strftime('%Y-%m-%d %H:%M')}")
            print(f"  Gain: +{rally['total_gain']:.1f}%")
            print(f"  Tweets found: {len(scored_tweets)}")
            
            if scored_tweets:
                high_conf = [t for t in scored_tweets if t['score']['confidence'] == 'high']
                
                if high_conf:
                    print(f"  Early callers (high confidence):")
                    for st in high_conf[:3]:
                        tweet = st['tweet']
                        print(f"    • @{tweet['author_id']} at T{tweet['time_to_rally_minutes']:+.0f}m")
            
            print()
        
        print(f"Total tweets extracted: {sum(len(r['tweets']) for r in rally_results)}")
        print(f"High-confidence tweets: {sum(len([t for t in r['scored_tweets'] if t['score']['confidence'] == 'high']) for r in rally_results)}")
        print(f"\nTwitter API quota used: {self.tweet_extractor.tweets_used_this_month}/100\n")


def main():
    """Example usage with environment variables"""
    print("""
╔══════════════════════════════════════════════════════════════════════════════════════════════╗
║                           RALLY + TWEET ANALYSIS TOOL v3.0                                   ║
╚══════════════════════════════════════════════════════════════════════════════════════════════╝

This tool:
1. Detects price rallies using precision candle analysis
2. Searches Twitter for mentions during configurable time windows
3. Scores tweets using NLP disambiguation
4. Shows you WHO tweeted BEFORE pumps

Configuration:
  - API keys loaded from environment variables
  - Configurable analysis timeframes
  - Customizable candle sizes
  - Adjustable tweet search windows

⚠️  Requirements:
   • BIRDEYE_API_KEY environment variable
   • TWITTER_BEARER_TOKEN environment variable
""")
    
    # Check environment variables
    birdeye_key = os.environ.get('BIRDEYE_API_KEY')
    twitter_token = os.environ.get('TWITTER_BEARER_TOKEN')
    
    if not birdeye_key:
        print("❌ BIRDEYE_API_KEY environment variable not set")
        birdeye_key = input("Enter Birdeye API Key: ").strip()
    
    if not twitter_token:
        print("❌ TWITTER_BEARER_TOKEN environment variable not set")
        twitter_token = input("Enter Twitter Bearer Token: ").strip()
    
    if not birdeye_key or not twitter_token:
        print("\n❌ API keys are required")
        return
    
    # Initialize connector
    connector = RallyTweetConnector(
        birdeye_api_key=birdeye_key,
        twitter_bearer_token=twitter_token
    )
    
    print("\n[Testing Twitter API connection...]")
    if not connector.tweet_extractor.test_connection():
        print("\n⚠️ Twitter API test failed")
        proceed = input("\nContinue anyway? (y/n): ").strip().lower()
        if proceed != 'y':
            return
    
    # Get token address
    print("\nEnter token contract address:")
    token_address = input("Token: ").strip()
    
    if not token_address:
        print("❌ No token address provided")
        return
    
    # Get analysis settings
    print("\nAnalysis Settings:")
    print("1. Time range (first_5m, first_24h, first_7d, last_7d, etc.)")
    time_range = input("Time range [first_7d]: ").strip() or 'first_7d'
    
    print("2. Candle size (1m, 5m, 15m, 1h, 4h, 1d)")
    candle_size = input("Candle size [5m]: ").strip() or '5m'
    
    print("3. Tweet search window")
    t_minus = int(input("T-minus minutes [35]: ").strip() or '35')
    t_plus = int(input("T-plus minutes [10]: ").strip() or '10')
    
    # Run analysis
    results = connector.analyze_token_with_tweets(
        token_address=token_address,
        time_range=time_range,
        candle_size=candle_size,
        t_minus=t_minus,
        t_plus=t_plus
    )
    
    if results:
        print("\n✅ Analysis complete!")
        print("\nYou can now:")
        print("  1. Review the tweets above")
        print("  2. Check if the accounts who tweeted actually called it early")
        print("  3. Verify the NLP scoring accuracy")


if __name__ == "__main__":
    main()