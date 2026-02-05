import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta
import time
import statistics

class PrecisionRallyDetector:
    """
    Rally detection using SolanaTracker for everything:
    - Token search
    - Token metadata
    - OHLCV data
    
    Solana-only implementation (multi-chain support removed for now)
    Used in both General Mode and Pump Mode for window detection
    
    UNBIASED PHILOSOPHY:
    - Rally detection is objective (price movement patterns)
    - No assumptions about "best" traders
    - Used as input for unbiased wallet discovery via /trades/{token}
    """
    
    def __init__(self, solanatracker_api_key=None):
        self.st_base_url = "https://data.solanatracker.io"
        self.api_key = solanatracker_api_key
        
        # Create session with retry logic
        self.session = self._create_session()
        
        # Rally detection thresholds (proven working values)
        self.MIN_START_GAIN = 1.5
        self.MIN_TOTAL_GAIN = 20.0
        self.MIN_GREEN_RATIO = 0.40
        self.MAX_RALLY_LENGTH = 100
        self.CONSOLIDATION_THRESHOLD = 2.0
        self.DRAWDOWN_END_THRESHOLD = -15.0
        self.VOLUME_EXHAUSTION = 0.3
        
        # Candle size mapping for SolanaTracker
        self.CANDLE_SIZE_MAPPING = {
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '1h': '1h',
            '4h': '4h',
            '1d': '1d'
        }
    
    def _create_session(self):
        """Create requests session with retry logic"""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        return session
    
    def get_st_headers(self):
        """Get headers for SolanaTracker API requests"""
        return {
            'accept': 'application/json',
            'x-api-key': self.api_key
        }
    
    def search_tokens(self, query, limit=20, min_liquidity=0, sort_by='liquidityUsd'):
        """
        Search for tokens by name, symbol, or address using SolanaTracker
        
        Args:
            query: Search term (token symbol, name, or address)
            limit: Number of results to return (max 500)
            min_liquidity: Minimum liquidity in USD
            sort_by: Field to sort by (liquidityUsd, marketCapUsd, volume_24h, etc.)
        
        Returns:
            List of matching tokens with metadata
        """
        print(f"\n[TOKEN SEARCH] Searching SolanaTracker for: {query}")
        
        if not self.api_key:
            print("❌ SolanaTracker API key is required!")
            return []
        
        url = f"{self.st_base_url}/search"
        
        params = {
            'query': query,
            'limit': min(limit, 500),
            'sortBy': sort_by,
            'sortOrder': 'desc',
            'minLiquidity': min_liquidity
        }
        
        try:
            response = self.session.get(
                url,
                params=params,
                headers=self.get_st_headers(),
                timeout=15
            )
            
            if response.status_code != 200:
                print(f"❌ Error: HTTP {response.status_code}")
                return []
            
            data = response.json()
            
            if data.get('status') != 'success':
                print(f"❌ API returned non-success status")
                return []
            
            results = data.get('data', [])
            
            if not results:
                print(f"❌ No tokens found for query: {query}")
                return []
            
            # Format results to match existing structure
            tokens = []
            for item in results:
                tokens.append({
                    'ticker': item.get('symbol', 'UNKNOWN'),
                    'name': item.get('name', 'Unknown Token'),
                    'address': item.get('mint'),
                    'chain': 'solana',  # Hardcoded since SolanaTracker is Solana-only
                    'liquidity_usd': item.get('liquidityUsd', 0),
                    'price_usd': item.get('priceUsd', 0),
                    'market_cap_usd': item.get('marketCapUsd', 0),
                    'volume_24h': item.get('volume_24h', 0),
                    'holders': item.get('holders', 0),
                    'image': item.get('image', ''),
                    'pool_address': item.get('poolAddress'),
                    'created_at': item.get('createdAt'),
                    'has_socials': item.get('hasSocials', False),
                    'market': item.get('market', ''),
                    'lp_burn': item.get('lpBurn', 0)
                })
            
            print(f"✓ Found {len(tokens)} tokens")
            
            # Display top 5 results
            if len(tokens) > 0:
                print(f"\nTop {min(5, len(tokens))} results:")
                for idx, token in enumerate(tokens[:5], 1):
                    print(f"  {idx}. {token['ticker']} ({token['name']})")
                    print(f"     Address: {token['address']}")
                    print(f"     Liquidity: ${token['liquidity_usd']:,.2f}")
                    print(f"     Market Cap: ${token['market_cap_usd']:,.2f}")
                    print()
            
            return tokens
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error searching tokens: {e}")
            return []
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return []
    
    def get_token_data(self, token_address):
        """
        Fetch comprehensive token metadata from SolanaTracker
        
        Args:
            token_address: Solana token mint address
        
        Returns:
            Dictionary with token metadata or None if error
        """
        print(f"\n[1/3] Fetching token metadata from SolanaTracker...")
        print(f"Token: {token_address}")
        
        if not self.api_key:
            print("❌ SolanaTracker API key is required!")
            return None
        
        url = f"{self.st_base_url}/tokens/{token_address}"
        
        try:
            response = self.session.get(
                url,
                headers=self.get_st_headers(),
                timeout=15
            )
            
            if response.status_code == 404:
                print(f"❌ Token not found: {token_address}")
                return None
            elif response.status_code != 200:
                print(f"❌ Error: HTTP {response.status_code}")
                return None
            
            data = response.json()
            
            token_info = data.get('token', {})
            pools = data.get('pools', [])
            
            if not token_info:
                print("❌ No token information returned")
                return None
            
            # Get the primary pool (highest liquidity)
            if pools:
                primary_pool = max(pools, key=lambda p: p.get('liquidity', {}).get('usd', 0))
            else:
                print("❌ No pools found for this token")
                return None
            
            # Extract metadata
            symbol = token_info.get('symbol', 'UNKNOWN')
            name = token_info.get('name', 'Unknown Token')
            liquidity = primary_pool.get('liquidity', {}).get('usd', 0)
            price = primary_pool.get('price', {}).get('usd', 0)
            market_cap = primary_pool.get('marketCap', {}).get('usd', 0)
            
            print(f"✓ Found: {symbol} ({name})")
            print(f"✓ Liquidity: ${liquidity:,.2f}")
            print(f"✓ Market Cap: ${market_cap:,.2f}")
            print(f"✓ Price: ${price:.10f}")
            print(f"✓ Market: {primary_pool.get('market', 'unknown')}")
            
            return {
                'symbol': symbol,
                'name': name,
                'address': token_address,
                'chain': 'solana',
                'decimals': token_info.get('decimals', 6),
                'image': token_info.get('image', ''),
                'description': token_info.get('description', ''),
                'liquidity_usd': liquidity,
                'price_usd': price,
                'market_cap_usd': market_cap,
                'pool_address': primary_pool.get('poolId'),
                'market': primary_pool.get('market'),
                'holders': data.get('holders', 0),
                'buys': data.get('buys', 0),
                'sells': data.get('sells', 0),
                'total_txns': data.get('txns', 0),
                'lp_burn': primary_pool.get('lpBurn', 0),
                'freeze_authority': primary_pool.get('security', {}).get('freezeAuthority'),
                'mint_authority': primary_pool.get('security', {}).get('mintAuthority'),
                'created_at': primary_pool.get('createdAt'),
                'pools': pools  # Include all pools for reference
            }
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching token data: {e}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return None
    
    def get_ohlcv_data(self, token_address, days_back=30, candle_size='5m'):
        """
        Fetch OHLCV data using SolanaTracker API
        
        Args:
            token_address: Solana token contract address
            days_back: Number of days to look back (1-90)
            candle_size: Candle timeframe ('1m', '5m', '15m', '1h', '4h', '1d')
        
        Returns:
            List of OHLCV candles or None if error
        """
        print(f"\n[2/3] Fetching candlestick data from SolanaTracker...")
        print(f"Token: {token_address[:8]}...{token_address[-6:]}")
        print(f"Days back: {days_back}")
        print(f"Candle size: {candle_size}")
        
        if not self.api_key:
            print("❌ SolanaTracker API key is required!")
            return None
        
        # Map candle size to SolanaTracker format
        st_type = self.CANDLE_SIZE_MAPPING.get(candle_size, '5m')
        
        # Calculate time range
        time_to = int(time.time())
        time_from = time_to - (days_back * 86400)
        
        url = f"{self.st_base_url}/chart/{token_address}"
        
        params = {
            'type': st_type,
            'time_from': time_from,
            'time_to': time_to,
            'currency': 'usd',
            'dynamicPools': 'true',
            'removeOutliers': 'true'
        }
        
        try:
            response = self.session.get(
                url,
                params=params,
                headers=self.get_st_headers(),
                timeout=30
            )
            
            if response.status_code == 400:
                print(f"❌ 400 Bad Request - Check if token address is correct")
                return None
            elif response.status_code == 401:
                print(f"❌ 401 Unauthorized - Check API key")
                return None
            elif response.status_code == 429:
                print(f"❌ 429 Rate Limited - Wait and retry")
                return None
            elif response.status_code == 404:
                print(f"❌ 404 Not Found - No chart data available")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            oclhv = data.get('oclhv', [])
            
            if not oclhv:
                print("❌ No candlestick data returned")
                return None
            
            # Normalize SolanaTracker format to match existing structure
            normalized = []
            for c in oclhv:
                timestamp = c['time'] // 1000  # Convert ms to seconds
                close_price = c['close']
                volume = c['volume']
                
                normalized.append({
                    'unix_time': timestamp,
                    'o': c['open'],
                    'h': c['high'],
                    'l': c['low'],
                    'c': close_price,
                    'v': volume,
                    'v_usd': volume * close_price
                })
            
            print(f"✓ Retrieved {len(normalized)} {candle_size} candles")
            
            if len(normalized) > 0:
                first_time = datetime.fromtimestamp(normalized[0]['unix_time'])
                last_time = datetime.fromtimestamp(normalized[-1]['unix_time'])
                print(f"✓ Time range: {first_time} to {last_time}")
            
            return normalized
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching OHLCV data: {e}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return None
    
    def get_volume_baseline(self, ohlcv_data, current_idx, lookback=15):
        """Get volume baseline - lenient for early candles"""
        if current_idx < 3:
            return {'median': 100, 'use_fixed': True}
        
        start = max(0, current_idx - lookback)
        lookback_candles = ohlcv_data[start:current_idx]
        
        if not lookback_candles or len(lookback_candles) < 3:
            return {'median': 500, 'use_fixed': True}
        
        volumes = [c.get('v_usd', 0) for c in lookback_candles]
        
        # Remove extreme outliers
        if len(volumes) > 5:
            sorted_vol = sorted(volumes)
            q25_idx = int(len(sorted_vol) * 0.25)
            q75_idx = int(len(sorted_vol) * 0.75)
            q25 = sorted_vol[q25_idx]
            q75 = sorted_vol[q75_idx]
            iqr = q75 - q25
            filtered = [v for v in volumes if q25 - 2*iqr <= v <= q75 + 2*iqr]
            volumes = filtered if filtered else volumes
        
        return {
            'median': statistics.median(volumes) if volumes else 100,
            'mean': statistics.mean(volumes) if volumes else 100,
            'use_fixed': False
        }
    
    def is_valid_rally_start(self, ohlcv_data, idx):
        """Check if candle is a valid rally start"""
        if idx >= len(ohlcv_data):
            return False
        
        current = ohlcv_data[idx]
        
        # Must be green
        if current['c'] <= current['o']:
            return False
        
        # Calculate gain
        current_gain = ((current['c'] - current['o']) / current['o']) * 100
        
        if current_gain < self.MIN_START_GAIN:
            return False
        
        # Volume check - lenient
        baseline = self.get_volume_baseline(ohlcv_data, idx)
        current_volume = current.get('v_usd', 0)
        
        if baseline['use_fixed']:
            if current_volume < 100:
                return False
        else:
            if baseline['median'] < 5000:
                vol_threshold = baseline['median'] * 0.3
            else:
                vol_threshold = baseline['median'] * 0.5
            
            if current_volume < vol_threshold:
                return False
        
        return True
    
    def detect_rally_end(self, ohlcv_data, start_idx, current_idx):
        """Detect when rally momentum fades"""
        if current_idx < start_idx + 2:
            return False
        
        rally_length = current_idx - start_idx + 1
        if rally_length < 3:
            return False
        
        recent_start = max(start_idx, current_idx - 4)
        recent_candles = ohlcv_data[recent_start:current_idx + 1]
        
        if len(recent_candles) < 3:
            return False
        
        # 1. Consolidation check
        last_3 = recent_candles[-3:]
        small_moves = 0
        for c in last_3:
            move = abs((c['c'] - c['o']) / c['o']) * 100
            if move < self.CONSOLIDATION_THRESHOLD:
                small_moves += 1
        
        if small_moves >= 3:
            return True
        
        # 2. Drawdown check
        rally_candles = ohlcv_data[start_idx:current_idx + 1]
        closes = [c['c'] for c in rally_candles]
        peak_price = max(closes)
        current_price = ohlcv_data[current_idx]['c']
        
        if peak_price > 0:
            drawdown = ((current_price - peak_price) / peak_price) * 100
            if drawdown < self.DRAWDOWN_END_THRESHOLD:
                return True
        
        # 3. Volume exhaustion
        volumes = [c.get('v_usd', 0) for c in rally_candles]
        avg_rally_volume = sum(volumes) / len(volumes) if volumes else 0
        current_volume = ohlcv_data[current_idx].get('v_usd', 0)
        
        if avg_rally_volume > 0 and current_volume < avg_rally_volume * self.VOLUME_EXHAUSTION:
            if rally_length >= 5:
                return True
        
        # 4. Red candle cluster
        if len(recent_candles) >= 5:
            last_5 = recent_candles[-5:]
            red_count = sum(1 for c in last_5 if c['c'] <= c['o'])
            if red_count >= 3:
                return True
        
        return False
    
    def build_rally_window(self, ohlcv_data, start_idx):
        """Build rally window incrementally"""
        if not self.is_valid_rally_start(ohlcv_data, start_idx):
            return None
        
        current_idx = start_idx
        max_idx = len(ohlcv_data) - 1
        
        # Build window candle by candle
        while current_idx < max_idx:
            if self.detect_rally_end(ohlcv_data, start_idx, current_idx):
                break
            
            window_length = current_idx - start_idx + 1
            if window_length >= self.MAX_RALLY_LENGTH:
                break
            
            current_idx += 1
        
        window = ohlcv_data[start_idx:current_idx + 1]
        
        if len(window) < 2:
            return None
        
        # Calculate stats
        green_count = sum(1 for c in window if c['c'] > c['o'])
        green_ratio = green_count / len(window) if len(window) > 0 else 0
        
        # Better price reference handling
        if start_idx > 0:
            start_price = ohlcv_data[start_idx - 1]['c']
        else:
            start_price = window[0]['o']
        
        end_price = window[-1]['c']
        closes = [c['c'] for c in window]
        peak_price = max(closes)
        
        # Validation for unrealistic prices
        if start_price <= 0 or end_price <= 0:
            return None
        
        total_gain = ((end_price - start_price) / start_price) * 100
        peak_gain = ((peak_price - start_price) / start_price) * 100
        
        # Sanity check for unrealistic gains (likely data error)
        if total_gain > 10000:
            return None
        
        # Minimum thresholds
        if total_gain < self.MIN_TOTAL_GAIN:
            return None
        
        if green_ratio < self.MIN_GREEN_RATIO:
            return None
        
        combined_volume = sum(c.get('v_usd', 0) for c in window)
        rally_type = self.classify_rally_type(window, total_gain, peak_gain, green_ratio)
        max_dd = self.calculate_max_drawdown(closes)
        
        return {
            'start_idx': start_idx,
            'end_idx': current_idx,
            'length': len(window),
            'total_gain': total_gain,
            'peak_gain': peak_gain,
            'green_ratio': green_ratio,
            'green_count': green_count,
            'red_count': len(window) - green_count,
            'type': rally_type,
            'window': window,
            'combined_volume': combined_volume,
            'start_price': start_price,
            'end_price': end_price,
            'peak_price': peak_price,
            'max_drawdown': max_dd
        }
    
    def calculate_max_drawdown(self, closes):
        """Calculate maximum drawdown during rally"""
        if not closes:
            return 0
        max_dd = 0
        peak = closes[0]
        for price in closes:
            if price > peak:
                peak = price
            dd = (price - peak) / peak * 100 if peak > 0 else 0
            if dd < max_dd:
                max_dd = dd
        return max_dd
    
    def classify_rally_type(self, window, total_gain, peak_gain, green_ratio):
        """Classify rally type based on characteristics"""
        length = len(window)
        
        if length <= 6 and total_gain >= 40 and green_ratio >= 0.75:
            return 'explosive'
        
        if 4 <= length <= 20 and total_gain >= 30 and green_ratio >= 0.55:
            return 'choppy'
        
        if 10 <= length <= 50 and total_gain >= 80 and green_ratio >= 0.45:
            return 'grind'
        
        if length > 20 and green_ratio >= 0.40 and peak_gain >= 100:
            return 'ultra_choppy'
        
        return 'standard'
    
    def deduplicate_rallies_smart(self, rallies):
        """Remove overlapping rallies, keeping the best one"""
        if not rallies:
            return []
        
        sorted_rallies = sorted(rallies, key=lambda x: x['start_idx'])
        deduplicated = []
        
        for rally in sorted_rallies:
            overlaps = False
            
            for i, existing in enumerate(deduplicated):
                overlap_start = max(rally['start_idx'], existing['start_idx'])
                overlap_end = min(rally['end_idx'], existing['end_idx'])
                overlap_length = max(0, overlap_end - overlap_start + 1)
                
                rally_length = rally['end_idx'] - rally['start_idx'] + 1
                existing_length = existing['end_idx'] - existing['start_idx'] + 1
                
                overlap_ratio = overlap_length / min(rally_length, existing_length)
                
                if overlap_ratio > 0.3:
                    overlaps = True
                    
                    rally_score = rally['peak_gain'] * rally['green_ratio'] * (rally['length'] ** 0.5)
                    existing_score = existing['peak_gain'] * existing['green_ratio'] * (existing['length'] ** 0.5)
                    
                    if rally_score > existing_score * 1.3:
                        deduplicated[i] = rally
                    
                    break
            
            if not overlaps:
                deduplicated.append(rally)
        
        return sorted(deduplicated, key=lambda x: x['start_idx'])
    
    def detect_all_rallies(self, ohlcv_data):
        """Detect all rallies in OHLCV data"""
        print(f"\n[3/3] Analyzing with Precision Rally Detection...")
        print(f" • Min start gain: {self.MIN_START_GAIN}%")
        print(f" • Min total gain: {self.MIN_TOTAL_GAIN}%")
        print(f" • Min green ratio: {self.MIN_GREEN_RATIO*100}%\n")
        
        if not ohlcv_data or len(ohlcv_data) < 5:
            print(f"❌ Insufficient data (need at least 5 candles)")
            return []
        
        rallies = []
        i = 1
        
        while i < len(ohlcv_data) - 1:
            rally = self.build_rally_window(ohlcv_data, i)
            
            if rally:
                rallies.append(rally)
                rally_time = datetime.fromtimestamp(rally['window'][0]['unix_time'])
                print(f"   ✓ Rally #{len(rallies)} at {rally_time.strftime('%m/%d %H:%M')}: "
                      f"{rally['type'].upper()} ({rally['length']} candles, "
                      f"+{rally['total_gain']:.1f}%, {rally['green_ratio']*100:.0f}% green)")
                
                i = rally['end_idx'] + 3
            else:
                i += 1
        
        print(f"\n   → Found {len(rallies)} raw rallies")
        
        final_rallies = self.deduplicate_rallies_smart(rallies)
        print(f"   → After deduplication: {len(final_rallies)} unique rallies\n")
        
        return final_rallies
    
    def display_rallies(self, rallies):
        """Display detected rallies in formatted output"""
        print(f"\n{'='*100}")
        
        if not rallies:
            print("NO RALLIES DETECTED")
            print("="*100)
            return
        
        print(f"DETECTED {len(rallies)} RALLY/RALLIES")
        print(f"{'='*100}\n")
        
        for idx, rally in enumerate(rallies, 1):
            pump_time = datetime.fromtimestamp(rally['window'][0]['unix_time'])
            end_time = datetime.fromtimestamp(rally['window'][-1]['unix_time'])
            t_minus_35 = pump_time - timedelta(minutes=35)
            t_plus_10 = end_time + timedelta(minutes=10)
            
            print(f"{'─'*100}")
            print(f"RALLY #{idx} - TYPE: {rally['type'].upper()}")
            print(f"{'─'*100}")
            print(f"⏰ START TIME: {pump_time.strftime('%A, %B %d, %Y at %H:%M:%S')}")
            print(f"🏁 END TIME: {end_time.strftime('%A, %B %d, %Y at %H:%M:%S')}")
            print(f"⏪ T-35 MINS: {t_minus_35.strftime('%A, %B %d, %Y at %H:%M:%S')}")
            print(f"⏩ T+10 MINS: {t_plus_10.strftime('%A, %B %d, %Y at %H:%M:%S')}")
            print(f"")
            print(f"📊 METRICS:")
            print(f" Duration: {rally['length']} candles ({rally['length']*5} minutes)")
            print(f" Candle Composition: {rally['green_count']} green, {rally['red_count']} red")
            print(f" Green Ratio: {rally['green_ratio']*100:.1f}%")
            print(f" Total Gain: +{rally['total_gain']:.2f}%")
            print(f" Peak Gain: +{rally['peak_gain']:.2f}%")
            print(f" Max Drawdown: {rally['max_drawdown']:.2f}%")
            print(f" Combined Volume: ${rally['combined_volume']:,.2f}")
            print(f" Price Range: ${rally['start_price']:.8f} → ${rally['end_price']:.8f} (peak: ${rally['peak_price']:.8f})")
            print()
        
        print(f"{'='*100}\n")
    
    def analyze_token(self, token_address, days_back=30, candle_size='5m'):
        """
        Main analysis function with simple parameters
        
        Args:
            token_address: Solana token contract address
            days_back: Number of days to analyze (1-90)
            candle_size: Candle timeframe ('1m', '5m', '15m', '1h', '4h', '1d')
        
        Returns:
            List of detected rallies
        """
        # Get token metadata first
        token_data = self.get_token_data(token_address)
        
        if not token_data:
            print("❌ Could not fetch token metadata")
            return None
        
        # Get OHLCV data
        ohlcv_data = self.get_ohlcv_data(token_address, days_back, candle_size)
        
        if not ohlcv_data:
            print("❌ Could not fetch OHLCV data")
            return None
        
        # Detect rallies
        rallies = self.detect_all_rallies(ohlcv_data)
        self.display_rallies(rallies)
        
        return rallies