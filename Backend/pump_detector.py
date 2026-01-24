import requests
from datetime import datetime, timedelta
import time
import statistics

class PrecisionRallyDetector:
    def __init__(self, birdeye_api_key=None):
        self.dex_screener_url = "https://api.dexscreener.com/latest/dex"
        self.birdeye_url = "https://public-api.birdeye.so/defi/v3/ohlcv/pair"
        self.birdeye_api_key = birdeye_api_key
        
        # Rally detection thresholds
        self.MIN_START_GAIN = 1.5
        self.MIN_TOTAL_GAIN = 20.0
        self.MIN_GREEN_RATIO = 0.40
        self.MAX_RALLY_LENGTH = 100
        self.CONSOLIDATION_THRESHOLD = 2.0
        self.DRAWDOWN_END_THRESHOLD = -15.0
        self.VOLUME_EXHAUSTION = 0.3
        
        # Candle size mapping
        self.CANDLE_SIZE_MAPPING = {
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '1h': '1H',
            '4h': '4H',
            '1d': '1D'
        }
    
    def get_token_data(self, token_address):
        """Fetch token data from DexScreener"""
        print(f"\n[1/3] Fetching token data from DEX Screener...")
        print(f"Token: {token_address}")
        
        url = f"{self.dex_screener_url}/search/?q={token_address}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            if not data.get('pairs'):
                print("❌ No pairs found for this token")
                return None
            
            pairs = data['pairs']
            main_pair = max(pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
            
            print(f"✓ Found pair: {main_pair['baseToken']['symbol']}/{main_pair['quoteToken']['symbol']}")
            print(f"✓ Chain: {main_pair['chainId']}")
            print(f"✓ DEX: {main_pair['dexId']}")
            print(f"✓ Liquidity: ${float(main_pair.get('liquidity', {}).get('usd', 0)):,.2f}")
            
            return main_pair
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching data: {e}")
            return None
    
    def search_tokens(self, query):
        """
        Search for tokens by name or contract address
        Returns list of matching tokens
        """
        print(f"\n[TOKEN SEARCH] Searching for: {query}")
        
        url = f"{self.dex_screener_url}/search/?q={query}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            if not data.get('pairs'):
                return []
            
            tokens = []
            
            for pair in data['pairs'][:20]:  # Limit to top 20
                tokens.append({
                    'ticker': pair['baseToken']['symbol'],
                    'name': pair['baseToken']['name'],
                    'address': pair['baseToken']['address'],
                    'chain': pair['chainId'],
                    'dex': pair['dexId'],
                    'liquidity_usd': float(pair.get('liquidity', {}).get('usd', 0)),
                    'price_usd': float(pair.get('priceUsd', 0)),
                    'pair_address': pair['pairAddress'],
                    'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
                    'price_change_24h': float(pair.get('priceChange', {}).get('h24', 0))
                })
            
            # Sort by liquidity
            tokens.sort(key=lambda x: x['liquidity_usd'], reverse=True)
            
            print(f"[TOKEN SEARCH] Found {len(tokens)} tokens")
            
            return tokens
            
        except Exception as e:
            print(f"[TOKEN SEARCH ERROR] {str(e)}")
            return []
    
    def get_chain_name(self, chain_id):
        """Map chain ID to Birdeye chain name"""
        chain_mapping = {
            'solana': 'solana', 'ethereum': 'ethereum', 'bsc': 'bsc',
            'base': 'base', 'arbitrum': 'arbitrum', 'avalanche': 'avalanche',
            'optimism': 'optimism', 'polygon': 'polygon', 'zksync': 'zksync',
            'sui': 'sui', 'aptos': 'aptos',
        }
        return chain_mapping.get(chain_id.lower(), 'solana')
    
    def get_token_launch_time(self, token_address):
        """Get token creation timestamp from Birdeye"""
        print(f"\n[LAUNCH] Fetching token creation time...")
        
        url = f"https://public-api.birdeye.so/defi/token_creation_info"
        
        params = {'address': token_address}
        headers = {
            'accept': 'application/json',
            'X-API-KEY': self.birdeye_api_key
        }
        
        try:
            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if data.get('success') and data.get('data'):
                launch_time = data['data'].get('blockUnixTime')
                
                if launch_time:
                    launch_date = datetime.fromtimestamp(launch_time)
                    print(f"✓ Token launched: {launch_date.strftime('%Y-%m-%d %H:%M:%S')}")
                    return launch_time
            
            print("⚠️ Could not find token creation time")
            return None
            
        except Exception as e:
            print(f"❌ Error fetching launch time: {e}")
            return None
    
    def calculate_launch_window(self, launch_timestamp, window_type):
        """Calculate time range based on launch time"""
        if not launch_timestamp:
            # Fallback to relative windows
            time_to = int(time.time())
            
            mapping = {
                'first_5m': 5 * 60,
                'first_24h': 24 * 60 * 60,
                'first_7d': 7 * 24 * 60 * 60,
                'first_30d': 30 * 24 * 60 * 60,
                'last_1h': 1 * 60 * 60,
                'last_24h': 24 * 60 * 60,
                'last_7d': 7 * 24 * 60 * 60,
                'last_30d': 30 * 24 * 60 * 60,
                'all': 90 * 24 * 60 * 60
            }
            
            seconds_back = mapping.get(window_type, 7 * 24 * 60 * 60)
            time_from = time_to - seconds_back
            
            return (time_from, time_to)
        
        # Calculate from launch time
        launch_time = launch_timestamp
        
        if window_type == 'first_5m':
            return (launch_time, launch_time + 5 * 60)
        elif window_type == 'first_24h':
            return (launch_time, launch_time + 24 * 60 * 60)
        elif window_type == 'first_7d':
            return (launch_time, launch_time + 7 * 24 * 60 * 60)
        elif window_type == 'first_30d':
            return (launch_time, launch_time + 30 * 24 * 60 * 60)
        elif window_type == 'all':
            return (launch_time, int(time.time()))
        else:
            # Default: first 7 days
            return (launch_time, launch_time + 7 * 24 * 60 * 60)
    
    def get_ohlcv_data_with_launch(self, pair_address, chain, launch_timestamp=None, 
                                    window_type='first_7d', candle_size='5m'):
        """
        Fetch OHLCV data with support for:
        - Launch-anchored windows (first_5m, first_24h, etc.)
        - Relative windows (last_7d, last_30d, etc.)
        - Different candle sizes (1m, 5m, 15m, 1h, 4h, 1d)
        """
        print(f"\n[2/3] Fetching candlestick data from Birdeye...")
        print(f"Window type: {window_type}")
        print(f"Candle size: {candle_size}")
        
        if not self.birdeye_api_key:
            print("❌ Birdeye API key is required!")
            return None
        
        # Map candle size
        birdeye_candle_size = self.CANDLE_SIZE_MAPPING.get(candle_size, '5m')
        
        # Calculate time range
        if window_type.startswith('first_'):
            time_from, time_to = self.calculate_launch_window(launch_timestamp, window_type)
            
            if launch_timestamp:
                launch_date = datetime.fromtimestamp(launch_timestamp)
                from_date = datetime.fromtimestamp(time_from)
                to_date = datetime.fromtimestamp(time_to)
                print(f"✓ Launch time: {launch_date.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"✓ Analysis window: {from_date.strftime('%Y-%m-%d %H:%M:%S')} to {to_date.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            # Relative window (last X days from now)
            time_to = int(time.time())
            
            mapping = {
                'last_1h': 1 * 60 * 60,
                'last_5h': 5 * 60 * 60,
                'last_24h': 24 * 60 * 60,
                'last_3d': 3 * 24 * 60 * 60,
                'last_7d': 7 * 24 * 60 * 60,
                'last_30d': 30 * 24 * 60 * 60
            }
            
            seconds_back = mapping.get(window_type, 7 * 24 * 60 * 60)
            time_from = time_to - seconds_back
        
        params = {
            'address': pair_address,
            'type': birdeye_candle_size,
            'time_from': time_from,
            'time_to': time_to,
        }
        
        headers = {
            'accept': 'application/json',
            'x-chain': chain,
            'X-API-KEY': self.birdeye_api_key
        }
        
        try:
            response = requests.get(self.birdeye_url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if not data.get('success'):
                print(f"❌ Birdeye API error: {data}")
                return None
            
            items = data.get('data', {}).get('items', [])
            
            if not items:
                print("❌ No candlestick data returned")
                return None
            
            print(f"✓ Retrieved {len(items)} {candle_size} candles")
            print(f"✓ Time range: {datetime.fromtimestamp(items[0]['unix_time'])} to {datetime.fromtimestamp(items[-1]['unix_time'])}")
            
            return items
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching OHLCV data: {e}")
            return None
    
    def get_volume_baseline(self, ohlcv_data, current_idx, lookback=15):
        """Get volume baseline - lenient for early candles"""
        if current_idx < 3:
            return {'median': 100, 'use_fixed': True}
        
        start = max(0, current_idx - lookback)
        lookback_candles = ohlcv_data[start:current_idx]
        
        if not lookback_candles or len(lookback_candles) < 3:
            return {'median': 500, 'use_fixed': True}
        
        volumes = [c['v_usd'] for c in lookback_candles]
        
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
            'median': statistics.median(volumes),
            'mean': statistics.mean(volumes),
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
        
        if baseline['use_fixed']:
            if current['v_usd'] < 100:
                return False
        else:
            if baseline['median'] < 5000:
                vol_threshold = baseline['median'] * 0.3
            else:
                vol_threshold = baseline['median'] * 0.5
            
            if current['v_usd'] < vol_threshold:
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
        avg_rally_volume = sum(c['v_usd'] for c in rally_candles) / len(rally_candles)
        current_volume = ohlcv_data[current_idx]['v_usd']
        
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
        
        start_price = ohlcv_data[start_idx - 1]['c'] if start_idx > 0 else window[0]['o']
        end_price = window[-1]['c']
        closes = [c['c'] for c in window]
        peak_price = max(closes)
        
        if start_price <= 0:
            return None
        
        total_gain = ((end_price - start_price) / start_price) * 100
        peak_gain = ((peak_price - start_price) / start_price) * 100
        
        # Minimum thresholds
        if total_gain < self.MIN_TOTAL_GAIN:
            return None
        
        if green_ratio < self.MIN_GREEN_RATIO:
            return None
        
        combined_volume = sum(c['v_usd'] for c in window)
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