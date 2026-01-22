import tweepy
from datetime import datetime, timedelta
import time

class TwitterTweetExtractor:
    def __init__(self, bearer_token):
        """
        Initialize Twitter API client
        
        Args:
            bearer_token: Your Twitter API Bearer Token
        """
        self.client = tweepy.Client(bearer_token=bearer_token)
        self.monthly_tweet_limit = 100
        self.tweets_used_this_month = 0
    
    def test_connection(self):  # ← Must be indented at same level as __init__
        """Test if Twitter API credentials are valid"""
        try:
            # Try a simple API call that works on all tiers
            response = self.client.get_user(username="twitter")
            print("✅ Twitter API connection successful!")
            print(f"   Test user: {response.data.name} (@{response.data.username})")
            return True
        except tweepy.TweepyException as e:
            print(f"❌ Twitter API connection failed: {e}")
            return False
    
    def search_tweets_for_rally(self, token_ticker, token_name, rally_start_time, 
                                 t_minus_minutes=35, t_plus_minutes=10):
        """
        Search tweets for a specific rally window with EXACT date filtering
        
        Args:
            token_ticker: e.g., "BONK"
            token_name: e.g., "Bonk Inu"
            rally_start_time: datetime object of rally start
            t_minus_minutes: Minutes before rally to search (default 35)
            t_plus_minutes: Minutes after rally end to search (default 10)
        
        Returns:
            List of tweet dictionaries with metadata
        """
        
        # Calculate search window
        search_start = rally_start_time - timedelta(minutes=t_minus_minutes)
        search_end = rally_start_time + timedelta(minutes=t_plus_minutes)
        
        print(f"\n{'='*80}")
        print(f"SEARCHING TWITTER FOR RALLY")
        print(f"{'='*80}")
        print(f"Token: {token_ticker}")
        print(f"Rally Start: {rally_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Search Window: {search_start.strftime('%Y-%m-%d %H:%M:%S')} to {search_end.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Duration: T-{t_minus_minutes} to T+{t_plus_minutes}")
        print(f"{'='*80}\n")
        
        # Build search queries
        queries = self._build_search_queries(token_ticker, token_name)
        
        all_tweets = []
        
        for query_idx, query in enumerate(queries, 1):
            print(f"[Query {query_idx}/{len(queries)}] Searching: '{query}'")
            
            # Check quota
            if self.tweets_used_this_month >= self.monthly_tweet_limit:
                print(f"⚠️  QUOTA EXCEEDED: {self.tweets_used_this_month}/{self.monthly_tweet_limit} tweets used this month")
                print(f"   Skipping remaining queries to preserve quota")
                break
            
            try:
                # Call Twitter API with EXACT date filtering
                response = self.client.search_recent_tweets(
                    query=query,
                    start_time=search_start,  # ✅ EXACT START TIME
                    end_time=search_end,      # ✅ EXACT END TIME
                    max_results=10,
                    tweet_fields=['created_at', 'author_id', 'text', 'public_metrics']
                )
                
                if not response.data:
                    print(f"   → No tweets found\n")
                    continue
                
                tweets_found = len(response.data)
                self.tweets_used_this_month += tweets_found
                
                print(f"   → Found {tweets_found} tweets")
                print(f"   → Quota used: {self.tweets_used_this_month}/{self.monthly_tweet_limit}\n")
                
                # Process tweets
                for tweet in response.data:
                    tweet_time = tweet.created_at
                    time_to_rally = (tweet_time - rally_start_time).total_seconds() / 60
                    
                    tweet_data = {
                        'id': tweet.id,
                        'text': tweet.text,
                        'created_at': tweet_time,
                        'author_id': tweet.author_id,
                        'likes': tweet.public_metrics['like_count'],
                        'retweets': tweet.public_metrics['retweet_count'],
                        'replies': tweet.public_metrics['reply_count'],
                        'time_to_rally_minutes': round(time_to_rally, 1),
                        'search_query_used': query
                    }
                    
                    all_tweets.append(tweet_data)
                    
                    # Preview
                    status = "PRE" if time_to_rally < 0 else "POST"
                    print(f"      [{status} T{time_to_rally:+.0f}m] @{tweet.author_id}: {tweet.text[:60]}...")
                
                # Rate limiting (be nice to Twitter)
                time.sleep(2)
                
            except tweepy.TweepyException as e:
                print(f"   ❌ Twitter API Error: {e}\n")
                continue
            except Exception as e:
                print(f"   ❌ Unexpected Error: {e}\n")
                continue
        
        # Deduplicate by tweet ID
        unique_tweets = {t['id']: t for t in all_tweets}.values()
        
        print(f"\n{'─'*80}")
        print(f"SEARCH SUMMARY:")
        print(f"  Total tweets found: {len(unique_tweets)}")
        print(f"  Quota used this session: {self.tweets_used_this_month}/{self.monthly_tweet_limit}")
        print(f"{'─'*80}\n")
        
        return list(unique_tweets)
    
    def _build_search_queries(self, ticker, name):
        """
        Build optimized search queries to maximize relevance
        
        Strategy: Start broad, then narrow with context
        """
        queries = []
        
        # Query 1: Ticker with dollar sign (most common)
        queries.append(f"${ticker}")
        
        # Query 2: Ticker without dollar sign
        queries.append(f"{ticker}")
        
        # Query 3: Full name (if different from ticker)
        if name.lower() != ticker.lower():
            queries.append(f"{name}")
        
        return queries
    
    def get_user_info(self, user_ids):
        """
        Get user information for a list of user IDs
        Useful for seeing who tweeted
        
        Args:
            user_ids: List of Twitter user IDs
            
        Returns:
            Dictionary mapping user_id -> user info
        """
        if not user_ids:
            return {}
        
        print(f"\n[INFO] Fetching user info for {len(user_ids)} accounts...")
        
        try:
            # Remove duplicates
            unique_ids = list(set(user_ids))
            
            # Twitter API allows max 100 users per request
            user_info = {}
            
            for i in range(0, len(unique_ids), 100):
                batch = unique_ids[i:i+100]
                
                response = self.client.get_users(
                    ids=batch,
                    user_fields=['username', 'name', 'public_metrics', 'verified']
                )
                
                if response.data:
                    for user in response.data:
                        user_info[str(user.id)] = {
                            'username': user.username,
                            'name': user.name,
                            'followers': user.public_metrics['followers_count'],
                            'verified': user.verified if hasattr(user, 'verified') else False
                        }
                
                time.sleep(1)
            
            print(f"   → Retrieved info for {len(user_info)} accounts\n")
            return user_info
            
        except tweepy.TweepyException as e:
            print(f"   ❌ Error fetching user info: {e}\n")
            return {}