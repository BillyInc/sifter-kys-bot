import tweepy
from datetime import datetime, timedelta
import time
import os

class TwitterTweetExtractor:
    def __init__(self, bearer_token=None):
        """
        Initialize Twitter API client
        
        Args:
            bearer_token: Optional Twitter API Bearer Token (if None, uses env variable)
        """
        # Get bearer token from parameter or environment variable
        self.bearer_token = bearer_token or os.environ.get('TWITTER_BEARER_TOKEN')
        
        if not self.bearer_token:
            raise ValueError("Twitter Bearer Token is required. Set TWITTER_BEARER_TOKEN environment variable.")
        
        self.client = tweepy.Client(bearer_token=self.bearer_token)
        self.monthly_tweet_limit = 100
        self.tweets_used_this_month = 0
    
    def test_connection(self):
        """Test if Twitter API credentials are valid"""
        try:
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
            t_minus_minutes: Minutes before rally to search (configurable per token)
            t_plus_minutes: Minutes after rally to search (configurable per token)
        
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
                    start_time=search_start,
                    end_time=search_end,
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
                
                # Rate limiting
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
        """Build optimized search queries"""
        queries = []
        
        # Query 1: Ticker with dollar sign
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
    
    def get_account_interactions(self, account_usernames, days_back=90):
        """
        Fetch interactions (mentions, replies, retweets) between accounts
        
        Args:
            account_usernames: List of Twitter usernames
            days_back: Days to look back (default 90)
        
        Returns:
            Dictionary with interaction data
        """
        print(f"\n[INTERACTIONS] Fetching interactions for {len(account_usernames)} accounts over {days_back} days...")
        
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days_back)
        
        all_interactions = {
            'mentions': [],
            'replies': [],
            'retweets': [],
            'quote_tweets': []
        }
        
        # Build query
        username_list = ' OR '.join([f'@{u}' for u in account_usernames])
        from_list = ' OR '.join([f'from:{u}' for u in account_usernames])
        
        query = f"({from_list}) ({username_list}) -is:retweet"
        
        print(f"[INTERACTIONS] Query: {query[:100]}...")
        
        try:
            tweets = self.client.search_recent_tweets(
                query=query,
                start_time=start_time,
                end_time=end_time,
                max_results=100,
                tweet_fields=['created_at', 'author_id', 'referenced_tweets', 'entities'],
                expansions=['author_id', 'referenced_tweets.id']
            )
            
            if not tweets.data:
                print("[INTERACTIONS] No interactions found")
                return all_interactions
            
            print(f"[INTERACTIONS] Found {len(tweets.data)} interaction tweets")
            
            # Process tweets
            for tweet in tweets.data:
                tweet_data = {
                    'id': tweet.id,
                    'text': tweet.text,
                    'author_id': tweet.author_id,
                    'created_at': tweet.created_at
                }
                
                # Check for mentions
                if tweet.entities and 'mentions' in tweet.entities:
                    for mention in tweet.entities['mentions']:
                        all_interactions['mentions'].append({
                            **tweet_data,
                            'mentioned_user_id': mention['id'],
                            'mentioned_username': mention['username']
                        })
                
                # Check for replies/retweets
                if tweet.referenced_tweets:
                    for ref in tweet.referenced_tweets:
                        if ref.type == 'replied_to':
                            all_interactions['replies'].append({
                                **tweet_data,
                                'replied_to_id': ref.id
                            })
                        elif ref.type == 'retweeted':
                            all_interactions['retweets'].append({
                                **tweet_data,
                                'retweeted_id': ref.id
                            })
                        elif ref.type == 'quoted':
                            all_interactions['quote_tweets'].append({
                                **tweet_data,
                                'quoted_id': ref.id
                            })
            
            print(f"[INTERACTIONS] Breakdown:")
            print(f"   Mentions: {len(all_interactions['mentions'])}")
            print(f"   Replies: {len(all_interactions['replies'])}")
            print(f"   Retweets: {len(all_interactions['retweets'])}")
            print(f"   Quotes: {len(all_interactions['quote_tweets'])}")
            
            return all_interactions
            
        except tweepy.TweepyException as e:
            print(f"[INTERACTIONS] Twitter API error: {e}")
            return all_interactions
    
    def get_user_timeline(self, user_id, max_results=100):
        """
        Get recent tweets from a specific user
        
        Args:
            user_id: Twitter user ID
            max_results: Maximum tweets to fetch (default 100)
        
        Returns:
            List of tweets
        """
        print(f"\n[TIMELINE] Fetching timeline for user {user_id}...")
        
        try:
            tweets = self.client.get_users_tweets(
                id=user_id,
                max_results=max_results,
                tweet_fields=['created_at', 'text', 'public_metrics']
            )
            
            if not tweets.data:
                print("[TIMELINE] No tweets found")
                return []
            
            timeline = []
            
            for tweet in tweets.data:
                timeline.append({
                    'id': tweet.id,
                    'text': tweet.text,
                    'created_at': tweet.created_at,
                    'likes': tweet.public_metrics['like_count'],
                    'retweets': tweet.public_metrics['retweet_count']
                })
            
            print(f"[TIMELINE] Retrieved {len(timeline)} tweets")
            
            return timeline
            
        except tweepy.TweepyException as e:
            print(f"[TIMELINE] Error: {e}")
            return []