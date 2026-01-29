import requests
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import time
from typing import List, Dict, Optional
from .twitter_api_pool import TwitterAPIKeyPool


class TwitterTweetExtractor:
    """
    Twitter data extractor using TwitterAPI.io
    Fixed version with proper time filtering and query structure
    """
    
    def __init__(self, api_key_pool: TwitterAPIKeyPool):
        """
        Initialize with API key pool
        
        Args:
            api_key_pool: TwitterAPIKeyPool instance managing multiple keys
        """
        self.api_pool = api_key_pool
        self.base_url = "https://api.twitterapi.io"
        
        print(f"[TWEET EXTRACTOR] Initialized with {self.api_pool.get_status()['active_keys']} active API keys")
    
    
    def _make_request(self, endpoint: str, params: Dict = None, max_retries: int = 3) -> Optional[Dict]:
        """
        Make API request with automatic key rotation and retry logic
        
        Args:
            endpoint: API endpoint (e.g., '/twitter/tweet/advanced_search')
            params: Query parameters
            max_retries: Maximum retry attempts with different keys
        
        Returns:
            API response JSON or None if all retries failed
        """
        attempts = 0
        
        while attempts < max_retries:
            # Get next available key
            key_info = self.api_pool.get_next_key()
            
            if not key_info:
                print(f"[TWEET EXTRACTOR] ❌ No API keys available")
                return None
            
            api_key = key_info['api_key']
            key_name = key_info['name']
            
            # Make request
            url = f"{self.base_url}{endpoint}"
            headers = {'x-api-key': api_key}
            
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
                
                # Handle different response codes
                if response.status_code == 200:
                    self.api_pool.mark_success(api_key)
                    return response.json()
                
                elif response.status_code == 429:
                    # Rate limit hit
                    print(f"[TWEET EXTRACTOR] ⏸️  Rate limit hit on key: {key_name}")
                    self.api_pool.mark_rate_limited(api_key)
                    attempts += 1
                    continue
                
                elif response.status_code in [401, 403]:
                    # Authentication error
                    print(f"[TWEET EXTRACTOR] ❌ Auth error on key: {key_name}")
                    self.api_pool.mark_failed(api_key)
                    attempts += 1
                    continue
                
                else:
                    # Other error
                    print(f"[TWEET EXTRACTOR] ⚠️  HTTP {response.status_code}: {response.text[:100]}")
                    attempts += 1
                    time.sleep(2)
                    continue
            
            except requests.exceptions.RequestException as e:
                print(f"[TWEET EXTRACTOR] ⚠️  Request error: {e}")
                attempts += 1
                time.sleep(2)
                continue
        
        print(f"[TWEET EXTRACTOR] ❌ All retry attempts failed for endpoint: {endpoint}")
        return None
    
    
    def _parse_tweet_timestamp(self, created_at_raw) -> Optional[datetime]:
        """
        Parse tweet timestamp with support for multiple formats
        
        Args:
            created_at_raw: Raw timestamp (string, int, or float)
        
        Returns:
            datetime object or None if parsing fails
        """
        try:
            if isinstance(created_at_raw, str):
                # FIXED: Check position 10 to avoid matching "Tuesday"
                if 'T' in created_at_raw and len(created_at_raw) > 10 and created_at_raw[10] == 'T':
                    # ISO format: "2026-01-23T09:35:00Z"
                    tweet_time = datetime.fromisoformat(created_at_raw.replace('Z', '+00:00'))
                    return tweet_time.replace(tzinfo=None)
                
                elif '+0000' in created_at_raw or 'GMT' in created_at_raw:
                    # RFC 2822 format: "Fri Jan 23 11:50:19 +0000 2026"
                    tweet_time = parsedate_to_datetime(created_at_raw)
                    return tweet_time.replace(tzinfo=None)
                
                else:
                    # Unix timestamp as string
                    tweet_time = datetime.fromtimestamp(float(created_at_raw))
                    return tweet_time
            
            else:
                # Unix timestamp as integer/float
                tweet_time = datetime.fromtimestamp(created_at_raw)
                return tweet_time
        
        except Exception as e:
            print(f"      [WARNING] Could not parse timestamp: {created_at_raw} - Error: {e}")
            return None
    
    
    def search_tweets_for_rally(
        self, 
        token_ticker: str, 
        token_name: str, 
        rally_start_time: datetime,
        t_minus_minutes: int = 35, 
        t_plus_minutes: int = 10
    ) -> List[Dict]:
        """
        Search tweets for a specific rally window with improved query filtering
        
        Args:
            token_ticker: e.g., "BONK"
            token_name: e.g., "Bonk Inu"
            rally_start_time: datetime object of rally start
            t_minus_minutes: Minutes before rally
            t_plus_minutes: Minutes after rally
        
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
        
        # Build mandatory crypto context - makes Query 2 require crypto signals
        crypto_mandatory = (
            "(pump.fun OR pumpfun OR dexscreener OR birdeye OR "
            "ca: OR contract OR 0x OR bought OR ape OR call OR shill OR "
            "mc OR mcap OR loading OR adding)"
        )
        
        ticker = token_ticker.upper()
        
        # Build improved queries with mandatory filters
        queries = [
            # Query 1: Strict dollar ticker + crypto context (AND logic)
            f"${ticker} {crypto_mandatory} lang:en min_faves:2 min_retweets:1",
            
            # Query 2: Broad keyword BUT crypto context is MANDATORY (not optional)
            f"{ticker} {crypto_mandatory} lang:en min_faves:2 min_retweets:1",
            
            # Query 3: Momentum/Dip signals
            f"${ticker} (dip OR loading OR adding OR higher OR trenches OR \"vibe shift\") lang:en min_faves:2 min_retweets:1",
            
            # Query 4: Predictive/Setup signals
            f"${ticker} (\"will trade\" OR gonna OR \"paying attention\" OR setup) lang:en min_faves:2 min_retweets:1"
        ]
        
        # Add token name query if different from ticker
        if token_name and token_name.lower() != ticker.lower():
            queries.append(
                f"\"{token_name}\" (${ticker} OR {crypto_mandatory}) lang:en min_faves:2 min_retweets:1"
            )
        
        all_tweets = []
        tweets_outside_window = 0
        
        for query_idx, query in enumerate(queries, 1):
            print(f"[Query {query_idx}/{len(queries)}] Searching: '{query[:60]}...'")
            
            # Format timestamps for Twitter's advanced search syntax
            since_str = search_start.strftime('%Y-%m-%d_%H:%M:%S_UTC')
            until_str = search_end.strftime('%Y-%m-%d_%H:%M:%S_UTC')
            
            # Build query with time filters
            query_with_time = f"{query} since:{since_str} until:{until_str}"
            
            print(f"   Full query: {query_with_time}")
            
            # TwitterAPI.io Advanced Search endpoint
            params = {
                'query': query_with_time,
                'queryType': 'Latest',
                'cursor': ''
            }
            
            response = self._make_request('/twitter/tweet/advanced_search', params)
            
            print(f"   [DEBUG] API Response Status: {response.get('status') if response else 'None'}")
            if response:
                print(f"   [DEBUG] Response keys: {list(response.keys())}")
            
            if not response:
                print(f"   → No response from API\n")
                continue
            
            tweets = response.get('tweets', [])
            
            if not tweets:
                if response:
                    print(f"   [DEBUG] Full response: {response}")
                print(f"   → No tweets found\n")
                continue
            
            print(f"   → Found {len(tweets)} tweets\n")
            
            # Process tweets with improved timestamp parsing
            for tweet in tweets:
                created_at_raw = tweet.get('createdAt', 0)
                
                # Parse timestamp
                tweet_time = self._parse_tweet_timestamp(created_at_raw)
                
                if tweet_time is None:
                    continue
                
                # Calculate time to rally
                time_to_rally = (tweet_time - rally_start_time).total_seconds() / 60
                
                # CRITICAL FIX: Enforce strict time window filtering
                # Reject tweets outside T-minus to T+plus window
                if time_to_rally < -t_minus_minutes or time_to_rally > t_plus_minutes:
                    tweets_outside_window += 1
                    continue  # Skip this tweet
                
                tweet_data = {
                    'id': tweet.get('id'),
                    'text': tweet.get('text', ''),
                    'created_at': tweet_time,
                    'author_id': tweet.get('author', {}).get('id'),
                    'author_username': tweet.get('author', {}).get('userName'),
                    'likes': tweet.get('likeCount', 0),
                    'retweets': tweet.get('retweetCount', 0),
                    'replies': tweet.get('replyCount', 0),
                    'time_to_rally_minutes': round(time_to_rally, 1),
                    'search_query_used': query
                }
                
                all_tweets.append(tweet_data)
                
                # Preview
                status = "PRE" if time_to_rally < 0 else "POST"
                print(f"      [{status} T{time_to_rally:+.0f}m] @{tweet_data['author_username']}: {tweet_data['text'][:60]}...")
            
            time.sleep(1)
        
        # Deduplicate by tweet ID
        unique_tweets = {t['id']: t for t in all_tweets if t['id']}.values()
        
        print(f"\n{'─'*80}")
        print(f"SEARCH SUMMARY:")
        print(f"  Total tweets found: {len(unique_tweets)}")
        if tweets_outside_window > 0:
            print(f"  Tweets filtered (outside time window): {tweets_outside_window}")
        print(f"{'─'*80}\n")
        
        return list(unique_tweets)
    
    
    def get_user_info(self, user_ids: List[str]) -> Dict[str, Dict]:
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
        
        unique_ids = list(set(user_ids))
        user_info = {}
        
        for i in range(0, len(unique_ids), 100):
            batch = unique_ids[i:i+100]
            
            params = {
                'userIds': ','.join(batch)
            }
            
            response = self._make_request('/twitter/user/batch_info_by_ids', params)
            
            if not response or response.get('status') != 'success':
                print(f"   → Batch {i//100 + 1} failed")
                continue
            
            users = response.get('users', [])
            
            for user in users:
                user_id = str(user.get('id'))
                user_info[user_id] = {
                    'username': user.get('userName'),
                    'name': user.get('name'),
                    'followers': user.get('followers', 0),
                    'verified': user.get('isBlueVerified', False)
                }
            
            time.sleep(1)
        
        print(f"   → Retrieved info for {len(user_info)} accounts\n")
        return user_info
    
    
    def get_user_timeline(self, user_id: str, max_results: int = 100) -> List[Dict]:
        """
        Get recent tweets from a specific user
        
        Args:
            user_id: Twitter user ID
            max_results: Maximum tweets to fetch
        
        Returns:
            List of tweets
        """
        print(f"\n[TIMELINE] Fetching timeline for user {user_id}...")
        
        params = {
            'userId': user_id,
            'cursor': ''
        }
        
        response = self._make_request('/twitter/user/last_tweets', params)
        
        if not response or response.get('status') != 'success':
            print("[TIMELINE] No tweets found or API error")
            return []
        
        tweets_data = response.get('tweets', [])
        
        timeline = []
        
        for tweet in tweets_data[:max_results]:
            timeline.append({
                'id': tweet.get('id'),
                'text': tweet.get('text', ''),
                'created_at': datetime.fromtimestamp(tweet.get('createdAt', 0)),
                'likes': tweet.get('likeCount', 0),
                'retweets': tweet.get('retweetCount', 0)
            })
        
        print(f"[TIMELINE] Retrieved {len(timeline)} tweets")
        
        return timeline
    
    
    def get_account_interactions(
        self, 
        account_usernames: List[str], 
        days_back: int = 90
    ) -> Dict[str, List[Dict]]:
        """
        Fetch interactions (mentions, replies, RTs) between specific accounts
        
        Args:
            account_usernames: List of Twitter usernames
            days_back: Days to look back
        
        Returns:
            Dictionary with interaction data
        """
        print(f"\n[INTERACTIONS] Fetching interactions for {len(account_usernames)} accounts over {days_back} days...")
        
        all_interactions = {
            'mentions': [],
            'replies': [],
            'retweets': [],
            'quote_tweets': []
        }
        
        for username in account_usernames:
            params = {
                'userName': username,
                'sinceTime': int((datetime.now() - timedelta(days=days_back)).timestamp()),
                'cursor': ''
            }
            
            response = self._make_request('/twitter/user/mentions', params)
            
            if not response or response.get('status') != 'success':
                continue
            
            mentions = response.get('tweets', [])
            
            for tweet in mentions:
                author_username = tweet.get('author', {}).get('userName', '')
                
                if author_username in account_usernames:
                    all_interactions['mentions'].append({
                        'id': tweet.get('id'),
                        'text': tweet.get('text', ''),
                        'author_id': tweet.get('author', {}).get('id'),
                        'created_at': datetime.fromtimestamp(tweet.get('createdAt', 0)),
                        'mentioned_username': username
                    })
            
            time.sleep(1)
        
        print(f"[INTERACTIONS] Breakdown:")
        print(f"   Mentions: {len(all_interactions['mentions'])}")
        
        return all_interactions
    
    
    def get_user_followings(self, username: str, max_results: int = 200) -> List[str]:
        """
        Get list of user IDs that a user follows
        
        Args:
            username: Twitter username
            max_results: Maximum followings to fetch
        
        Returns:
            List of user IDs
        """
        print(f"[FOLLOWINGS] Fetching followings for @{username}...")
        
        params = {
            'userName': username,
            'cursor': '',
            'pageSize': min(max_results, 200)
        }
        
        response = self._make_request('/twitter/user/followings', params)
        
        if not response or response.get('status') != 'success':
            return []
        
        followings = response.get('followings', [])
        following_ids = [str(user.get('id')) for user in followings]
        
        print(f"   → Found {len(following_ids)} followings")
        
        return following_ids
    
    
    def get_user_followers(self, username: str, max_results: int = 200) -> List[str]:
        """
        Get list of user IDs who follow this user
        
        Args:
            username: Twitter username
            max_results: Maximum followers to fetch
        
        Returns:
            List of user IDs
        """
        print(f"[FOLLOWERS] Fetching followers for @{username}...")
        
        params = {
            'userName': username,
            'cursor': '',
            'pageSize': min(max_results, 200)
        }
        
        response = self._make_request('/twitter/user/followers', params)
        
        if not response or response.get('status') != 'success':
            return []
        
        followers = response.get('followers', [])
        follower_ids = [str(user.get('id')) for user in followers]
        
        print(f"   → Found {len(follower_ids)} followers")
        
        return follower_ids
    
    
    def check_follow_relationship(self, source_username: str, target_username: str) -> Dict[str, bool]:
        """
        Check if two users follow each other
        
        Args:
            source_username: Source user's username
            target_username: Target user's username
        
        Returns:
            Dict with 'following' and 'followed_by' booleans
        """
        params = {
            'source_user_name': source_username,
            'target_user_name': target_username
        }
        
        response = self._make_request('/twitter/user/check_follow_relationship', params)
        
        if not response or response.get('status') != 'success':
            return {'following': False, 'followed_by': False}
        
        data = response.get('data', {})
        
        return {
            'following': data.get('following', False),
            'followed_by': data.get('followed_by', False)
        }


# Testing function
if __name__ == "__main__":
    from .twitter_api_pool import TwitterAPIKeyPool
    
    all_keys = [
        {'user_id': '405920194964049920', 'api_key': 'new1_f62eefe95d5349938ea4f77ca8f198ad', 'name': 'dnjunu'}
    ]
    
    pool = TwitterAPIKeyPool(all_keys)
    
    print(f"\n✅ Initialized with {len(all_keys)} API keys\n")
    
    extractor = TwitterTweetExtractor(pool)
    
    # Test rally search with strict time filtering
    rally_time = datetime(2026, 1, 23, 10, 30, 0)  # Example rally
    
    tweets = extractor.search_tweets_for_rally(
        token_ticker='PENGUIN',
        token_name='Nietzschean Penguin',
        rally_start_time=rally_time,
        t_minus_minutes=35,
        t_plus_minutes=10
    )
    
    print(f"\n{'='*80}")
    print(f"RESULTS:")
    print(f"  Found {len(tweets)} tweets within time window")
    
    if tweets:
        print(f"\n  Time distribution:")
        pre_rally = sum(1 for t in tweets if t['time_to_rally_minutes'] < 0)
        post_rally = sum(1 for t in tweets if t['time_to_rally_minutes'] >= 0)
        print(f"    Pre-rally (T-35 to T0): {pre_rally}")
        print(f"    Post-rally (T0 to T+10): {post_rally}")
    
    print(f"{'='*80}\n")
    
    pool.print_status()