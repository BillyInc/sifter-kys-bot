import sys
import json
from datetime import datetime, timedelta

# Import your rally detector
from pump_detector import PrecisionRallyDetector


# Import new modules
from tweet_extractor import TwitterTweetExtractor
from nlp_disambiguator import NLPDisambiguator


class RallyTweetConnector:
    def __init__(self, birdeye_api_key, twitter_bearer_token):
        """
        Connect rally detection with tweet extraction
        
        Args:
            birdeye_api_key: Your Birdeye API key
            twitter_bearer_token: Your Twitter Bearer Token
        """
        self.rally_detector = PrecisionRallyDetector(birdeye_api_key=birdeye_api_key)
        self.tweet_extractor = TwitterTweetExtractor(bearer_token=twitter_bearer_token)
    
    def analyze_token_with_tweets(self, token_address, days_back=7):
        """
        Main pipeline: Detect rallies → Extract tweets → Score → Display
        
        Args:
            token_address: Token contract address
            days_back: Days of price data to analyze (max 7 for free Twitter API)
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
        
        # Build token profile for NLP
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
        print(f"[STEP 2/4] Detecting rallies in last {days_back} days...")
        
        pair_address = pair_data['pairAddress']
        chain_name = self.rally_detector.get_chain_name(pair_data['chainId'])
        
        ohlcv_data = self.rally_detector.get_ohlcv_data(pair_address, chain_name, days_back)
        
        if not ohlcv_data:
            print("❌ Failed to fetch OHLCV data")
            return None
        
        rallies = self.rally_detector.detect_all_rallies(ohlcv_data)
        
        if not rallies:
            print("\n❌ No rallies detected in the specified time period")
            return None
        
        print(f"\n✓ Detected {len(rallies)} rally/rallies\n")
        
        # STEP 3: Extract tweets for each rally
        print(f"[STEP 3/4] Extracting tweets for each rally...")
        
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
            
            # Extract tweets
            tweets = self.tweet_extractor.search_tweets_for_rally(
                token_ticker=token_profile['ticker'],
                token_name=token_profile['name'],
                rally_start_time=rally_start,
                t_minus_minutes=35,
                t_plus_minutes=10
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
            
            # STEP 4: Score tweets with NLP
            print(f"\n[SCORING] Applying NLP disambiguation to {len(tweets)} tweets...")
            
            scored_tweets = []
            
            for tweet in tweets:
                score_result = nlp_scorer.score_tweet(tweet)
                
                if score_result['accept']:
                    scored_tweets.append({
                        'tweet': tweet,
                        'score': score_result
                    })
            
            # Sort by score
            scored_tweets.sort(key=lambda x: x['score']['total_score'], reverse=True)
            
            print(f"   → {len(scored_tweets)} tweets passed filtering")
            print(f"   → Confidence breakdown:")
            
            high_conf = [t for t in scored_tweets if t['score']['confidence'] == 'high']
            medium_conf = [t for t in scored_tweets if t['score']['confidence'] == 'medium']
            
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
    print("""
╔══════════════════════════════════════════════════════════════════════════════════════════════╗
║                           RALLY + TWEET ANALYSIS TOOL                                        ║
╚══════════════════════════════════════════════════════════════════════════════════════════════╝

This tool:
1. Detects price rallies using precision candle analysis
2. Searches Twitter for mentions during T-35 to T+10 windows
3. Scores tweets using NLP disambiguation
4. Shows you WHO tweeted BEFORE pumps

⚠️  FREE TWITTER API LIMITS:
   • 100 tweets/month total
   • Last 7 days only
   • Recommend analyzing 1-2 rallies max per month
""")
    
    # Configuration
    BIRDEYE_API_KEY = "35d3d50f74d94c439f6913a7e82cf994"
    
    print("Enter your Twitter Bearer Token:")
    TWITTER_BEARER_TOKEN = input("Bearer Token: ").strip()
    
    if not TWITTER_BEARER_TOKEN:
        print("\n❌ No Twitter token provided")
        return
    
    # Initialize connector
    connector = RallyTweetConnector(
        birdeye_api_key=BIRDEYE_API_KEY,
        twitter_bearer_token=TWITTER_BEARER_TOKEN
    )
    print("\n[Testing Twitter API connection...]")
    if not connector.tweet_extractor.test_connection():
        print("\n⚠️ Twitter API test failed. Please check:")
        print("   1. Your Bearer Token is correct")
        print("   2. Your Twitter API access level (Free tier won't work for search)")
        print("   3. Twitter API status: https://api.twitterstat.us/")
        
        proceed = input("\nContinue anyway? (y/n): ").strip().lower()
        if proceed != 'y':
            return
    # Get token address
    print("\nEnter token contract address (must be <7 days old for Twitter search):")
    token_address = input("Token: ").strip()
    
    if not token_address:
        print("❌ No token address provided")
        return
    
    # Get days back (max 7 for free Twitter API)
    days_input = input("\nDays of data to analyze (default 7, max 7 for free Twitter API): ").strip()
    try:
        days_back = int(days_input) if days_input else 7
        days_back = min(days_back, 7)  # Cap at 7 for free API
    except ValueError:
        days_back = 7
    
    # Run analysis
    results = connector.analyze_token_with_tweets(token_address, days_back)
    
    if results:
        print("\n✅ Analysis complete!")
        print("\nYou can now:")
        print("  1. Review the tweets above")
        print("  2. Check if the accounts who tweeted actually called it early")
        print("  3. Verify the NLP scoring accuracy")


if __name__ == "__main__":
    main()