import os
from datetime import datetime, timedelta

from analyzers import PrecisionRallyDetector, NLPDisambiguator
from .tweet_extractor import TwitterTweetExtractor


class RallyTweetConnector:
    def __init__(self, birdeye_api_key=None, api_key_pool=None):
        """
        Connect rally detection with tweet extraction

        Args:
            birdeye_api_key: Optional Birdeye API key (uses env var if None)
            api_key_pool: TwitterAPIKeyPool instance for multi-key rotation
        """
        # Use provided keys or fallback to environment variables
        self.birdeye_api_key = birdeye_api_key or os.environ.get('BIRDEYE_API_KEY')
        self.api_key_pool = api_key_pool

        # Initialize components
        self.rally_detector = PrecisionRallyDetector(birdeye_api_key=self.birdeye_api_key)

        # Initialize tweet extractor with api_key_pool
        if api_key_pool:
            self.tweet_extractor = TwitterTweetExtractor(api_key_pool=api_key_pool)
        else:
            print("[WARNING] No API key pool provided - Twitter functionality disabled")
            self.tweet_extractor = None

    def analyze_token_with_tweets(self, token_address, days_back=7,
                                  candle_size='5m', t_minus=35, t_plus=10):
        """
        Main pipeline: Detect rallies → Extract tweets → Score → Display

        Args:
            token_address: Token contract address
            days_back: Number of days to analyze (1-90)
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
        print(f"  Days back: {days_back}")
        print(f"  Candle size: {candle_size}")

        pair_address = pair_data['pairAddress']
        chain_name = self.rally_detector.get_chain_name(pair_data['chainId'])

        # SIMPLIFIED: Just use days_back and candle_size
        ohlcv_data = self.rally_detector.get_ohlcv_data(
            pair_address=pair_address,
            chain=chain_name,
            days_back=days_back,
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
        if not self.tweet_extractor:
            print("⚠️ Twitter extractor not initialized - skipping tweet analysis")
            return None

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
        print(f"High-confidence tweets: {sum(len([t for t in r['scored_tweets'] if t['score']['confidence'] == 'high']) for r in rally_results)}\n")


def main():
    """Example usage with API key pool"""
    print("""
╔══════════════════════════════════════════════════════════════════════════════════════════════╗
║                           RALLY + TWEET ANALYSIS TOOL v6.0                                   ║
╚══════════════════════════════════════════════════════════════════════════════════════════════╝

This tool:
1. Detects price rallies using precision candle analysis
2. Searches Twitter for mentions during configurable time windows
3. Scores tweets using NLP disambiguation
4. Shows you WHO tweeted BEFORE pumps

Configuration:
  - Multi-key API rotation with automatic failover
  - Simple days_back parameter (1-90)
  - Customizable candle sizes
  - Adjustable tweet search windows

⚠️  Requirements:
   • BIRDEYE_API_KEY environment variable
   • Multiple TwitterAPI.io keys configured
""")

    # Check environment variables
    birdeye_key = os.environ.get('BIRDEYE_API_KEY')

    if not birdeye_key:
        print("❌ BIRDEYE_API_KEY environment variable not set")
        birdeye_key = input("Enter Birdeye API Key: ").strip()

    if not birdeye_key:
        print("\n❌ Birdeye API key is required")
        return

    # Import here to avoid circular imports
    from .twitter_api_pool import TwitterAPIKeyPool

    # Initialize API key pool (example with 2 keys)
    api_keys = [
        {'user_id': '405920194964049920', 'api_key': 'new1_f62eefe95d5349938ea4f77ca8f198ad', 'name': 'dnjunu'},
        {'user_id': '405944251155873792', 'api_key': 'new1_8c0aabf38b194412903658bfc9c0bdca', 'name': 'Ptrsamuelchinedu'},
    ]

    api_pool = TwitterAPIKeyPool(api_keys)

    # Initialize connector
    connector = RallyTweetConnector(
        birdeye_api_key=birdeye_key,
        api_key_pool=api_pool
    )

    # Get token address
    print("\nEnter token contract address:")
    token_address = input("Token: ").strip()

    if not token_address:
        print("❌ No token address provided")
        return

    # Get analysis settings
    print("\nAnalysis Settings:")
    days_input = input("Days back (1-90) [default 7]: ").strip()
    try:
        days_back = int(days_input) if days_input else 7
        days_back = max(1, min(days_back, 90))
    except ValueError:
        days_back = 7

    print("Candle size options: 1m, 5m, 15m, 1h, 4h, 1d")
    candle_size = input("Candle size [5m]: ").strip() or '5m'

    print("\nTweet search window:")
    t_minus = int(input("T-minus minutes [35]: ").strip() or '35')
    t_plus = int(input("T-plus minutes [10]: ").strip() or '10')

    # Run analysis
    results = connector.analyze_token_with_tweets(
        token_address=token_address,
        days_back=days_back,
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
