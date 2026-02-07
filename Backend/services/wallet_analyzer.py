import requests
from datetime import datetime
from collections import defaultdict
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore
from datetime import datetime, timedelta

class WalletPumpAnalyzer:
    """
    PROFESSIONAL WALLET ANALYZER with COMPLETE 6-Step Analysis
    
    THE 6 STEPS (from Document 6):
    1. Fetch top traders from Solana Tracker + first buy timestamps
    2. Fetch first buyers from Solana Tracker + entry prices
    3. Fetch Birdeye historical trades (30 days back)
    4. Fetch recent Solana Tracker trades
    5. Fetch PnL for ALL wallets, filter for ≥3x ROI AND ≥$100 invested
    6. Rank by professional score (60% distance to ATH, 30% realized profit, 10% total position)
    
    Additional Features:
    - 30-day runner history tracking with per-runner distance to ATH
    - Cross-runner consistency grading
    - Batch analysis with variance tracking
    - Professional scoring (60/30/10 - NO time-based)
    - Replacement finder for degrading wallets
    
    All data from SolanaTracker + Birdeye APIs
    """

    def __init__(self, solanatracker_api_key, birdeye_api_key=None, debug_mode=True):
        self.solanatracker_key = solanatracker_api_key
        self.birdeye_key = birdeye_api_key or "a49c49de31d34574967c13bd35f3c523"
        self.st_base_url = "https://data.solanatracker.io"
        self.birdeye_base_url = "https://public-api.birdeye.so"
        self.debug_mode = debug_mode
        
        # Concurrency control
        self.max_workers = 8
        self.birdeye_semaphore = Semaphore(2)
        self.solana_tracker_semaphore = Semaphore(3)
        self.pnl_semaphore = Semaphore(2)
        self.executor = None
        
        # ✅ ADD: Caching for trending runners
        self._trending_cache = {}
        self._cache_expiry = {}

    def _log(self, message):
        if self.debug_mode:
            print(f"[WALLET ANALYZER] {message}")

    def _get_solanatracker_headers(self):
        """Get headers for SolanaTracker API requests"""
        return {
            'accept': 'application/json',
            'x-api-key': self.solanatracker_key
        }

    def _get_birdeye_headers(self):
        """Get headers for Birdeye API requests"""
        return {
            "x-chain": "solana",
            "accept": "application/json",
            "X-API-KEY": self.birdeye_key
        }

    def fetch_with_retry(self, url: str, headers: dict, params: dict = None, 
                        semaphore: Semaphore = None, max_retries: int = 3):
        """Fetch with retry logic and semaphore-based rate limiting"""
        for attempt in range(max_retries):
            try:
                if semaphore:
                    semaphore.acquire()
                    try:
                        response = requests.get(url, headers=headers, params=params, timeout=15)
                    finally:
                        semaphore.release()
                else:
                    response = requests.get(url, headers=headers, params=params, timeout=15)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    return None
                elif response.status_code == 429:
                    wait_time = int(response.headers.get('Retry-After', 5))
                    self._log(f"Rate limited. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    time.sleep(2 ** attempt)
                elif response.status_code == 500:
                    return None
                else:
                    return None
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return None

    # =========================================================================
    # BASIC DATA FETCHING METHODS
    # =========================================================================

    def get_wallet_pnl_solanatracker(self, wallet_address, token_address):
        """Get PnL data for a wallet-token pair"""
        try:
            url = f"{self.st_base_url}/pnl/{wallet_address}/{token_address}"
            return self.fetch_with_retry(
                url, 
                self._get_solanatracker_headers(), 
                semaphore=self.pnl_semaphore
            )
        except Exception as e:
            self._log(f"  ⚠️ Error fetching PnL: {str(e)}")
            return None

    def get_token_ath(self, token_address):
        """Get all-time high price data - ✅ USES RETRY"""
        try:
            url = f"{self.st_base_url}/tokens/{token_address}/ath"
            
            # ✅ USE RETRY instead of direct requests.get
            data = self.fetch_with_retry(
                url,
                self._get_solanatracker_headers(),
                semaphore=self.solana_tracker_semaphore
            )
            
            return data  # Returns None if failed
            
        except Exception as e:
            self._log(f"  ⚠️ Error fetching ATH: {str(e)}")
            return None

    def get_wallet_trades_30days(self, wallet_address, limit=100):
        """Get wallet's trades from last 30 days"""
        try:
            url = f"{self.st_base_url}/wallet/{wallet_address}/trades"
            params = {'limit': limit}
            
            response = requests.get(url, headers=self._get_solanatracker_headers(), timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                trades = data.get('trades', [])
                
                thirty_days_ago = time.time() - (30 * 24 * 60 * 60)
                recent_trades = [
                    trade for trade in trades 
                    if trade.get('time', 0) > thirty_days_ago * 1000
                ]
                
                return recent_trades
            
            return []
            
        except Exception as e:
            self._log(f"  ⚠️ Error getting 30-day trades: {str(e)}")
            return []

    def get_first_buy_for_wallet(self, wallet_address, token_address):
        """Get first buy timestamp and price for a wallet"""
        try:
            url = f"{self.st_base_url}/trades/{token_address}/by-wallet/{wallet_address}"
            data = self.fetch_with_retry(
                url, 
                self._get_solanatracker_headers(), 
                semaphore=self.solana_tracker_semaphore
            )
            
            if data and data.get('trades'):
                buys = [t for t in data['trades'] if t.get('type') == 'buy']
                if buys:
                    first_buy = min(buys, key=lambda x: x.get('time', float('inf')))
                    return {
                        'time': first_buy.get('time'),
                        'price': first_buy.get('priceUsd')
                    }
            
            return None
            
        except Exception as e:
            return None

    def calculate_ath_distance_for_wallet(self, token_address, cost_basis):
        """Calculate ATH distance for a wallet's entry price"""
        try:
            ath_data = self.get_token_ath(token_address)
            if not ath_data or ath_data.get('highest_price', 0) <= 0 or cost_basis <= 0:
                return 0
            
            ath = ath_data['highest_price']
            distance = ((ath - cost_basis) / ath) * 100 if ath > cost_basis else 0
            return round(distance, 2)
            
        except Exception as e:
            return 0

    # =========================================================================
    # TRENDING RUNNER DISCOVERY (FIXED)
    # =========================================================================

    def _get_price_range_in_period(self, token_address, days_back):
        """Get price multiplier for period - ✅ USES RETRY"""
        try:
            time_to = int(time.time())
            time_from = time_to - (days_back * 86400)
            
            # Auto-select candle size based on timeframe
            candle_type = '1h' if days_back <= 7 else '4h'
            
            url = f"{self.st_base_url}/chart/{token_address}"
            params = {
                'type': candle_type,
                'time_from': time_from,
                'time_to': time_to,
                'currency': 'usd'
            }
            
            # ✅ USE RETRY instead of direct requests.get
            data = self.fetch_with_retry(
                url,
                self._get_solanatracker_headers(),
                params=params,
                semaphore=self.solana_tracker_semaphore
            )
            
            if not data:
                return None
            
            candles = data.get('oclhv', [])
            
            if not candles:
                return None
            
            low_prices = [c.get('low', float('inf')) for c in candles if c.get('low')]
            high_prices = [c.get('high', 0) for c in candles if c.get('high')]
            
            if not low_prices or not high_prices:
                return None
            
            lowest_price = min(low_prices)
            highest_price = max(high_prices)
            
            return {
                'lowest_price': lowest_price,
                'highest_price': highest_price,
                'multiplier': highest_price / lowest_price if lowest_price > 0 else 0,
                'candle_count': len(candles)
            }
            
        except Exception as e:
            self._log(f"  ⚠️ Price range error: {str(e)}")
            return None

    def _get_token_detailed_info(self, token_address):
        """Get detailed token information - ✅ USES RETRY"""
        try:
            url = f"{self.st_base_url}/tokens/{token_address}"
            
            # ✅ USE RETRY instead of direct requests.get
            data = self.fetch_with_retry(
                url,
                self._get_solanatracker_headers(),
                semaphore=self.solana_tracker_semaphore
            )
            
            if not data:
                return None
            
            pools = data.get('pools', [])
            if not pools:
                return None
            
            primary_pool = max(pools, key=lambda p: p.get('liquidity', {}).get('usd', 0))
            
            # ✅ Get creation time for age calculation
            creation_time = data.get('creation', {}).get('created_time', 0)
            token_age_days = 0
            if creation_time > 0:
                token_age_days = (time.time() - creation_time) / 86400
            
            return {
                'symbol': data.get('symbol', 'UNKNOWN'),
                'name': data.get('name', 'Unknown'),
                'address': token_address,
                'liquidity': primary_pool.get('liquidity', {}).get('usd', 0),
                'volume_24h': primary_pool.get('txns', {}).get('volume24h', 0),
                'price': primary_pool.get('price', {}).get('usd', 0),
                'holders': data.get('holders', 0),
                'age_days': token_age_days,  # ✅ Numeric age
                'age': f"{token_age_days:.1f}d" if token_age_days > 0 else 'N/A'  # ✅ Formatted age
            }
            
        except Exception as e:
            self._log(f"  ⚠️ Token info error: {str(e)}")
            return None

    def find_trending_runners_enhanced(self, days_back=7, min_multiplier=5.0, min_liquidity=50000):
        """
        ✅ OPTIMIZED: Enhanced trending runner discovery with caching
        
        Changes:
        1. Limit to top 20 tokens (not 100) - 5x faster
        2. Added time.sleep(0.2) backoff to avoid 429s
        3. Disable cache for 30d (fresh Auto Discovery)
        4. 5-minute cache TTL for 7d/14d
        5. All fields present (ticker, chain, age)
        """
        cache_key = f"{days_back}_{min_multiplier}_{min_liquidity}"
        now = datetime.now()
        
        # ✅ SKIP CACHE for 30d (Auto Discovery always fresh)
        if days_back == 30:
            self._log(f"  ⚡ Skipping cache for 30d (one-off autodiscovery)")
        else:
            # Check cache for 7d/14d
            if cache_key in self._trending_cache:
                cache_age = now - self._cache_expiry[cache_key]
                if cache_age < timedelta(minutes=5):
                    self._log(f"  ⚡ Cache hit ({cache_key}) - age: {cache_age.seconds}s")
                    return self._trending_cache[cache_key]
        
        self._log(f"\n{'='*80}")
        self._log(f"FINDING TRENDING RUNNERS: {days_back} days, {min_multiplier}x+")
        self._log(f"{'='*80}")
        
        try:
            # ✅ Use fetch_with_retry for trending list
            url = f"{self.st_base_url}/tokens/trending"
            response = self.fetch_with_retry(
                url,
                self._get_solanatracker_headers(),
                semaphore=self.solana_tracker_semaphore
            )
            
            if not response:
                self._log(f"  ❌ Failed to fetch trending list")
                return []
            
            trending_data = response if isinstance(response, list) else []
            qualified_runners = []
            
            # ✅ LIMIT TO TOP 20 (not 100) - 5x faster
            for item in trending_data[:20]:
                try:
                    token = item.get('token', {})
                    pools = item.get('pools', [])
                    
                    if not pools or not token:
                        continue
                    
                    mint = token.get('mint')
                    pool = pools[0]
                    liquidity = pool.get('liquidity', {}).get('usd', 0)
                    
                    if liquidity < min_liquidity:
                        continue
                    
                    # ✅ Calculate multiplier within timeframe
                    price_range = self._get_price_range_in_period(mint, days_back)
                    if not price_range or price_range['multiplier'] < min_multiplier:
                        continue
                    
                    token_info = self._get_token_detailed_info(mint)
                    if not token_info:
                        continue
                    
                    ath_data = self.get_token_ath(mint)
                    
                    token_age_days = token_info.get('age_days', 0)
                    
                    qualified_runners.append({
                        'symbol': token.get('symbol', 'UNKNOWN'),
                        'ticker': token.get('symbol', 'UNKNOWN'),  # ✅ Frontend expects ticker
                        'name': token.get('name', 'Unknown'),
                        'address': mint,
                        'chain': 'solana',  # ✅ Frontend expects chain
                        'multiplier': round(price_range['multiplier'], 2),
                        'period_days': days_back,
                        'lowest_price': price_range['lowest_price'],
                        'highest_price': price_range['highest_price'],
                        'current_price': token_info['price'],
                        'ath_price': ath_data.get('highest_price', 0) if ath_data else 0,
                        'ath_time': ath_data.get('timestamp', 0) if ath_data else 0,
                        'liquidity': liquidity,
                        'volume_24h': token_info['volume_24h'],
                        'holders': token_info['holders'],
                        'token_age_days': round(token_age_days, 1),
                        'age': token_info.get('age', 'N/A'),  # ✅ Formatted age
                        'pair_address': pool.get('poolId', mint)
                    })
                    
                    # ✅ BACKOFF to avoid 429s
                    time.sleep(0.2)
                    
                except Exception as e:
                    self._log(f"  ⚠️ Token skip: {str(e)}")
                    continue
            
            qualified_runners.sort(key=lambda x: x['multiplier'], reverse=True)
            
            # ✅ ONLY CACHE 7d/14d (not 30d)
            if days_back != 30:
                self._trending_cache[cache_key] = qualified_runners
                self._cache_expiry[cache_key] = now
                self._log(f"  ✅ Found {len(qualified_runners)} runners (cached 5 min)")
            else:
                self._log(f"  ✅ Found {len(qualified_runners)} runners (no cache - one-off)")
            
            return qualified_runners
            
        except Exception as e:
            self._log(f"  ❌ Error finding runners: {str(e)}")
            return []

    # =========================================================================
    # PROFESSIONAL SCORING (60/30/10) - ✅ CORRECTED: DISTANCE BASED, NOT TIME
    # =========================================================================

    def calculate_wallet_professional_score(self, wallet_data, ath_price, ath_time=None):
        """
        ✅ CORRECTED: Professional scoring based ONLY on Distance to ATH
        
        SCORING COMPONENTS:
        1. Distance to ATH (60%) - Entry-to-ATH multiplier & percentage
        2. Realized Profit (30%) - Actual profits taken
        3. Total Position (10%) - Overall position value
        
        NO TIME-BASED SCORING.
        """
        try:
            entry_price = wallet_data.get('entry_price')
            realized_multiplier = wallet_data.get('realized_multiplier', 0)
            total_multiplier = wallet_data.get('total_multiplier', 0)
            
            # ============================================================
            # 1. DISTANCE TO ATH SCORE (60%)
            # ============================================================
            distance_to_ath_score = 0
            entry_to_ath_multiplier = None
            distance_to_ath_pct = None
            
            if entry_price and ath_price and ath_price > 0 and entry_price > 0:
                # Calculate multiplier (how many x below ATH they bought)
                entry_to_ath_multiplier = ath_price / entry_price
                
                # Calculate percentage (what % below ATH they bought)
                distance_to_ath_pct = ((ath_price - entry_price) / ath_price) * 100
                
                # Scoring based on multiplier distance
                if entry_to_ath_multiplier >= 10:
                    distance_to_ath_score = 100
                elif entry_to_ath_multiplier >= 5:
                    distance_to_ath_score = 80 + ((entry_to_ath_multiplier - 5) / 5) * 20
                elif entry_to_ath_multiplier >= 3:
                    distance_to_ath_score = 60 + ((entry_to_ath_multiplier - 3) / 2) * 20
                elif entry_to_ath_multiplier >= 2:
                    distance_to_ath_score = 40 + ((entry_to_ath_multiplier - 2) / 1) * 20
                elif entry_to_ath_multiplier >= 1.5:
                    distance_to_ath_score = 20 + ((entry_to_ath_multiplier - 1.5) / 0.5) * 20
                elif entry_to_ath_multiplier >= 1:
                    distance_to_ath_score = ((entry_to_ath_multiplier - 1) / 0.5) * 20
                else:
                    distance_to_ath_score = 0
            else:
                distance_to_ath_score = 50
            
            # ============================================================
            # 2. REALIZED PROFIT SCORE (30%)
            # ============================================================
            realized_profit_score = 0
            
            if realized_multiplier > 0:
                if realized_multiplier >= 10:
                    realized_profit_score = 100
                elif realized_multiplier >= 5:
                    realized_profit_score = 80 + ((realized_multiplier - 5) / 5) * 20
                elif realized_multiplier >= 3:
                    realized_profit_score = 60 + ((realized_multiplier - 3) / 2) * 20
                elif realized_multiplier >= 2:
                    realized_profit_score = 40 + ((realized_multiplier - 2) / 1) * 20
                elif realized_multiplier >= 1:
                    realized_profit_score = ((realized_multiplier - 1) / 1) * 40
            
            # ============================================================
            # 3. TOTAL POSITION SCORE (10%)
            # ============================================================
            total_position_score = 0
            
            if total_multiplier > 0:
                if total_multiplier >= 10:
                    total_position_score = 100
                elif total_multiplier >= 5:
                    total_position_score = 80 + ((total_multiplier - 5) / 5) * 20
                elif total_multiplier >= 3:
                    total_position_score = 60 + ((total_multiplier - 3) / 2) * 20
                elif total_multiplier >= 2:
                    total_position_score = 40 + ((total_multiplier - 2) / 1) * 20
                elif total_multiplier >= 1:
                    total_position_score = ((total_multiplier - 1) / 1) * 40
            
            # ============================================================
            # 4. WEIGHTED PROFESSIONAL SCORE (60/30/10)
            # ============================================================
            professional_score = (
                distance_to_ath_score * 0.60 +
                realized_profit_score * 0.30 +
                total_position_score * 0.10
            )
            
            # ============================================================
            # 5. GRADE ASSIGNMENT
            # ============================================================
            grade = 'F'
            if professional_score >= 90: grade = 'A+'
            elif professional_score >= 85: grade = 'A'
            elif professional_score >= 80: grade = 'A-'
            elif professional_score >= 75: grade = 'B+'
            elif professional_score >= 70: grade = 'B'
            elif professional_score >= 65: grade = 'B-'
            elif professional_score >= 60: grade = 'C+'
            elif professional_score >= 50: grade = 'C'
            elif professional_score >= 40: grade = 'D'
            
            return {
                'professional_score': round(professional_score, 2),
                'professional_grade': grade,
                'entry_to_ath_multiplier': round(entry_to_ath_multiplier, 2) if entry_to_ath_multiplier else None,
                'distance_to_ath_pct': round(distance_to_ath_pct, 2) if distance_to_ath_pct else None,
                'realized_multiplier': round(realized_multiplier, 2) if realized_multiplier else None,
                'total_multiplier': round(total_multiplier, 2) if total_multiplier else None,
                'score_breakdown': {
                    'distance_to_ath_score': round(distance_to_ath_score, 2),
                    'realized_profit_score': round(realized_profit_score, 2),
                    'total_position_score': round(total_position_score, 2)
                }
            }
            
        except Exception as e:
            print(f"[SCORING ERROR] {str(e)}")
            return {
                'professional_score': 0,
                'professional_grade': 'F',
                'entry_to_ath_multiplier': None,
                'distance_to_ath_pct': None,
                'realized_multiplier': None,
                'total_multiplier': None,
                'score_breakdown': {
                    'distance_to_ath_score': 0,
                    'realized_profit_score': 0,
                    'total_position_score': 0
                }
            }

    # =========================================================================
    # 30-DAY RUNNER HISTORY (THE DROPDOWN FEATURE) - ✅ WITH PER-RUNNER STATS
    # =========================================================================

    def _check_if_runner(self, token_address, min_multiplier=5.0):
        """Verify if token is actually a 5x+ runner in last 30 days"""
        try:
            price_range = self._get_price_range_in_period(token_address, 30)
            if not price_range or price_range['multiplier'] < min_multiplier:
                return None
            
            token_info = self._get_token_detailed_info(token_address)
            if not token_info:
                return None
            
            ath_data = self.get_token_ath(token_address)
            
            return {
                'address': token_address,
                'symbol': token_info['symbol'],
                'name': token_info['name'],
                'multiplier': round(price_range['multiplier'], 2),
                'current_price': token_info['price'],
                'ath_price': ath_data.get('highest_price', 0) if ath_data else 0,
                'liquidity': token_info['liquidity']
            }
            
        except:
            return None

    def get_wallet_other_runners(self, wallet_address, current_token_address=None, min_multiplier=5.0):
        """
        ✅ COMPLETE: Get other 5x+ runners WITH per-runner distance to ATH stats
        
        Returns for each runner:
        - entry_to_ath_multiplier (how many X below ATH they bought)
        - distance_to_ath_pct (what % below ATH they bought)
        - roi_multiplier, invested, realized
        
        Plus aggregate stats with averages.
        """
        try:
            trades = self.get_wallet_trades_30days(wallet_address)
            
            if not trades:
                return {'other_runners': [], 'stats': {}}
            
            token_addresses = set()
            for trade in trades:
                token_addr = trade.get('token_address')
                if token_addr and token_addr != current_token_address:
                    token_addresses.add(token_addr)
            
            other_runners = []
            
            for token_addr in list(token_addresses)[:15]:
                # Step 1: Verify it's a runner
                runner_info = self._check_if_runner(token_addr, min_multiplier)
                
                if not runner_info:
                    continue
                
                # Step 2: Get wallet's PnL on this token
                pnl_data = self.get_wallet_pnl_solanatracker(wallet_address, token_addr)
                
                if not pnl_data:
                    continue
                
                realized = pnl_data.get('realized', 0)
                invested = pnl_data.get('total_invested', 0)
                
                if invested <= 0:
                    continue
                
                # Calculate ROI
                roi_mult = (realized + invested) / invested
                runner_info['roi_multiplier'] = round(roi_mult, 2)
                runner_info['invested'] = round(invested, 2)
                runner_info['realized'] = round(realized, 2)
                
                # ✅ Step 3: Get wallet's ENTRY PRICE on this token
                first_buy = self.get_first_buy_for_wallet(wallet_address, token_addr)
                
                if first_buy and first_buy.get('price'):
                    entry_price = first_buy['price']
                    ath_price = runner_info.get('ath_price', 0)
                    
                    runner_info['entry_price'] = entry_price
                    
                    # ✅ Step 4: Calculate DISTANCE TO ATH for this runner
                    if entry_price > 0 and ath_price > 0:
                        entry_to_ath_mult = ath_price / entry_price
                        distance_pct = ((ath_price - entry_price) / ath_price) * 100
                        
                        runner_info['entry_to_ath_multiplier'] = round(entry_to_ath_mult, 2)
                        runner_info['distance_to_ath_pct'] = round(distance_pct, 2)
                    else:
                        runner_info['entry_to_ath_multiplier'] = None
                        runner_info['distance_to_ath_pct'] = None
                else:
                    runner_info['entry_price'] = None
                    runner_info['entry_to_ath_multiplier'] = None
                    runner_info['distance_to_ath_pct'] = None
                
                other_runners.append(runner_info)
                time.sleep(0.2)
            
            # ✅ Step 5: Calculate AGGREGATE STATS
            stats = {}
            
            if other_runners:
                # Success rate
                successful = sum(1 for r in other_runners if r.get('roi_multiplier', 0) > 1)
                stats['success_rate'] = round(successful / len(other_runners) * 100, 1)
                
                # Average ROI
                roi_values = [r.get('roi_multiplier', 0) for r in other_runners if r.get('roi_multiplier')]
                if roi_values:
                    stats['avg_roi'] = round(sum(roi_values) / len(roi_values), 2)
                
                # ✅ Average Entry-to-ATH Multiplier
                entry_to_ath_values = [
                    r.get('entry_to_ath_multiplier', 0) 
                    for r in other_runners 
                    if r.get('entry_to_ath_multiplier')
                ]
                if entry_to_ath_values:
                    stats['avg_entry_to_ath'] = round(sum(entry_to_ath_values) / len(entry_to_ath_values), 2)
                
                # ✅ Average Distance to ATH Percentage
                distance_pct_values = [
                    r.get('distance_to_ath_pct', 0) 
                    for r in other_runners 
                    if r.get('distance_to_ath_pct')
                ]
                if distance_pct_values:
                    stats['avg_distance_to_ath_pct'] = round(sum(distance_pct_values) / len(distance_pct_values), 2)
                
                # Total invested/realized
                total_invested = sum(r.get('invested', 0) for r in other_runners)
                total_realized = sum(r.get('realized', 0) for r in other_runners)
                stats['total_invested'] = round(total_invested, 2)
                stats['total_realized'] = round(total_realized, 2)
                
                stats['total_other_runners'] = len(other_runners)
            
            return {
                'other_runners': other_runners,
                'stats': stats
            }
            
        except Exception as e:
            self._log(f"  ⚠️ Error getting 30-day runners: {str(e)}")
            return {'other_runners': [], 'stats': {}}

    # =========================================================================
    # THE COMPLETE 6-STEP ANALYSIS (FROM DOCUMENT 6)
    # =========================================================================

    def analyze_token_professional(self, token_address, token_symbol="UNKNOWN", 
                                   min_roi_multiplier=3.0, user_id='default_user'):
        """
        COMPLETE 6-STEP PROFESSIONAL ANALYSIS (from Document 6)
        
        Step 1: Fetch top traders + first buy timestamps
        Step 2: Fetch first buyers + entry prices
        Step 3: Fetch Birdeye historical trades (30 days)
        Step 4: Fetch recent Solana Tracker trades
        Step 5: Fetch PnL, filter for ≥3x ROI AND ≥$100 invested
        Step 6: Rank by professional score (60/30/10)
        
        Returns: List of wallets with professional scoring + 30-day dropdown data
        """
        self._log(f"\n{'='*80}")
        self._log(f"6-STEP PROFESSIONAL ANALYSIS: {token_symbol}")
        self._log(f"{'='*80}")
        
        # Initialize executor for this analysis
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
        try:
            all_wallets = set()
            wallet_data = {}
            
            # STEP 1: Fetch top traders from Solana Tracker
            self._log("\n[STEP 1] Fetching top traders from Solana Tracker...")
            url = f"{self.st_base_url}/top-traders/{token_address}"
            data = self.fetch_with_retry(
                url, 
                self._get_solanatracker_headers(), 
                semaphore=self.solana_tracker_semaphore
            )
            
            if data:
                traders = data if isinstance(data, list) else []
                self._log(f"  ✓ Found {len(traders)} top traders")
                
                for i, trader in enumerate(traders, 1):
                    wallet = trader.get('wallet')
                    if wallet:
                        all_wallets.add(wallet)
                        
                        first_buy_data = self.get_first_buy_for_wallet(wallet, token_address)
                        
                        wallet_data[wallet] = {
                            'source': 'top_traders',
                            'pnl_data': trader,
                            'earliest_entry': first_buy_data['time'] if first_buy_data else None,
                            'entry_price': first_buy_data['price'] if first_buy_data else None
                        }
                        
                        if i % 10 == 0:
                            self._log(f"    Processed {i}/{len(traders)} traders...")
                        
                        time.sleep(0.3)
            
            # STEP 2: Fetch first buyers from Solana Tracker
            self._log("\n[STEP 2] Fetching first buyers from Solana Tracker...")
            url = f"{self.st_base_url}/first-buyers/{token_address}"
            data = self.fetch_with_retry(
                url, 
                self._get_solanatracker_headers(), 
                semaphore=self.solana_tracker_semaphore
            )
            
            if data:
                buyers = data if isinstance(data, list) else data.get('buyers', [])
                first_buyer_wallets = set()
                
                for buyer in buyers:
                    wallet = buyer.get('wallet')
                    if wallet:
                        first_buyer_wallets.add(wallet)
                        first_buy_time = buyer.get('first_buy_time', 0)
                        
                        if wallet not in all_wallets:
                            wallet_data[wallet] = {
                                'source': 'first_buyers',
                                'pnl_data': buyer,
                                'earliest_entry': first_buy_time,
                                'entry_price': None
                            }
                        else:
                            wallet_data[wallet]['pnl_data'] = buyer
                            wallet_data[wallet]['earliest_entry'] = first_buy_time
                            wallet_data[wallet]['source'] = 'first_buyers'
                
                new_wallets = first_buyer_wallets - all_wallets
                all_wallets.update(first_buyer_wallets)
                
                self._log(f"  ✓ Found {len(buyers)} first buyers ({len(new_wallets)} new)")
                
                # Fetch entry prices
                futures = {}
                for wallet in first_buyer_wallets:
                    future = self.executor.submit(self.get_first_buy_for_wallet, wallet, token_address)
                    futures[future] = wallet
                
                processed = 0
                for future in as_completed(futures.keys()):
                    wallet = futures[future]
                    first_buy_data = future.result()
                    
                    if first_buy_data:
                        wallet_data[wallet]['entry_price'] = first_buy_data['price']
                    
                    processed += 1
                    if processed % 20 == 0:
                        self._log(f"    Processed {processed}/{len(first_buyer_wallets)} wallets...")
            
            # STEP 3: Fetch Birdeye historical trades (30 days)
            self._log("\n[STEP 3] Fetching Birdeye historical trades (30 days)...")
            
            current_time = int(time.time())
            after_time = current_time - (30 * 86400)
            
            all_birdeye_trades = []
            offset = 0
            max_offset = 10000
            limit = 100
            
            while offset < max_offset:
                params = {
                    "address": token_address,
                    "offset": offset,
                    "limit": limit,
                    "sort_by": "block_unix_time",
                    "sort_type": "asc",
                    "tx_type": "all",
                    "ui_amount_mode": "scaled",
                    "after_time": after_time
                }
                
                url = f"{self.birdeye_base_url}/defi/v3/token/txs"
                data = self.fetch_with_retry(
                    url, 
                    self._get_birdeye_headers(), 
                    params, 
                    semaphore=self.birdeye_semaphore
                )
                
                if not data or not data.get('success'):
                    break
                
                trades = data.get('data', {}).get('items', [])
                
                if not trades:
                    break
                
                all_birdeye_trades.extend(trades)
                
                if len(trades) < limit:
                    break
                
                offset += limit
                time.sleep(0.5)
            
            self._log(f"  ✓ Found {len(all_birdeye_trades)} Birdeye trades")
            
            birdeye_wallets = set()
            for trade in all_birdeye_trades:
                wallet = trade.get('owner')
                if wallet and wallet not in all_wallets:
                    birdeye_wallets.add(wallet)
                    trade_time = trade.get('block_unix_time')
                    trade_price = trade.get('price_pair')
                    
                    wallet_data[wallet] = {
                        'source': 'birdeye_trades',
                        'earliest_entry': trade_time,
                        'entry_price': trade_price
                    }
            
            new_wallets = birdeye_wallets - all_wallets
            all_wallets.update(birdeye_wallets)
            
            self._log(f"  ✓ Found {len(new_wallets)} new wallets from Birdeye")
            
            # Get first buy for Birdeye wallets
            if birdeye_wallets:
                futures = {}
                for wallet in birdeye_wallets:
                    future = self.executor.submit(self.get_first_buy_for_wallet, wallet, token_address)
                    futures[future] = wallet
                
                processed = 0
                for future in as_completed(futures.keys()):
                    wallet = futures[future]
                    first_buy_data = future.result()
                    
                    if first_buy_data:
                        if wallet_data[wallet].get('entry_price') is None:
                            wallet_data[wallet]['entry_price'] = first_buy_data['price']
                        wallet_entry = wallet_data[wallet].get('earliest_entry', float('inf'))
                        if first_buy_data['time'] < wallet_entry:
                            wallet_data[wallet]['earliest_entry'] = first_buy_data['time']
                    
                    processed += 1
                    if processed % 50 == 0:
                        self._log(f"    Processed {processed}/{len(birdeye_wallets)} wallets...")
            
            # STEP 4: Fetch recent Solana Tracker trades
            self._log("\n[STEP 4] Fetching recent Solana Tracker trades...")
            
            url = f"{self.st_base_url}/trades/{token_address}"
            params = {"sortDirection": "DESC", "limit": 100}
            data = self.fetch_with_retry(
                url, 
                self._get_solanatracker_headers(), 
                params, 
                semaphore=self.solana_tracker_semaphore
            )
            
            if data:
                trades = data.get('trades', [])
                recent_wallets = set()
                
                for trade in trades[:500]:
                    wallet = trade.get('wallet')
                    trade_time = trade.get('time', 0)
                    
                    if wallet and wallet not in all_wallets:
                        recent_wallets.add(wallet)
                        wallet_data[wallet] = {
                            'source': 'solana_recent',
                            'earliest_entry': trade_time
                        }
                
                new_wallets = recent_wallets - all_wallets
                all_wallets.update(recent_wallets)
                
                self._log(f"  ✓ Found {len(recent_wallets)} recent traders ({len(new_wallets)} new)")
            
            # STEP 5: Fetch PnL and filter for ≥3x ROI AND ≥$100 invested
            self._log(f"\n[STEP 5] Fetching PnL for {len(all_wallets)} wallets...")
            
            wallets_with_pnl = []
            wallets_to_fetch = []
            
            for wallet in all_wallets:
                if wallet_data[wallet].get('pnl_data'):
                    wallets_with_pnl.append(wallet)
                else:
                    wallets_to_fetch.append(wallet)
            
            self._log(f"  ✓ {len(wallets_with_pnl)} wallets already have PnL")
            self._log(f"  → Fetching PnL for {len(wallets_to_fetch)} remaining wallets...")
            
            qualified_wallets = []
            
            # Process existing PnL
            for wallet in wallets_with_pnl:
                pnl_data = wallet_data[wallet]['pnl_data']
                if self._process_wallet_pnl(wallet, pnl_data, wallet_data, qualified_wallets, min_roi_multiplier):
                    pass
            
            # Fetch and process remaining PnL
            futures = {}
            for i, wallet in enumerate(wallets_to_fetch):
                future = self.executor.submit(self.get_wallet_pnl_solanatracker, wallet, token_address)
                futures[future] = wallet
                
                if i > 0 and i % 3 == 0:
                    time.sleep(0.5)
            
            completed = 0
            for future in as_completed(futures.keys()):
                wallet = futures[future]
                pnl_data = future.result()
                
                if pnl_data:
                    wallet_data[wallet]['pnl_data'] = pnl_data
                    self._process_wallet_pnl(wallet, pnl_data, wallet_data, qualified_wallets, min_roi_multiplier)
                
                completed += 1
                if completed % 20 == 0:
                    self._log(f"    Processed {completed}/{len(wallets_to_fetch)} wallets...")
            
            self._log(f"  ✓ Found {len(qualified_wallets)} qualified wallets")
            
            # STEP 6: Rank by professional score
            self._log("\n[STEP 6] Ranking by professional score...")
            
            ath_data = self.get_token_ath(token_address)
            ath_price = ath_data.get('highest_price', 0) if ath_data else 0
            ath_time = ath_data.get('timestamp', 0) if ath_data else 0
            
            wallet_results = []
            
            for wallet_info in qualified_wallets:
                wallet_address = wallet_info['wallet']
                
                # Get 30-day runner history (THE DROPDOWN) with per-runner stats
                runner_history = self.get_wallet_other_runners(wallet_address, token_address, min_multiplier=5.0)
                
                # Calculate professional score
                wallet_data_for_scoring = {
                    'entry_price': wallet_info.get('entry_price'),
                    'first_buy_time': wallet_info.get('earliest_entry'),
                    'realized_multiplier': wallet_info['realized_multiplier'],
                    'total_multiplier': wallet_info['total_multiplier']
                }
                
                professional_score_data = self.calculate_wallet_professional_score(
                    wallet_data_for_scoring, ath_price, ath_time
                )
                
                wallet_results.append({
                    'wallet': wallet_address,
                    'source': wallet_info['source'],
                    'roi_percent': round((wallet_info['realized_multiplier'] - 1) * 100, 2),
                    'roi_multiplier': round(wallet_info['realized_multiplier'], 2),
                    'ath_distance': self.calculate_ath_distance_for_wallet(
                        token_address, 
                        wallet_info.get('cost_basis', 0)
                    ),
                    'entry_to_ath_multiplier': professional_score_data.get('entry_to_ath_multiplier'),
                    'distance_to_ath_pct': professional_score_data.get('distance_to_ath_pct'),
                    'realized_profit': wallet_info['realized'],
                    'unrealized_profit': wallet_info['unrealized'],
                    'total_invested': wallet_info['total_invested'],
                    'cost_basis': wallet_info.get('cost_basis', 0),
                    'realized_multiplier': professional_score_data.get('realized_multiplier'),
                    'total_multiplier': professional_score_data.get('total_multiplier'),
                    
                    # Professional scoring
                    'professional_score': professional_score_data['professional_score'],
                    'professional_grade': professional_score_data['professional_grade'],
                    'score_breakdown': professional_score_data['score_breakdown'],
                    
                    # 30-day runner history (DROPDOWN DATA with per-runner stats)
                    'runner_hits_30d': runner_history['stats'].get('total_other_runners', 0),
                    'runner_success_rate': runner_history['stats'].get('success_rate', 0),
                    'runner_avg_roi': runner_history['stats'].get('avg_roi', 0),
                    'other_runners': runner_history['other_runners'][:5],
                    'other_runners_stats': runner_history['stats'],  # ✅ Add aggregate stats
                    
                    # Timing data
                    'first_buy_time': wallet_info.get('earliest_entry'),
                    'entry_price': wallet_info.get('entry_price'),
                    
                    'is_fresh': True  # TODO: Implement watchlist check
                })
            
            # Rank by professional score
            wallet_results.sort(key=lambda x: x['professional_score'], reverse=True)
            
            self._log(f"  ✅ Analysis complete: {len(wallet_results)} qualified wallets")
            if wallet_results:
                self._log(f"  Top score: {wallet_results[0]['professional_score']} ({wallet_results[0]['professional_grade']})")
            
            return wallet_results
            
        finally:
            # Shutdown executor
            if self.executor:
                self.executor.shutdown(wait=True)
                self.executor = None

    def _process_wallet_pnl(self, wallet, pnl_data, wallet_data, qualified_wallets, min_roi_multiplier):
        """Process PnL and add to qualified if ≥3x ROI AND ≥$100 invested"""
        realized = pnl_data.get('realized', 0)
        unrealized = pnl_data.get('unrealized', 0)
        total_invested = pnl_data.get('total_invested') or pnl_data.get('totalInvested', 0)
        
        if total_invested < 100:
            return False
        
        realized_multiplier = (realized + total_invested) / total_invested
        total_multiplier = (realized + unrealized + total_invested) / total_invested
        
        min_roi_pct = (min_roi_multiplier - 1) * 100
        roi_pct = (realized_multiplier - 1) * 100
        
        if roi_pct >= min_roi_pct:
            earliest_entry = wallet_data[wallet].get('earliest_entry')
            if not earliest_entry:
                earliest_entry = pnl_data.get('first_buy_time', 0)
            
            entry_price = wallet_data[wallet].get('entry_price')
            
            qualified_wallets.append({
                'wallet': wallet,
                'source': wallet_data[wallet]['source'],
                'realized': realized,
                'unrealized': unrealized,
                'total_invested': total_invested,
                'realized_multiplier': realized_multiplier,
                'total_multiplier': total_multiplier,
                'earliest_entry': earliest_entry,
                'entry_price': entry_price,
                'cost_basis': pnl_data.get('cost_basis', 0)
            })
            return True
        
        return False

    # =========================================================================
    # BATCH ANALYSIS (MULTI-TOKEN WITH CONSISTENCY)
    # =========================================================================

    def batch_analyze_runners_professional(self, runners_list, min_runner_hits=2, 
                                           min_roi_multiplier=3.0, user_id='default_user'):
        """
        BATCH ANALYSIS across multiple runners with consistency tracking
        Uses 6-step analysis on each runner
        """
        self._log(f"\n{'='*80}")
        self._log(f"BATCH PROFESSIONAL ANALYSIS (6-STEP)")
        self._log(f"Analyzing {len(runners_list)} runners")
        self._log(f"{'='*80}")
        
        wallet_hits = defaultdict(lambda: {
            'wallet': None,
            'runners_hit': [],
            'runners_hit_addresses': set(),
            'roi_details': [],
            'professional_scores': [],
            'ath_distances': [],
            'entry_to_ath_multipliers': []
        })
        
        for idx, runner in enumerate(runners_list, 1):
            self._log(f"\n  [{idx}/{len(runners_list)}] Analyzing {runner.get('symbol', 'UNKNOWN')}")
            
            # Run 6-step analysis
            wallets = self.analyze_token_professional(
                token_address=runner['address'],
                token_symbol=runner.get('symbol', 'UNKNOWN'),
                min_roi_multiplier=min_roi_multiplier,
                user_id=user_id
            )
            
            for wallet in wallets[:50]:
                wallet_addr = wallet['wallet']
                
                if wallet_hits[wallet_addr]['wallet'] is None:
                    wallet_hits[wallet_addr]['wallet'] = wallet_addr
                
                if runner['symbol'] not in wallet_hits[wallet_addr]['runners_hit']:
                    wallet_hits[wallet_addr]['runners_hit'].append(runner['symbol'])
                    wallet_hits[wallet_addr]['runners_hit_addresses'].add(runner['address'])
                
                wallet_hits[wallet_addr]['roi_details'].append({
                    'runner': runner['symbol'],
                    'runner_address': runner['address'],
                    'roi_percent': wallet['roi_percent'],
                    'roi_multiplier': wallet['roi_multiplier'],
                    'professional_score': wallet['professional_score'],
                    'professional_grade': wallet['professional_grade'],
                    'ath_distance': wallet['ath_distance'],
                    'entry_to_ath_multiplier': wallet.get('entry_to_ath_multiplier')
                })
                
                wallet_hits[wallet_addr]['professional_scores'].append(wallet['professional_score'])
                wallet_hits[wallet_addr]['ath_distances'].append(wallet['ath_distance'])
                if wallet.get('entry_to_ath_multiplier'):
                    wallet_hits[wallet_addr]['entry_to_ath_multipliers'].append(wallet['entry_to_ath_multiplier'])
        
        smart_money = []
        
        for wallet_addr, data in wallet_hits.items():
            if len(data['runners_hit']) < min_runner_hits:
                continue
            
            avg_professional_score = sum(data['professional_scores']) / len(data['professional_scores'])
            avg_roi = sum(r['roi_percent'] for r in data['roi_details']) / len(data['roi_details'])
            avg_ath_distance = sum(data['ath_distances']) / len(data['ath_distances']) if data['ath_distances'] else 0
            avg_entry_to_ath = sum(data['entry_to_ath_multipliers']) / len(data['entry_to_ath_multipliers']) if data['entry_to_ath_multipliers'] else None
            
            if len(data['professional_scores']) > 1:
                variance = statistics.variance(data['professional_scores'])
            else:
                variance = 0
            
            if variance < 10:
                consistency_grade = 'A+'
            elif variance < 20:
                consistency_grade = 'A'
            elif variance < 30:
                consistency_grade = 'B'
            elif variance < 40:
                consistency_grade = 'C'
            else:
                consistency_grade = 'D'
            
            full_history = self.get_wallet_other_runners(wallet_addr, min_multiplier=5.0)
            
            batch_runner_addresses = data['runners_hit_addresses']
            outside_batch_runners = [
                r for r in full_history['other_runners']
                if r['address'] not in batch_runner_addresses
            ]
            
            smart_money.append({
                'wallet': wallet_addr,
                'runner_count': len(data['runners_hit']),
                'runners_hit': data['runners_hit'],
                'avg_professional_score': round(avg_professional_score, 2),
                'avg_roi': round(avg_roi, 2),
                'avg_ath_distance': round(avg_ath_distance, 2),
                'avg_entry_to_ath_multiplier': round(avg_entry_to_ath, 2) if avg_entry_to_ath else None,
                'variance': round(variance, 2),
                'consistency_grade': consistency_grade,
                'roi_details': data['roi_details'][:5],
                'total_runners_30d': len(data['runners_hit']) + len(outside_batch_runners),
                'in_batch_count': len(data['runners_hit']),
                'outside_batch_count': len(outside_batch_runners),
                'outside_batch_runners': outside_batch_runners[:5],
                'full_30d_stats': full_history['stats'],
                'is_fresh': True
            })
        
        smart_money.sort(
            key=lambda x: (x['runner_count'], x['avg_professional_score'], -x['variance']),
            reverse=True
        )
        
        self._log(f"\n  ✅ Found {len(smart_money)} consistent smart money wallets")
        
        return smart_money

    # =========================================================================
    # REPLACEMENT FINDER METHODS
    # =========================================================================

    def find_replacement_wallets(self, declining_wallet_address, user_id='default_user', 
                                 min_professional_score=85, max_results=3):
        """
        Find replacement wallets for a degrading wallet using existing metrics.
        
        Args:
            declining_wallet_address: Address of wallet being replaced
            user_id: User ID for checking watchlist
            min_professional_score: Minimum score for candidates (default 85)
            max_results: Number of suggestions to return (default 3)
            
        Returns:
            List of replacement candidates with similarity scores
        """
        
        print(f"\n{'='*80}")
        print(f"FINDING REPLACEMENTS FOR: {declining_wallet_address[:8]}...")
        print(f"{'='*80}")
        
        # STEP 1: Get declining wallet's profile from watchlist
        declining_profile = self._get_wallet_profile_from_watchlist(
            user_id, 
            declining_wallet_address
        )
        
        if not declining_profile:
            print(f"  ⚠️ Wallet not found in watchlist")
            return []
        
        print(f"  Profile: {declining_profile['tier']} tier, "
              f"{len(declining_profile['tokens_traded'])} tokens traded")
        
        # STEP 2: Get recent 30-day runners to find active wallets
        print(f"\n  [1/3] Discovering recent runners...")
        runners = self.find_trending_runners_enhanced(
            days_back=30,
            min_multiplier=5.0,
            min_liquidity=50000
        )
        
        if not runners:
            print(f"  ⚠️ No runners found")
            return []
        
        print(f"  ✓ Found {len(runners)} runners")
        
        # STEP 3: Analyze top runners to get fresh wallets
        print(f"\n  [2/3] Analyzing top runners for candidates...")
        
        all_candidates = []
        tokens_to_check = runners[:10]  # Top 10 hottest runners
        
        for runner in tokens_to_check:
            # Run 6-step analysis on this runner
            wallets = self.analyze_token_professional(
                token_address=runner['address'],
                token_symbol=runner['symbol'],
                min_roi_multiplier=3.0,
                user_id=user_id
            )
            
            # Filter for high performers only
            qualified = [
                w for w in wallets 
                if w['professional_score'] >= min_professional_score
                and w.get('is_fresh', True)  # Not already in watchlist
            ]
            
            all_candidates.extend(qualified)
        
        print(f"  ✓ Found {len(all_candidates)} candidate wallets")
        
        # STEP 4: Score candidates by similarity to declining wallet
        print(f"\n  [3/3] Scoring candidates by similarity...")
        
        scored_candidates = []
        
        for candidate in all_candidates:
            # Calculate similarity score
            similarity = self._calculate_similarity_score(
                declining_profile,
                candidate
            )
            
            # Add to results if similarity is decent
            if similarity['total_score'] > 0.3:  # 30% minimum similarity
                scored_candidates.append({
                    **candidate,
                    'similarity_score': similarity['total_score'],
                    'similarity_breakdown': similarity['breakdown'],
                    'why_better': self._explain_why_better(declining_profile, candidate)
                })
        
        # STEP 5: Rank by combination of similarity + performance
        scored_candidates.sort(
            key=lambda x: (
                x['similarity_score'] * 0.6 +  # 60% similarity weight
                (x['professional_score'] / 100) * 0.4  # 40% performance weight
            ),
            reverse=True
        )
        
        top_matches = scored_candidates[:max_results]
        
        print(f"\n  ✅ Top {len(top_matches)} replacements found:")
        for i, match in enumerate(top_matches, 1):
            print(f"    {i}. {match['wallet'][:8]}... "
                  f"(Score: {match['professional_score']}, "
                  f"Similarity: {match['similarity_score']:.1%})")
        
        return top_matches

    def _get_wallet_profile_from_watchlist(self, user_id, wallet_address):
        """Get wallet's historical profile from watchlist database"""
        try:
            from db.watchlist_db import WatchlistDatabase
            
            db = WatchlistDatabase()
            watchlist = db.get_wallet_watchlist(user_id)
            
            # Find this specific wallet
            wallet_data = next(
                (w for w in watchlist if w['wallet_address'] == wallet_address),
                None
            )
            
            if not wallet_data:
                return None
            
            # Extract token list
            tokens_traded = []
            if wallet_data.get('tokens_hit'):
                if isinstance(wallet_data['tokens_hit'], list):
                    tokens_traded = wallet_data['tokens_hit']
                else:
                    tokens_traded = [
                        t.strip() 
                        for t in str(wallet_data['tokens_hit']).split(',')
                    ]
            
            return {
                'wallet_address': wallet_address,
                'tier': wallet_data.get('tier', 'C'),
                'professional_score': wallet_data.get('avg_professional_score', 0),
                'tokens_traded': tokens_traded,
                'avg_roi': wallet_data.get('avg_roi_to_peak', 0),
                'pump_count': wallet_data.get('pump_count', 0),
                'consistency_score': wallet_data.get('consistency_score', 0)
            }
            
        except Exception as e:
            print(f"  ⚠️ Error loading wallet profile: {e}")
            return None

    def _calculate_similarity_score(self, declining_profile, candidate):
        """
        Calculate how similar a candidate is to the declining wallet.
        Uses YOUR existing metrics.
        """
        
        # 1. TOKEN OVERLAP (40% weight)
        declining_tokens = set(declining_profile['tokens_traded'])
        
        # Get candidate's token preferences from 'other_runners'
        candidate_tokens = set()
        if candidate.get('other_runners'):
            candidate_tokens = {
                r['symbol'] 
                for r in candidate['other_runners']
            }
        
        if declining_tokens and candidate_tokens:
            overlap = len(declining_tokens & candidate_tokens)
            total = len(declining_tokens | candidate_tokens)
            token_score = overlap / total if total > 0 else 0
        else:
            token_score = 0.5  # Neutral if no data
        
        # 2. TIER MATCH (30% weight)
        tier_values = {'S': 4, 'A': 3, 'B': 2, 'C': 1}
        
        declining_tier_value = tier_values.get(declining_profile['tier'], 1)
        
        # Get candidate tier from professional_grade if no tier field
        candidate_tier = candidate.get('tier')
        if not candidate_tier:
            grade = candidate.get('professional_grade', 'C')
            if grade in ['A+', 'A', 'A-']:
                candidate_tier = 'S'
            elif grade in ['B+', 'B', 'B-']:
                candidate_tier = 'A'
            elif grade in ['C+', 'C']:
                candidate_tier = 'B'
            else:
                candidate_tier = 'C'
        
        candidate_tier_value = tier_values.get(candidate_tier, 1)
        
        # Prefer same tier or better
        if candidate_tier_value >= declining_tier_value:
            tier_score = 1.0
        elif candidate_tier_value == declining_tier_value - 1:
            tier_score = 0.7
        else:
            tier_score = 0.3
        
        # 3. ACTIVITY LEVEL (20% weight)
        # Compare runner hit counts
        declining_activity = declining_profile.get('pump_count', 0)
        candidate_activity = candidate.get('runner_hits_30d', 0)
        
        if declining_activity > 0:
            activity_ratio = min(candidate_activity / declining_activity, 2.0)
            activity_score = activity_ratio / 2.0  # Normalize to 0-1
        else:
            activity_score = 1.0 if candidate_activity > 0 else 0.5
        
        # 4. CONSISTENCY (10% weight)
        # Use your consistency_grade or variance
        candidate_consistency = candidate.get('consistency_grade', 'C')
        
        consistency_values = {
            'A+': 1.0, 'A': 0.9, 'B': 0.7, 'C': 0.5, 'D': 0.3
        }
        consistency_score = consistency_values.get(candidate_consistency, 0.5)
        
        # CALCULATE WEIGHTED TOTAL
        total_score = (
            token_score * 0.40 +
            tier_score * 0.30 +
            activity_score * 0.20 +
            consistency_score * 0.10
        )
        
        return {
            'total_score': total_score,
            'breakdown': {
                'token_overlap': token_score,
                'tier_match': tier_score,
                'activity_level': activity_score,
                'consistency': consistency_score
            }
        }

    def _explain_why_better(self, declining_profile, candidate):
        """
        Generate human-readable reasons why candidate is better.
        Returns list of improvement points.
        """
        reasons = []
        
        # Compare professional scores
        declining_score = declining_profile.get('professional_score', 0)
        candidate_score = candidate.get('professional_score', 0)
        
        if candidate_score > declining_score:
            diff = candidate_score - declining_score
            reasons.append(f"Professional score +{diff:.0f} points higher")
        
        # Compare runner hits
        declining_runners = declining_profile.get('pump_count', 0)
        candidate_runners = candidate.get('runner_hits_30d', 0)
        
        if candidate_runners > declining_runners:
            reasons.append(
                f"{candidate_runners} runners last 30d "
                f"(vs {declining_runners} for old wallet)"
            )
        
        # Compare ROI
        declining_roi = declining_profile.get('avg_roi', 0)
        candidate_roi = candidate.get('roi_multiplier', 0) * 100
        
        if candidate_roi > declining_roi:
            diff = candidate_roi - declining_roi
            reasons.append(f"+{diff:.0f}% better ROI")
        
        # Check if actively trading
        if candidate.get('runner_hits_30d', 0) > 0:
            reasons.append("Currently active (recent runner hits)")
        
        # Check tier upgrade
        candidate_grade = candidate.get('professional_grade', 'C')
        if candidate_grade in ['A+', 'A', 'A-'] and declining_profile['tier'] not in ['S', 'A']:
            reasons.append("Tier upgrade to S/A-tier")
        
        # Consistency grade
        if candidate.get('consistency_grade') in ['A+', 'A']:
            reasons.append(f"High consistency ({candidate['consistency_grade']})")
        
        return reasons