import requests
from datetime import datetime, timedelta
import time
import statistics

class PrecisionRallyDetector:
    def __init__(self, birdeye_api_key=None):
        self.dex_screener_url = "https://api.dexscreener.com/latest/dex"
        self.birdeye_url = "https://public-api.birdeye.so/defi/v3/ohlcv/pair"
        self.birdeye_api_key = birdeye_api_key
        
        # FIXED: More lenient thresholds
        self.MIN_START_GAIN = 1.5  # Down from 3.0 to catch Rally 3
        self.MIN_TOTAL_GAIN = 20.0
        self.MIN_GREEN_RATIO = 0.40
        self.MAX_RALLY_LENGTH = 100
        self.CONSOLIDATION_THRESHOLD = 2.0
        self.DRAWDOWN_END_THRESHOLD = -15.0
        self.VOLUME_EXHAUSTION = 0.3
        
    def get_token_data(self, token_address):
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
    
    def get_chain_name(self, chain_id):
        chain_mapping = {
            'solana': 'solana', 'ethereum': 'ethereum', 'bsc': 'bsc',
            'base': 'base', 'arbitrum': 'arbitrum', 'avalanche': 'avalanche',
            'optimism': 'optimism', 'polygon': 'polygon', 'zksync': 'zksync',
            'sui': 'sui', 'aptos': 'aptos',
        }
        return chain_mapping.get(chain_id.lower(), 'solana')
    
    def get_token_launch_time(self, token_address):
        """
        Get token creation/launch timestamp from Birdeye
        
        Args:
            token_address: Token contract address
        
        Returns:
            Unix timestamp of token creation, or None if not found
        """
        print(f"\n[LAUNCH] Fetching token creation time...")
        
        url = f"https://public-api.birdeye.so/defi/token_creation_info"
        
        params = {
            'address': token_address
        }
        
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
            
            print("⚠️ Could not find token creation time, using first trade time as fallback")
            return None
            
        except Exception as e:
            print(f"❌ Error fetching launch time: {e}")
            return None
    
    def calculate_launch_window(self, launch_timestamp, window_type):
        """
        Calculate time range based on launch time
        
        Args:
            launch_timestamp: Unix timestamp of token launch
            window_type: One of 'first_5m', 'first_24h', 'first_7d', 'first_30d', 'all'
        
        Returns:
            Tuple of (time_from, time_to) in unix timestamps
        """
        if not launch_timestamp:
            # Fallback to relative windows if no launch time
            time_to = int(time.time())
            
            mapping = {
                'first_5m': 5 * 60,
                'first_24h': 24 * 60 * 60,
                'first_7d': 7 * 24 * 60 * 60,
                'first_30d': 30 * 24 * 60 * 60,
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
    
    def get_ohlcv_data(self, pair_address, chain, days_back=30):
        print(f"\n[2/3] Fetching M5 candlestick data from Birdeye (last {days_back} days)...")
        
        if not self.birdeye_api_key:
            print("❌ Birdeye API key is required!")
            return None
        
        time_to = int(time.time())
        time_from = time_to - (days_back * 24 * 60 * 60)
        
        params = {
            'address': pair_address,
            'type': '5m',
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
            
            print(f"✓ Retrieved {len(items)} M5 candles")
            print(f"✓ Time range: {datetime.fromtimestamp(items[0]['unix_time'])} to {datetime.fromtimestamp(items[-1]['unix_time'])}")
            
            return items
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching OHLCV data: {e}")
            return None
    
    def get_ohlcv_data_with_launch(self, pair_address, chain, launch_timestamp=None, window_type='first_7d'):
        """
        MODIFIED version of get_ohlcv_data that supports launch-anchored windows
        
        Args:
            pair_address: DEX pair address
            chain: Chain name
            launch_timestamp: Unix timestamp of token launch (optional)
            window_type: 'first_5m', 'first_24h', 'first_7d', 'first_30d', 'all', or 'last_7d', 'last_30d'
        
        Returns:
            OHLCV data array
        """
        print(f"\n[2/3] Fetching M5 candlestick data from Birdeye...")
        print(f"Window type: {window_type}")
        
        if not self.birdeye_api_key:
            print("❌ Birdeye API key is required!")
            return None
        
        # Calculate time range
        if window_type.startswith('first_'):
            # Launch-anchored window
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
            'type': '5m',
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
            
            print(f"✓ Retrieved {len(items)} M5 candles")
            print(f"✓ Time range: {datetime.fromtimestamp(items[0]['unix_time'])} to {datetime.fromtimestamp(items[-1]['unix_time'])}")
            
            return items
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching OHLCV data: {e}")
            return None
    
    def get_volume_baseline(self, ohlcv_data, current_idx, lookback=15):
        """Get volume baseline - VERY LENIENT for early candles"""
        if current_idx < 3:
            # For first few candles, use minimal threshold
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
        """FIXED: Simplified rally start detection"""
        if idx >= len(ohlcv_data):
            return False
        
        current = ohlcv_data[idx]
        
        # Must be green
        if current['c'] <= current['o']:
            return False
        
        # Calculate gain
        current_gain = ((current['c'] - current['o']) / current['o']) * 100
        
        # FIXED: Lower threshold to catch Rally 3
        if current_gain < self.MIN_START_GAIN:
            return False
        
        # Volume check - VERY LENIENT
        baseline = self.get_volume_baseline(ohlcv_data, idx)
        
        if baseline['use_fixed']:
            # Early candles - just need non-zero volume
            if current['v_usd'] < 100:
                return False
        else:
            # Later candles - very lenient multiplier
            if baseline['median'] < 5000:
                vol_threshold = baseline['median'] * 0.3  # Only 30% of median
            else:
                vol_threshold = baseline['median'] * 0.5  # Only 50% of median
            
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
        print(f"\n[3/3] Analyzing with Precision Rally Detection...")
        print(f" • Min start gain: {self.MIN_START_GAIN}%")
        print(f" • Min total gain: {self.MIN_TOTAL_GAIN}%")
        print(f" • Min green ratio: {self.MIN_GREEN_RATIO*100}%\n")
        
        if not ohlcv_data or len(ohlcv_data) < 5:
            print(f"❌ Insufficient data (need at least 5 candles)")
            return []
        
        rallies = []
        i = 1  # FIXED: Start from index 1 (second candle) to catch early rallies
        
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
    
    def analyze_token(self, token_address, days_back=30):
        pair_data = self.get_token_data(token_address)
        if not pair_data:
            return
        
        pair_address = pair_data['pairAddress']
        chain_id = pair_data['chainId']
        chain_name = self.get_chain_name(chain_id)
        
        ohlcv_data = self.get_ohlcv_data(pair_address, chain_name, days_back)
        if not ohlcv_data:
            return
        
        rallies = self.detect_all_rallies(ohlcv_data)
        self.display_rallies(rallies)
        
        return rallies
    
    def analyze_token_from_launch(self, token_address, window_type='first_7d'):
        """
        Analyze token rallies from launch time
        
        Args:
            token_address: Token contract address
            window_type: One of 'first_5m', 'first_24h', 'first_7d', 'first_30d', 'all'
        """
        pair_data = self.get_token_data(token_address)
        if not pair_data:
            return
        
        pair_address = pair_data['pairAddress']
        chain_id = pair_data['chainId']
        chain_name = self.get_chain_name(chain_id)
        
        # Get launch time
        launch_timestamp = self.get_token_launch_time(token_address)
        
        # Get OHLCV data with launch-anchored window
        ohlcv_data = self.get_ohlcv_data_with_launch(pair_address, chain_name, launch_timestamp, window_type)
        if not ohlcv_data:
            return
        
        rallies = self.detect_all_rallies(ohlcv_data)
        self.display_rallies(rallies)
        
        return rallies


def main():
    print("""
╔══════════════════════════════════════════════════════════════════════════════════════════════╗
║                        PRECISION RALLY DETECTOR - UPDATED VERSION                            ║
╚══════════════════════════════════════════════════════════════════════════════════════════════╝

🎯 Key Features:
   ✓ Starts from index 1 (catches early rallies like Rally 1 & 2)
   ✓ Lower start threshold (1.5% to catch Rally 3)  
   ✓ Very lenient volume checks for early candles
   ✓ Simplified breakout detection (no acceleration requirement)
   ✓ Natural rally end detection
   ✓ NEW: Launch-time-based analysis windows
""")
    
    BIRDEYE_API_KEY = "35d3d50f74d94c439f6913a7e82cf994"
    
    if not BIRDEYE_API_KEY:
        print("Enter your Birdeye API key:")
        api_key = input("API Key: ").strip()
        if not api_key:
            print("\n⚠️ No API key provided")
            return
    else:
        api_key = BIRDEYE_API_KEY
        print(f"✓ Using API key: {api_key[:8]}...{api_key[-4:]}")
    
    detector = PrecisionRallyDetector(birdeye_api_key=api_key)
    
    print("\nEnter token contract address:")
    token_address = input("Token: ").strip()
    
    if not token_address:
        print("❌ No token address provided")
        return
    
    # Ask user for analysis mode
    print("\nSelect analysis mode:")
    print("1. Standard (last N days from now)")
    print("2. Launch-based (from token creation)")
    mode = input("Mode (1 or 2): ").strip()
    
    if mode == '2':
        print("\nSelect window type:")
        print("1. First 5 minutes")
        print("2. First 24 hours")
        print("3. First 7 days")
        print("4. First 30 days")
        print("5. All time from launch")
        window_choice = input("Window (1-5): ").strip()
        
        window_mapping = {
            '1': 'first_5m',
            '2': 'first_24h',
            '3': 'first_7d',
            '4': 'first_30d',
            '5': 'all'
        }
        
        window_type = window_mapping.get(window_choice, 'first_7d')
        rallies = detector.analyze_token_from_launch(token_address, window_type)
    else:
        days_input = input("\nDays of data (default 30, max 90): ").strip()
        try:
            days_back = int(days_input) if days_input else 30
            days_back = min(days_back, 90)
        except ValueError:
            days_back = 30
        
        rallies = detector.analyze_token(token_address, days_back)
    
    if rallies:
        print("\n✅ Analysis complete!")
        print("Review T-35 to START TIME windows for early signals/mentions.")


if __name__ == "__main__":
    main()