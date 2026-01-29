import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import threading


class TwitterAPIKeyPool:
    """
    Manages multiple TwitterAPI.io API keys with rotation and failover
    
    Features:
    - Round-robin key rotation
    - Automatic failover when keys hit rate limits
    - Cooldown tracking for rate-limited keys
    - Thread-safe for concurrent requests
    """
    
    def __init__(self, api_keys: List[Dict[str, str]], cooldown_minutes: int = 15):
        """
        Initialize the API key pool
        
        Args:
            api_keys: List of dicts with format:
                [
                    {'user_id': '405920194964049920', 'api_key': 'new1_f62e...', 'name': 'dnjunu'},
                    {'user_id': '405944251155873792', 'api_key': 'new1_8c0a...', 'name': 'Ptrsamuelchinedu'},
                    ...
                ]
            cooldown_minutes: Minutes to wait before retrying rate-limited keys
        """
        self.all_keys = api_keys
        self.active_keys = list(api_keys)  # Keys ready to use
        self.rate_limited_keys = {}  # {api_key: cooldown_until_timestamp}
        self.failed_keys = []  # Keys with auth errors
        
        self.cooldown_minutes = cooldown_minutes
        self.current_index = 0
        self.lock = threading.Lock()
        
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'rate_limit_hits': 0,
            'auth_failures': 0,
            'key_usage': {key['api_key']: 0 for key in api_keys}
        }
        
        print(f"[API POOL] Initialized with {len(api_keys)} keys")
        print(f"[API POOL] Cooldown period: {cooldown_minutes} minutes")
    
    
    def get_next_key(self) -> Optional[Dict[str, str]]:
        """
        Get the next available API key (thread-safe)
        
        Returns:
            Dict with key info, or None if no keys available
        """
        with self.lock:
            # First, check if any rate-limited keys have cooled down
            self._check_cooldowns()
            
            if not self.active_keys:
                print(f"[API POOL] ⚠️ No active keys available!")
                print(f"[API POOL]    Rate-limited: {len(self.rate_limited_keys)}")
                print(f"[API POOL]    Failed: {len(self.failed_keys)}")
                return None
            
            # Get next key (round-robin)
            key_info = self.active_keys[self.current_index % len(self.active_keys)]
            
            # Move to next key for next request
            self.current_index = (self.current_index + 1) % len(self.active_keys)
            
            # Track usage
            self.stats['total_requests'] += 1
            self.stats['key_usage'][key_info['api_key']] += 1
            
            return key_info
    
    
    def mark_rate_limited(self, api_key: str):
        """
        Mark a key as rate-limited and move to cooldown
        
        Args:
            api_key: The API key that hit rate limit
        """
        with self.lock:
            # Calculate cooldown until time
            cooldown_until = datetime.now() + timedelta(minutes=self.cooldown_minutes)
            
            # Remove from active keys
            self.active_keys = [k for k in self.active_keys if k['api_key'] != api_key]
            
            # Add to rate-limited with cooldown timestamp
            self.rate_limited_keys[api_key] = cooldown_until
            
            # Update stats
            self.stats['rate_limit_hits'] += 1
            
            key_name = next((k['name'] for k in self.all_keys if k['api_key'] == api_key), 'Unknown')
            
            print(f"[API POOL] ⏸️  Key rate-limited: {key_name}")
            print(f"[API POOL]    Cooldown until: {cooldown_until.strftime('%H:%M:%S')}")
            print(f"[API POOL]    Active keys remaining: {len(self.active_keys)}")
    
    
    def mark_failed(self, api_key: str):
        """
        Mark a key as permanently failed (auth error)
        
        Args:
            api_key: The API key that failed authentication
        """
        with self.lock:
            # Remove from active keys
            self.active_keys = [k for k in self.active_keys if k['api_key'] != api_key]
            
            # Add to failed keys
            failed_key_info = next((k for k in self.all_keys if k['api_key'] == api_key), None)
            if failed_key_info and failed_key_info not in self.failed_keys:
                self.failed_keys.append(failed_key_info)
            
            # Update stats
            self.stats['auth_failures'] += 1
            
            key_name = next((k['name'] for k in self.all_keys if k['api_key'] == api_key), 'Unknown')
            
            print(f"[API POOL] ❌ Key failed (auth error): {key_name}")
            print(f"[API POOL]    Active keys remaining: {len(self.active_keys)}")
    
    
    def mark_success(self, api_key: str):
        """
        Mark a successful request (for stats tracking)
        
        Args:
            api_key: The API key that succeeded
        """
        with self.lock:
            self.stats['successful_requests'] += 1
    
    
    def _check_cooldowns(self):
        """
        Internal: Check if any rate-limited keys have cooled down
        """
        now = datetime.now()
        recovered_keys = []
        
        for api_key, cooldown_until in list(self.rate_limited_keys.items()):
            if now >= cooldown_until:
                # Cooldown expired, restore to active pool
                key_info = next((k for k in self.all_keys if k['api_key'] == api_key), None)
                
                if key_info:
                    self.active_keys.append(key_info)
                    recovered_keys.append(key_info['name'])
                
                del self.rate_limited_keys[api_key]
        
        if recovered_keys:
            print(f"[API POOL] ✅ Keys recovered from cooldown: {', '.join(recovered_keys)}")
    
    
    def get_status(self) -> Dict:
        """
        Get current pool status
        
        Returns:
            Dictionary with pool statistics
        """
        with self.lock:
            return {
                'total_keys': len(self.all_keys),
                'active_keys': len(self.active_keys),
                'rate_limited_keys': len(self.rate_limited_keys),
                'failed_keys': len(self.failed_keys),
                'stats': {
                    'total_requests': self.stats['total_requests'],
                    'successful_requests': self.stats['successful_requests'],
                    'rate_limit_hits': self.stats['rate_limit_hits'],
                    'auth_failures': self.stats['auth_failures'],
                    'success_rate': round(
                        (self.stats['successful_requests'] / self.stats['total_requests'] * 100) 
                        if self.stats['total_requests'] > 0 else 0, 
                        2
                    )
                }
            }
    
    
    def print_status(self):
        """Print formatted status report"""
        status = self.get_status()
        
        print(f"\n{'='*80}")
        print(f"API KEY POOL STATUS")
        print(f"{'='*80}")
        print(f"Total Keys: {status['total_keys']}")
        print(f"Active: {status['active_keys']} | Rate-Limited: {status['rate_limited_keys']} | Failed: {status['failed_keys']}")
        print(f"\nRequest Stats:")
        print(f"  Total: {status['stats']['total_requests']}")
        print(f"  Successful: {status['stats']['successful_requests']}")
        print(f"  Rate Limits Hit: {status['stats']['rate_limit_hits']}")
        print(f"  Auth Failures: {status['stats']['auth_failures']}")
        print(f"  Success Rate: {status['stats']['success_rate']}%")
        print(f"{'='*80}\n")
    
    
    def get_top_used_keys(self, top_n: int = 5) -> List[Dict]:
        """
        Get the most-used keys
        
        Args:
            top_n: Number of top keys to return
        
        Returns:
            List of dicts with key info and usage count
        """
        with self.lock:
            usage_list = []
            
            for key_info in self.all_keys:
                api_key = key_info['api_key']
                usage_count = self.stats['key_usage'].get(api_key, 0)
                
                usage_list.append({
                    'name': key_info['name'],
                    'user_id': key_info['user_id'],
                    'usage_count': usage_count
                })
            
            # Sort by usage
            usage_list.sort(key=lambda x: x['usage_count'], reverse=True)
            
            return usage_list[:top_n]


# Example usage
if __name__ == "__main__":
    # ALL 23 API keys from your list
    all_api_keys = [
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
    
    # Initialize pool with all 23 keys
    pool = TwitterAPIKeyPool(all_api_keys)
    
    print(f"\n✅ API Key Pool initialized with {len(all_api_keys)} keys\n")
    
    # Simulate requests
    for i in range(10):
        key = pool.get_next_key()
        if key:
            print(f"Request {i+1}: Using {key['name']}")
            
            # Simulate occasional rate limit
            if i == 5:
                pool.mark_rate_limited(key['api_key'])
            else:
                pool.mark_success(key['api_key'])
    
    # Print status
    pool.print_status()