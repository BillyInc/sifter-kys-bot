import requests
from datetime import datetime
from collections import defaultdict
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore
from datetime import datetime, timedelta
import duckdb
import time
import asyncio
import aiohttp
from asyncio import Semaphore as AsyncSemaphore
class WalletPumpAnalyzer:
    """
    FIXED WALLET ANALYZER - Uses TokenAnalyzer's Relative Scoring
 
    THE 6 STEPS (from TokenAnalyzer):
    1. Fetch top traders from Solana Tracker + first buy timestamps
    2. Fetch first buyers from Solana Tracker + entry prices
    3. Fetch Birdeye historical trades (30 days back)
    4. Fetch recent Solana Tracker trades
    5. Fetch PnL for ALL wallets, filter for ≥3x ROI AND ≥$100 invested
    6. Rank by RELATIVE score (like TokenAnalyzer - no days-to-ATH)
 
    SCORING (60/30/10):
    - 60% Entry-to-ATH RELATIVE (scaled to max in batch)
    - 30% Realized ROI RELATIVE (scaled to max in batch)
    - 10% Total ROI RELATIVE (scaled to max in batch)
 
    All wallets get 30-day runner history tracking
    """
    def __init__(self, solanatracker_api_key, birdeye_api_key=None, debug_mode=True):
        self.solanatracker_key = solanatracker_api_key
        self.birdeye_key = birdeye_api_key or "a49c49de31d34574967c13bd35f3c523"
        self.st_base_url = "https://data.solanatracker.io"
        self.birdeye_base_url = "https://public-api.birdeye.so"
        self.debug_mode = debug_mode
        self.duckdb_path = 'wallet_analytics.duckdb'
        self.con = duckdb.connect(self.duckdb_path)
        # Concurrency control
        self.max_workers = 8
        self.birdeye_semaphore = Semaphore(2)
        self.solana_tracker_semaphore = Semaphore(3)
        self.pnl_semaphore = Semaphore(2)
        self.birdeye_async_semaphore = AsyncSemaphore(2)
        self.solana_tracker_async_semaphore = AsyncSemaphore(3)
        self.pnl_async_semaphore = AsyncSemaphore(2)
        self.executor = None
        # Caching for trending runners
        self._trending_cache = {}
        self._cache_expiry = {}
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS wallet_token_cache (
        wallet TEXT,
        token TEXT,
        realized REAL,
        unrealized REAL,
        total_invested REAL,
        entry_price REAL,
        first_buy_time BIGINT,
        last_updated REAL, -- unix timestamp
        runner_multiplier REAL,
        PRIMARY KEY (wallet, token)
    )
""")
        # Add this after the first CREATE TABLE
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS wallet_runner_cache (
                wallet STRING PRIMARY KEY,
                other_runners JSON, -- Store as JSON string
                stats JSON, -- Store as JSON string
                last_updated FLOAT
            )
        """)
        # New table for token-level runner checks
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS token_runner_cache (
                token STRING PRIMARY KEY,
                runner_info JSON,
                last_updated FLOAT
            )
        """)
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_wallet_token ON wallet_token_cache(wallet, token)")
        self._log("DuckDB cache initialized")
     
     
        # Create tables once
    
# Add index for speed
 
     
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
    async def async_fetch_with_retry(self, session, url: str, headers: dict, params: dict = None,
                                     semaphore: AsyncSemaphore = None, max_retries: int = 3):
        for attempt in range(max_retries):
            try:
                if semaphore:
                    async with semaphore:
                        async with session.get(url, headers=headers, params=params, timeout=15) as response:
                            if response.status == 200:
                                return await response.json()
                            elif response.status == 404:
                                return None
                            elif response.status == 429:
                                wait_time = int(response.headers.get('Retry-After', 5))
                                self._log(f"Rate limited. Waiting {wait_time}s...")
                                await asyncio.sleep(wait_time)
                                await asyncio.sleep(2 ** attempt)
                            elif response.status == 500:
                                return None
                            else:
                                return None
                else:
                    async with session.get(url, headers=headers, params=params, timeout=15) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 404:
                            return None
                        elif response.status == 429:
                            wait_time = int(response.headers.get('Retry-After', 5))
                            self._log(f"Rate limited. Waiting {wait_time}s...")
                            await asyncio.sleep(wait_time)
                            await asyncio.sleep(2 ** attempt)
                        elif response.status == 500:
                            return None
                        else:
                            return None
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        return None
    # =========================================================================
    # BASIC DATA FETCHING METHODS
    # =========================================================================
 
    # Add this new method
    def _get_cached_pnl_and_entry(self, wallet, token):
        """Check cache first, fallback to API, then cache"""
        now = time.time()
        result = self.con.execute("""
            SELECT realized, unrealized, total_invested, entry_price, first_buy_time
            FROM wallet_token_cache
            WHERE wallet = ? AND token = ? AND last_updated > ?
        """, [wallet, token, now - 1800]).fetchone() # 30 min fresh (adjust to 900 for 15 min)
      
        if result:
            self._log(f"Cache hit for {wallet[:8]}... / {token[:8]}...")
            return {
                'realized': result[0], 'unrealized': result[1], 'total_invested': result[2],
                'entry_price': result[3], 'first_buy_time': result[4]
            }
      
        # Cache miss → fetch from APIs
        self._log(f"Cache miss for {wallet[:8]}... / {token[:8]}... Fetching...")
        pnl = self.get_wallet_pnl_solanatracker(wallet, token)
        first_buy = self.get_first_buy_for_wallet(wallet, token)
      
        if pnl and first_buy:
            data = {
                'realized': pnl.get('realized', 0),
                'unrealized': pnl.get('unrealized', 0),
                'total_invested': pnl.get('total_invested') or pnl.get('totalInvested', 0),
                'entry_price': first_buy.get('price'),
                'first_buy_time': first_buy.get('time')
            }
            # Cache it (INSERT OR REPLACE handles updates)
            self.con.execute("""
                INSERT OR REPLACE INTO wallet_token_cache
                (wallet, token, realized, unrealized, total_invested, entry_price, first_buy_time, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [wallet, token, data['realized'], data['unrealized'],
                  data['total_invested'], data['entry_price'],
                  data['first_buy_time'], now])
            self._log("Cached new data")
            return data
        self._log("Fetch failed - no data")
        return None
 
    def _get_cached_other_runners(self, wallet, current_token=None, min_multiplier=5.0):
        """Cache entire runner history per wallet (exclude current_token if provided)"""
        now = time.time()
        result = self.con.execute("""
            SELECT other_runners, stats
            FROM wallet_runner_cache
            WHERE wallet = ? AND last_updated > ?
        """, [wallet, now - 3600]).fetchone() # 60 min fresh (adjust to 900 for 15 min)
      
        if result:
            import json
            self._log(f"Runner cache hit for {wallet[:8]}...")
            return {'other_runners': json.loads(result[0]), 'stats': json.loads(result[1])}
      
        # Miss → compute from original method
        self._log(f"Runner cache miss for {wallet[:8]}... Computing...")
        runners = self.get_wallet_other_runners(wallet, current_token, min_multiplier) # Call original
        if runners:
            import json
            self.con.execute("""
                INSERT OR REPLACE INTO wallet_runner_cache
                (wallet, other_runners, stats, last_updated)
                VALUES (?, ?, ?, ?)
            """, [wallet, json.dumps(runners['other_runners']), json.dumps(runners['stats']), now])
            self._log("Cached runner history")
            return runners
        return {'other_runners': [], 'stats': {}}
 
    def _get_cached_check_if_runner(self, token, min_multiplier=5.0):
        now = time.time()
        result = self.con.execute("SELECT runner_info FROM token_runner_cache WHERE token = ? AND last_updated > ?", [token, now - 3600]).fetchone()
        if result:
            import json
            return json.loads(result[0])
      
        # Miss
        runner_info = self._check_if_runner(token, min_multiplier) # Original
        if runner_info:
            import json
            self.con.execute("INSERT OR REPLACE INTO token_runner_cache VALUES (?, ?, ?)", [token, json.dumps(runner_info), now])
            return runner_info
        return None
 
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
            self._log(f" ⚠️ Error fetching PnL: {str(e)}")
            return None
    def get_token_ath(self, token_address):
        """Get all-time high price data"""
        try:
            url = f"{self.st_base_url}/tokens/{token_address}/ath"
            data = self.fetch_with_retry(
                url,
                self._get_solanatracker_headers(),
                semaphore=self.solana_tracker_semaphore
            )
            return data
        except Exception as e:
            self._log(f" ⚠️ Error fetching ATH: {str(e)}")
            return None
    def get_wallet_trades_30days(self, wallet_address, limit=100):
        """Get wallet's trades from last 30 days"""
        # Incremental trades: Check last_processed_time
        now = time.time()
        result = self.con.execute("""
            SELECT last_processed_time
            FROM wallet_token_cache
            WHERE wallet = ?
            LIMIT 1
        """, [wallet_address]).fetchone()
       
        last_processed = result[0] if result else (now - (30 * 24 * 60 * 60)) * 1000
       
        try:
            url = f"{self.st_base_url}/wallet/{wallet_address}/trades"
            params = {'limit': limit, 'since_time': last_processed} # Assuming API supports since_time
           
            response = requests.get(url, headers=self._get_solanatracker_headers(), params=params, timeout=30)
         
            if response.status_code == 200:
                data = response.json()
                trades = data.get('trades', [])
               
                # Update last_processed
                if trades:
                    latest_time = max(t.get('time', 0) for t in trades)
                    self.con.execute("""
                        UPDATE wallet_token_cache
                        SET last_processed_time = ?
                        WHERE wallet = ?
                    """, [latest_time, wallet_address])
                    # If no row, insert dummy
                    if self.con.execute("SELECT COUNT(*) FROM wallet_token_cache WHERE wallet = ?", [wallet_address]).fetchone()[0] == 0:
                        self.con.execute("""
                            INSERT INTO wallet_token_cache (wallet, last_processed_time)
                            VALUES (?, ?)
                        """, [wallet_address, latest_time])
               
                return trades
         
            return []
         
        except Exception as e:
            self._log(f" ⚠️ Error getting 30-day trades: {str(e)}")
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
    async def _async_get_first_buy(self, session, wallet, token):
        url = f"{self.st_base_url}/trades/{token}/by-wallet/{wallet}"
        data = await self.async_fetch_with_retry(
            session,
            url,
            self._get_solanatracker_headers(),
            semaphore=self.solana_tracker_async_semaphore
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
    async def _async_fetch_first_buys(self, wallets, token):
        async with aiohttp.ClientSession() as session:
            tasks = [self._async_get_first_buy(session, w, token) for w in wallets]
            return await asyncio.gather(*tasks)
    # =========================================================================
    # TRENDING RUNNER DISCOVERY
    # =========================================================================
    def _get_price_range_in_period(self, token_address, days_back):
        """Get price multiplier for period"""
        try:
            time_to = int(time.time())
            time_from = time_to - (days_back * 86400)
         
            candle_type = '1h' if days_back <= 7 else '4h'
         
            url = f"{self.st_base_url}/chart/{token_address}"
            params = {
                'type': candle_type,
                'time_from': time_from,
                'time_to': time_to,
                'currency': 'usd'
            }
         
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
            self._log(f" ⚠️ Price range error: {str(e)}")
            return None
    def _get_token_detailed_info(self, token_address):
        """Get detailed token information"""
        try:
            url = f"{self.st_base_url}/tokens/{token_address}"
         
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
                'age_days': token_age_days,
                'age': f"{token_age_days:.1f}d" if token_age_days > 0 else 'N/A'
            }
         
        except Exception as e:
            self._log(f" ⚠️ Token info error: {str(e)}")
            return None
    def find_trending_runners_enhanced(self, days_back=7, min_multiplier=5.0, min_liquidity=50000):
        """Enhanced trending runner discovery with caching"""
        cache_key = f"{days_back}_{min_multiplier}_{min_liquidity}"
        now = datetime.now()
     
        # Skip cache for 30d (Auto Discovery always fresh)
        if days_back == 30:
            self._log(f" ⚡ Skipping cache for 30d (one-off autodiscovery)")
        else:
            # Check cache for 7d/14d
            if cache_key in self._trending_cache:
                cache_age = now - self._cache_expiry[cache_key]
                if cache_age < timedelta(minutes=5):
                    self._log(f" ⚡ Cache hit ({cache_key}) - age: {cache_age.seconds}s")
                    return self._trending_cache[cache_key]
     
        self._log(f"\n{'='*80}")
        self._log(f"FINDING TRENDING RUNNERS: {days_back} days, {min_multiplier}x+")
        self._log(f"{'='*80}")
     
        try:
            url = f"{self.st_base_url}/tokens/trending"
            response = self.fetch_with_retry(
                url,
                self._get_solanatracker_headers(),
                semaphore=self.solana_tracker_semaphore
            )
         
            if not response:
                self._log(f" ❌ Failed to fetch trending list")
                return []
         
            trending_data = response if isinstance(response, list) else []
            qualified_runners = []
         
            # Limit to top 20 for faster discovery
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
                        'ticker': token.get('symbol', 'UNKNOWN'),
                        'name': token.get('name', 'Unknown'),
                        'address': mint,
                        'chain': 'solana',
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
                        'age': token_info.get('age', 'N/A'),
                        'pair_address': pool.get('poolId', mint)
                    })
                 
                    time.sleep(0.2)
                 
                except Exception as e:
                    self._log(f" ⚠️ Token skip: {str(e)}")
                    continue
         
            qualified_runners.sort(key=lambda x: x['multiplier'], reverse=True)
         
            # Only cache 7d/14d (not 30d)
            if days_back != 30:
                self._trending_cache[cache_key] = qualified_runners
                self._cache_expiry[cache_key] = now
                self._log(f" ✅ Found {len(qualified_runners)} runners (cached 5 min)")
            else:
                self._log(f" ✅ Found {len(qualified_runners)} runners (no cache - one-off)")
         
            return qualified_runners
         
        except Exception as e:
            self._log(f" ❌ Error finding runners: {str(e)}")
            return []
    def preload_trending_cache(self):
        """Preload trending runners cache and analyze top 5"""
        for days_back in [7, 14, 30]:
            runners = self.find_trending_runners_enhanced(days_back=days_back)
            for runner in runners[:5]:
                self.analyze_token_professional(runner['address'])
    # =========================================================================
    # RELATIVE SCORING (LIKE TOKENANALYZER - NO DAYS TO ATH)
    # =========================================================================
    def calculate_wallet_relative_score(self, wallet_data, max_entry_to_ath, max_realized_roi, max_total_roi):
        """
        ✅ FIXED: Relative scoring like TokenAnalyzer (NO days-to-ATH)
     
        SCORING COMPONENTS (RELATIVE TO BATCH MAX):
        1. Entry-to-ATH (60%) - Relative to max in batch
        2. Realized ROI (30%) - Relative to max in batch
        3. Total ROI (10%) - Relative to max in batch
        """
        try:
            entry_to_ath_multiplier = wallet_data.get('entry_to_ath_multiplier', 0)
            realized_multiplier = wallet_data.get('realized_multiplier', 0)
            total_multiplier = wallet_data.get('total_multiplier', 0)
         
            # Calculate relative scores (0-1 scale)
            if max_entry_to_ath > 0:
                entry_to_ath_score = entry_to_ath_multiplier / max_entry_to_ath
            else:
                entry_to_ath_score = 0.5
         
            if max_realized_roi > 0:
                realized_roi_score = realized_multiplier / max_realized_roi
            else:
                realized_roi_score = 0
         
            if max_total_roi > 0:
                total_roi_score = total_multiplier / max_total_roi
            else:
                total_roi_score = 0
         
            # Combined score: 60% Entry-to-ATH + 30% Realized + 10% Total
            professional_score = (
                0.60 * entry_to_ath_score +
                0.30 * realized_roi_score +
                0.10 * total_roi_score
            ) * 100 # Scale to 0-100
         
            # Grade assignment
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
                'distance_to_ath_pct': round(((wallet_data.get('ath_price', 0) - wallet_data.get('entry_price', 0)) / wallet_data.get('ath_price', 1)) * 100, 2) if wallet_data.get('entry_price') and wallet_data.get('ath_price') else None,
                'realized_multiplier': round(realized_multiplier, 2) if realized_multiplier else None,
                'total_multiplier': round(total_multiplier, 2) if total_multiplier else None,
                'score_breakdown': {
                    'entry_to_ath_score': round(entry_to_ath_score * 100, 2),
                    'realized_roi_score': round(realized_roi_score * 100, 2),
                    'total_roi_score': round(total_roi_score * 100, 2)
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
                    'entry_to_ath_score': 0,
                    'realized_roi_score': 0,
                    'total_roi_score': 0
                }
            }
    # =========================================================================
    # 30-DAY RUNNER HISTORY
    # =========================================================================
    def _check_if_runner(self, token_address, min_multiplier=10.0):
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
    def get_wallet_other_runners(self, wallet_address, current_token_address=None, min_multiplier=10.0):
        """Get other 5x+ runners WITH per-runner distance to ATH stats"""
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
         
            for token_addr in list(token_addresses)[:10]:
                runner_info = self._get_cached_check_if_runner(token_addr, min_multiplier)
             
                if not runner_info:
                    continue
             
                cached = self._get_cached_pnl_and_entry(wallet_address, token_addr)
             
                if not cached:
                    continue
             
                realized = cached['realized']
                invested = cached['total_invested']
             
                if invested <= 0:
                    continue
             
                roi_mult = (realized + invested) / invested
                runner_info['roi_multiplier'] = round(roi_mult, 2)
                runner_info['invested'] = round(invested, 2)
                runner_info['realized'] = round(realized, 2)
             
                if cached['entry_price']:
                    entry_price = cached['entry_price']
                    ath_price = runner_info.get('ath_price', 0)
                 
                    runner_info['entry_price'] = entry_price
                 
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
         
            # Calculate aggregate stats
            stats = {}
         
            if other_runners:
                successful = sum(1 for r in other_runners if r.get('roi_multiplier', 0) > 1)
                stats['success_rate'] = round(successful / len(other_runners) * 100, 1)
             
                roi_values = [r.get('roi_multiplier', 0) for r in other_runners if r.get('roi_multiplier')]
                if roi_values:
                    stats['avg_roi'] = round(sum(roi_values) / len(roi_values), 2)
             
                entry_to_ath_values = [
                    r.get('entry_to_ath_multiplier', 0)
                    for r in other_runners
                    if r.get('entry_to_ath_multiplier')
                ]
                if entry_to_ath_values:
                    stats['avg_entry_to_ath'] = round(sum(entry_to_ath_values) / len(entry_to_ath_values), 2)
             
                distance_pct_values = [
                    r.get('distance_to_ath_pct', 0)
                    for r in other_runners
                    if r.get('distance_to_ath_pct')
                ]
                if distance_pct_values:
                    stats['avg_distance_to_ath_pct'] = round(sum(distance_pct_values) / len(distance_pct_values), 2)
             
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
            self._log(f" ⚠️ Error getting 30-day runners: {str(e)}")
            return {'other_runners': [], 'stats': {}}
    # =========================================================================
    # THE COMPLETE 6-STEP ANALYSIS (TOKENANALYZER APPROACH)
    # =========================================================================
    def analyze_token_professional(self, token_address, token_symbol="UNKNOWN",
                                   min_roi_multiplier=3.0, user_id='default_user'):
        """
        ✅ FIXED: Complete 6-step analysis using TokenAnalyzer's relative scoring
     
        Returns: List of wallets with professional scoring + 30-day dropdown data
        """
        self._log(f"\n{'='*80}")
        self._log(f"6-STEP ANALYSIS: {token_symbol}")
        self._log(f"{'='*80}")
     
        try:
            all_wallets = set()
            wallet_data = {}
         
            # STEP 1: Fetch top traders from Solana Tracker
            self._log("\n[STEP 1] Fetching top traders...")
            url = f"{self.st_base_url}/top-traders/{token_address}"
            data = self.fetch_with_retry(
                url,
                self._get_solanatracker_headers(),
                semaphore=self.solana_tracker_semaphore
            )
         
            if data:
                traders = data if isinstance(data, list) else []
                self._log(f" ✓ Found {len(traders)} top traders")
             
                # ✅ FIX: Fetch first buy for top traders
                for i, trader in enumerate(traders, 1):
                    wallet = trader.get('wallet')
                    if wallet:
                        all_wallets.add(wallet)
                     
                        # ✅ Get first buy timestamp and price
                        cached_data = self._get_cached_pnl_and_entry(wallet, token_address)
                     
                        wallet_data[wallet] = {
                            'source': 'top_traders',
                            'pnl_data': trader,
                            'earliest_entry': cached_data['first_buy_time'] if cached_data else None,
                            'entry_price': cached_data['entry_price'] if cached_data else None
                        }
                     
                        if i % 10 == 0:
                            self._log(f" Processed {i}/{len(traders)} traders...")
                     
                        time.sleep(0.3)
         
            # STEP 2: Fetch first buyers
            self._log("\n[STEP 2] Fetching first buyers...")
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
             
                self._log(f" ✓ Found {len(buyers)} first buyers ({len(new_wallets)} new)")
             
                # Fetch entry prices asynchronously
                results = asyncio.run(self._async_fetch_first_buys(first_buyer_wallets, token_address))
               
                for wallet, first_buy_data in zip(first_buyer_wallets, results):
                    if first_buy_data:
                        wallet_data[wallet]['entry_price'] = first_buy_data['price']
         
            # STEP 3: Fetch Birdeye historical trades
            self._log("\n[STEP 3] Fetching Birdeye trades (30 days)...")
         
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
         
            self._log(f" ✓ Found {len(all_birdeye_trades)} Birdeye trades")
         
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
         
            self._log(f" ✓ Found {len(new_wallets)} new wallets from Birdeye")
         
            if birdeye_wallets:
                results = asyncio.run(self._async_fetch_first_buys(birdeye_wallets, token_address))
               
                for wallet, first_buy_data in zip(birdeye_wallets, results):
                    if first_buy_data:
                        if wallet_data[wallet].get('entry_price') is None:
                            wallet_data[wallet]['entry_price'] = first_buy_data['price']
                        wallet_entry = wallet_data[wallet].get('earliest_entry', float('inf'))
                        if first_buy_data['time'] < wallet_entry:
                            wallet_data[wallet]['earliest_entry'] = first_buy_data['time']
         
            # STEP 4: Fetch recent trades
            self._log("\n[STEP 4] Fetching recent trades...")
         
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
             
                self._log(f" ✓ Found {len(recent_wallets)} recent traders ({len(new_wallets)} new)")
         
            # STEP 5: Fetch PnL and filter
            self._log(f"\n[STEP 5] Fetching PnL for {len(all_wallets)} wallets...")
         
            wallets_with_pnl = []
            wallets_to_fetch = []
         
            for wallet in all_wallets:
                if wallet_data[wallet].get('pnl_data'):
                    wallets_with_pnl.append(wallet)
                else:
                    wallets_to_fetch.append(wallet)
         
            self._log(f" ✓ {len(wallets_with_pnl)} wallets already have PnL")
            self._log(f" → Fetching PnL for {len(wallets_to_fetch)} remaining...")
         
            qualified_wallets = []
         
            # Process existing PnL
            for wallet in wallets_with_pnl:
                pnl_data = wallet_data[wallet]['pnl_data']
                self._process_wallet_pnl(wallet, pnl_data, wallet_data, qualified_wallets, min_roi_multiplier)
         
            # Fetch and process remaining PnL asynchronously
            async def _async_fetch_pnls():
                async with aiohttp.ClientSession() as session:
                    tasks = []
                    for wallet in wallets_to_fetch:
                        async def fetch_pnl(wallet=wallet):
                            return await self.async_fetch_with_retry(
                                session,
                                f"{self.st_base_url}/pnl/{wallet}/{token_address}",
                                self._get_solanatracker_headers(),
                                semaphore=self.pnl_async_semaphore
                            )
                        tasks.append(fetch_pnl())
                    return await asyncio.gather(*tasks)
            
            results = asyncio.run(_async_fetch_pnls())
           
            for wallet, pnl_data in zip(wallets_to_fetch, results):
                if pnl_data:
                    wallet_data[wallet]['pnl_data'] = pnl_data
                    self._process_wallet_pnl(wallet, pnl_data, wallet_data, qualified_wallets, min_roi_multiplier)
         
            self._log(f" ✓ Found {len(qualified_wallets)} qualified wallets")
         
            # STEP 6: Rank by RELATIVE score (like TokenAnalyzer)
            self._log("\n[STEP 6] Ranking by relative score...")
         
            ath_data = self.get_token_ath(token_address)
            ath_price = ath_data.get('highest_price', 0) if ath_data else 0
         
            # ✅ Calculate max values for relative scoring
            max_entry_to_ath = 0
            max_realized_roi = 0
            max_total_roi = 0
         
            for wallet_info in qualified_wallets:
                entry_price = wallet_info.get('entry_price')
             
                if entry_price and ath_price and entry_price > 0:
                    entry_to_ath_mult = ath_price / entry_price
                    wallet_info['entry_to_ath_multiplier'] = entry_to_ath_mult
                    wallet_info['ath_price'] = ath_price
                 
                    if entry_to_ath_mult > max_entry_to_ath:
                        max_entry_to_ath = entry_to_ath_mult
                else:
                    wallet_info['entry_to_ath_multiplier'] = 0
             
                if wallet_info['realized_multiplier'] > max_realized_roi:
                    max_realized_roi = wallet_info['realized_multiplier']
             
                if wallet_info['total_multiplier'] > max_total_roi:
                    max_total_roi = wallet_info['total_multiplier']
         
            self._log(f" Max Entry-to-ATH: {max_entry_to_ath:.2f}x")
            self._log(f" Max Realized ROI: {max_realized_roi:.2f}x")
            self._log(f" Max Total ROI: {max_total_roi:.2f}x")
         
            wallet_results = []
         
            for wallet_info in qualified_wallets:
                wallet_address = wallet_info['wallet']
             
                # ✅ Get 30-day runner history (ALWAYS)
                runner_history = self._get_cached_other_runners(wallet_address, current_token=token_address, min_multiplier=10.0)
             
                # ✅ Calculate RELATIVE score
                scoring_data = self.calculate_wallet_relative_score(
                    wallet_info,
                    max_entry_to_ath,
                    max_realized_roi,
                    max_total_roi
                )
             
                wallet_results.append({
                    'wallet': wallet_address,
                    'source': wallet_info['source'],
                    'roi_percent': round((wallet_info['realized_multiplier'] - 1) * 100, 2),
                    'roi_multiplier': round(wallet_info['realized_multiplier'], 2),
                    'entry_to_ath_multiplier': scoring_data.get('entry_to_ath_multiplier'),
                    'distance_to_ath_pct': scoring_data.get('distance_to_ath_pct'),
                    'realized_profit': wallet_info['realized'],
                    'unrealized_profit': wallet_info['unrealized'],
                    'total_invested': wallet_info['total_invested'],
                    'cost_basis': wallet_info.get('cost_basis', 0),
                    'realized_multiplier': scoring_data.get('realized_multiplier'),
                    'total_multiplier': scoring_data.get('total_multiplier'),
                 
                    # Professional scoring
                    'professional_score': scoring_data['professional_score'],
                    'professional_grade': scoring_data['professional_grade'],
                    'score_breakdown': scoring_data['score_breakdown'],
                 
                    # ✅ 30-day runner history (ALWAYS PRESENT)
                    'runner_hits_30d': runner_history['stats'].get('total_other_runners', 0),
                    'runner_success_rate': runner_history['stats'].get('success_rate', 0),
                    'runner_avg_roi': runner_history['stats'].get('avg_roi', 0),
                    'other_runners': runner_history['other_runners'][:5],
                    'other_runners_stats': runner_history['stats'],
                 
                    # Timing data
                    'first_buy_time': wallet_info.get('earliest_entry'),
                    'entry_price': wallet_info.get('entry_price'),
                 
                    'is_fresh': True
                })
         
            # ✅ Rank by professional score
            wallet_results.sort(key=lambda x: x['professional_score'], reverse=True)
         
            self._log(f" ✅ Analysis complete: {len(wallet_results)} qualified wallets")
            if wallet_results:
                self._log(f" Top score: {wallet_results[0]['professional_score']} ({wallet_results[0]['professional_grade']})")
         
            return wallet_results
         
        finally:
            pass
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
        """Batch analysis across multiple runners with consistency tracking"""
        self._log(f"\n{'='*80}")
        self._log(f"BATCH ANALYSIS: {len(runners_list)} runners")
        self._log(f"{'='*80}")
     
        wallet_hits = defaultdict(lambda: {
            'wallet': None,
            'runners_hit': [],
            'runners_hit_addresses': set(),
            'roi_details': [],
            'professional_scores': [],
            'entry_to_ath_multipliers': []
        })
     
        for idx, runner in enumerate(runners_list, 1):
            self._log(f"\n [{idx}/{len(runners_list)}] Analyzing {runner.get('symbol', 'UNKNOWN')}")
         
            wallets = self.analyze_token_professional(
                token_address=runner['address'],
                token_symbol=runner.get('symbol', 'UNKNOWN'),
                min_roi_multiplier=min_roi_multiplier,
                user_id=user_id
            )
         
            for wallet in wallets:
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
                    'entry_to_ath_multiplier': wallet.get('entry_to_ath_multiplier')
                })
             
                wallet_hits[wallet_addr]['professional_scores'].append(wallet['professional_score'])
                if wallet.get('entry_to_ath_multiplier'):
                    wallet_hits[wallet_addr]['entry_to_ath_multipliers'].append(wallet['entry_to_ath_multiplier'])
     
        smart_money = []
        no_overlap_fallback = False
     
        for wallet_addr, data in wallet_hits.items():
            if len(data['runners_hit']) < min_runner_hits:
                continue
         
            avg_professional_score = sum(data['professional_scores']) / len(data['professional_scores'])
            avg_roi = sum(r['roi_percent'] for r in data['roi_details']) / len(data['roi_details'])
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
         
            full_history = self._get_cached_other_runners(wallet_addr, min_multiplier=10.0)
         
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
     
        # ✅ NEW: Fallback if no overlap found
        if len(smart_money) == 0:
            self._log(f"\n ⚠️ No cross-token overlap - showing all wallets ranked individually")
            no_overlap_fallback = True
         
            for wallet_addr, data in wallet_hits.items():
                total_invested = sum(p.get('invested', 0) for p in data['performances'])
                if total_invested < 100: continue
                
                # Include ALL wallets regardless of token count
                avg_professional_score = sum(data['professional_scores']) / len(data['professional_scores'])
                avg_roi = sum(r['roi_percent'] for r in data['roi_details']) / len(data['roi_details'])
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
             
                full_history = self._get_cached_other_runners(wallet_addr, min_multiplier=5.0)
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
                    'avg_entry_to_ath_multiplier': round(avg_entry_to_ath, 2) if avg_entry_to_ath else None,
                    'variance': round(variance, 2),
                    'consistency_grade': consistency_grade,
                    'roi_details': data['roi_details'][:5],
                    'total_runners_30d': len(data['runners_hit']) + len(outside_batch_runners),
                    'in_batch_count': len(data['runners_hit']),
                    'outside_batch_count': len(outside_batch_runners),
                    'outside_batch_runners': outside_batch_runners[:5],
                    'full_30d_stats': full_history['stats'],
                    'is_fresh': True,
                    'no_overlap_fallback': True # Flag for frontend
                })
         
            # Sort by individual score instead of overlap count
            smart_money.sort(key=lambda x: x['avg_professional_score'], reverse=True)
        else:
            # Normal overlap sorting
            smart_money.sort(
                key=lambda x: (x['runner_count'], x['avg_professional_score'], -x['variance']),
                reverse=True
            )
     
        self._log(f"\n ✅ Found {len(smart_money)} {'individual' if no_overlap_fallback else 'consistent smart money'} wallets")
     
        return smart_money
    def batch_analyze_tokens(self, tokens, min_roi_multiplier=3.0, user_id='default_user'):
        wallet_hits = defaultdict(lambda: {
            'wallet': None,
            'tokens_hit': [], # Which tokens they appeared in
            'token_addresses': set(), # Track token addresses
            'performances': [], # All their performances
            'entry_to_ath_values': [], # All entry-to-ATH multipliers
            'realized_roi_values': [], # All realized ROI values
            'professional_scores': [] # All professional scores
        })
       
        # ✅ STEP 2: Analyze each token and track wallets
        for idx, token in enumerate(tokens, 1):
            print(f"\n[{idx}/{len(tokens)}] ANALYZING: {token['ticker']}")
           
            # Run 6-step analysis on this token
            wallets = self.analyze_token_professional(
                token_address=token['address'],
                token_symbol=token.get('ticker', 'UNKNOWN'),
                min_roi_multiplier=min_roi_multiplier,
                user_id=user_id
            )
           
            # ✅ STEP 3: Track each wallet's appearance
            for wallet in wallets: # Top 50 per token
                addr = wallet['wallet']
               
                # Initialize wallet if first time seeing it
                if wallet_hits[addr]['wallet'] is None:
                    wallet_hits[addr]['wallet'] = addr
               
                # ✅ Track token appearance (if not already counted)
                if token['ticker'] not in wallet_hits[addr]['tokens_hit']:
                    wallet_hits[addr]['tokens_hit'].append(token['ticker'])
                    wallet_hits[addr]['token_addresses'].add(token['address'])
               
                # ✅ Store this performance
                wallet_hits[addr]['performances'].append({
                    'token': token['ticker'],
                    'token_address': token['address'],
                    'professional_score': wallet['professional_score'],
                    'entry_to_ath_multiplier': wallet.get('entry_to_ath_multiplier'),
                    'realized_roi': wallet['roi_multiplier'],
                    'total_roi': wallet.get('total_multiplier'),
                    'invested': wallet.get('total_invested', 0),
                    'realized': wallet.get('realized_profit', 0)
                })
               
                # ✅ Track values for averaging
                wallet_hits[addr]['professional_scores'].append(wallet['professional_score'])
                if wallet.get('entry_to_ath_multiplier'):
                    wallet_hits[addr]['entry_to_ath_values'].append(wallet['entry_to_ath_multiplier'])
                wallet_hits[addr]['realized_roi_values'].append(wallet['roi_multiplier'])
       
        # ✅ STEP 4: Calculate aggregates and build ranked list
        ranked_wallets = []
       
        for addr, data in wallet_hits.items():
            token_count = len(data['tokens_hit'])
           
            # Calculate averages
            avg_professional_score = sum(data['professional_scores']) / len(data['professional_scores']) if data['professional_scores'] else 0
            avg_entry_to_ath = sum(data['entry_to_ath_values']) / len(data['entry_to_ath_values']) if data['entry_to_ath_values'] else None
            avg_realized_roi = sum(data['realized_roi_values']) / len(data['realized_roi_values']) if data['realized_roi_values'] else 0
           
            # Calculate consistency (variance in scores)
            if len(data['professional_scores']) > 1:
                variance = statistics.variance(data['professional_scores'])
            else:
                variance = 0
           
            # Assign consistency grade
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
           
            # Get 30-day runner history (from first performance)
            first_perf = data['performances'][0]
            runner_hits_30d = first_perf.get('runner_hits_30d', 0) if 'runner_hits_30d' in str(first_perf) else 0
           
            ranked_wallets.append({
                'wallet': addr,
                'token_count': token_count, # ✅ PRIMARY RANK
                'tokens_hit': data['tokens_hit'], # Which tokens
                'avg_professional_score': round(avg_professional_score, 2),
                'avg_entry_to_ath_multiplier': round(avg_entry_to_ath, 2) if avg_entry_to_ath else None,
                'avg_realized_roi': round(avg_realized_roi, 2),
                'consistency_grade': consistency_grade,
                'variance': round(variance, 2),
                'performances': data['performances'][:5], # Top 5 performances
                'professional_grade': 'A+' if avg_professional_score >= 90 else 'A' if avg_professional_score >= 85 else 'B',
                'runner_hits_30d': runner_hits_30d,
                'is_fresh': True
            })
       
        # ✅ STEP 5: Check for overlap, fallback if needed
        no_overlap_fallback = False
        if len(ranked_wallets) == 0:
            # No overlap - return all wallets ranked individually
            print("\n⚠️ No cross-token overlap - showing all wallets ranked individually")
            no_overlap_fallback = True
           
            for addr, data in wallet_hits.items():
                total_invested = sum(p.get('invested', 0) for p in data['performances'])
                if total_invested < 100:continue
                token_count = len(data['tokens_hit'])
               
                avg_professional_score = sum(data['professional_scores']) / len(data['professional_scores']) if data['professional_scores'] else 0
                avg_entry_to_ath = sum(data['entry_to_ath_values']) / len(data['entry_to_ath_values']) if data['entry_to_ath_values'] else None
                avg_realized_roi = sum(data['realized_roi_values']) / len(data['realized_roi_values']) if data['realized_roi_values'] else 0
               
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
               
                first_perf = data['performances'][0] if data['performances'] else {}
                runner_hits_30d = first_perf.get('runner_hits_30d', 0) if 'runner_hits_30d' in str(first_perf) else 0
               
                ranked_wallets.append({
                    'wallet': addr,
                    'token_count': token_count,
                    'tokens_hit': data['tokens_hit'],
                    'avg_professional_score': round(avg_professional_score, 2),
                    'avg_entry_to_ath_multiplier': round(avg_entry_to_ath, 2) if avg_entry_to_ath else None,
                    'avg_realized_roi': round(avg_realized_roi, 2),
                    'consistency_grade': consistency_grade,
                    'variance': round(variance, 2),
                    'performances': data['performances'][:5],
                    'professional_grade': 'A+' if avg_professional_score >= 90 else 'A' if avg_professional_score >= 85 else 'B',
                    'runner_hits_30d': runner_hits_30d,
                    'is_fresh': True,
                    'no_overlap_fallback': True # Flag for frontend
                })
           
            # Sort by individual score
            ranked_wallets.sort(key=lambda x: x['avg_professional_score'], reverse=True)
        else:
            # Normal overlap sorting
            ranked_wallets.sort(
                key=lambda x: (
                    x['token_count'],
                    x['avg_professional_score'],
                    -x['variance']
                ),
                reverse=True
            )
        # ✅ STEP 6: Top 20 only
        top_wallets = ranked_wallets[:20]
        return top_wallets
    # =========================================================================
    # REPLACEMENT FINDER METHODS
    # =========================================================================
    def find_replacement_wallets(self, declining_wallet_address, user_id='default_user',
                                 min_professional_score=85, max_results=3):
        """Find replacement wallets for a degrading wallet"""
     
        print(f"\n{'='*80}")
        print(f"FINDING REPLACEMENTS FOR: {declining_wallet_address[:8]}...")
        print(f"{'='*80}")
     
        declining_profile = self._get_wallet_profile_from_watchlist(
            user_id,
            declining_wallet_address
        )
     
        if not declining_profile:
            print(f" ⚠️ Wallet not found in watchlist")
            return []
     
        print(f" Profile: {declining_profile['tier']} tier, "
              f"{len(declining_profile['tokens_traded'])} tokens traded")
     
        print(f"\n [1/3] Discovering recent runners...")
        runners = self.find_trending_runners_enhanced(
            days_back=30,
            min_multiplier=5.0,
            min_liquidity=50000
        )
     
        if not runners:
            print(f" ⚠️ No runners found")
            return []
     
        print(f" ✓ Found {len(runners)} runners")
     
        print(f"\n [2/3] Analyzing top runners for candidates...")
     
        all_candidates = []
        tokens_to_check = runners[:10]
     
        for runner in tokens_to_check:
            wallets = self.analyze_token_professional(
                token_address=runner['address'],
                token_symbol=runner['symbol'],
                min_roi_multiplier=3.0,
                user_id=user_id
            )
         
            qualified = [
                w for w in wallets
                if w['professional_score'] >= min_professional_score
                and w.get('is_fresh', True)
            ]
         
            all_candidates.extend(qualified)
     
        print(f" ✓ Found {len(all_candidates)} candidate wallets")
     
        print(f"\n [3/3] Scoring candidates by similarity...")
     
        scored_candidates = []
     
        for candidate in all_candidates:
            similarity = self._calculate_similarity_score(
                declining_profile,
                candidate
            )
         
            if similarity['total_score'] > 0.3:
                scored_candidates.append({
                    **candidate,
                    'similarity_score': similarity['total_score'],
                    'similarity_breakdown': similarity['breakdown'],
                    'why_better': self._explain_why_better(declining_profile, candidate)
                })
     
        scored_candidates.sort(
            key=lambda x: (
                x['similarity_score'] * 0.6 +
                (x['professional_score'] / 100) * 0.4
            ),
            reverse=True
        )
     
        top_matches = scored_candidates[:max_results]
     
        print(f"\n ✅ Top {len(top_matches)} replacements found:")
        for i, match in enumerate(top_matches, 1):
            print(f" {i}. {match['wallet'][:8]}... "
                  f"(Score: {match['professional_score']}, "
                  f"Similarity: {match['similarity_score']:.1%})")
     
        return top_matches
    def _get_wallet_profile_from_watchlist(self, user_id, wallet_address):
        """Get wallet's historical profile from watchlist database"""
        try:
            from db.watchlist_db import WatchlistDatabase
         
            db = WatchlistDatabase()
            watchlist = db.get_wallet_watchlist(user_id)
         
            wallet_data = next(
                (w for w in watchlist if w['wallet_address'] == wallet_address),
                None
            )
         
            if not wallet_data:
                return None
         
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
            print(f" ⚠️ Error loading wallet profile: {e}")
            return None
    def _calculate_similarity_score(self, declining_profile, candidate):
        """Calculate how similar a candidate is to the declining wallet"""
     
        # 1. TOKEN OVERLAP (40% weight)
        declining_tokens = set(declining_profile['tokens_traded'])
     
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
            token_score = 0.5
     
        # 2. TIER MATCH (30% weight)
        tier_values = {'S': 4, 'A': 3, 'B': 2, 'C': 1}
     
        declining_tier_value = tier_values.get(declining_profile['tier'], 1)
     
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
     
        if candidate_tier_value >= declining_tier_value:
            tier_score = 1.0
        elif candidate_tier_value == declining_tier_value - 1:
            tier_score = 0.7
        else:
            tier_score = 0.3
     
        # 3. ACTIVITY LEVEL (20% weight)
        declining_activity = declining_profile.get('pump_count', 0)
        candidate_activity = candidate.get('runner_hits_30d', 0)
     
        if declining_activity > 0:
            activity_ratio = min(candidate_activity / declining_activity, 2.0)
            activity_score = activity_ratio / 2.0
        else:
            activity_score = 1.0 if candidate_activity > 0 else 0.5
     
        # 4. CONSISTENCY (10% weight)
        candidate_consistency = candidate.get('consistency_grade', 'C')
     
        consistency_values = {
            'A+': 1.0, 'A': 0.9, 'B': 0.7, 'C': 0.5, 'D': 0.3
        }
        consistency_score = consistency_values.get(candidate_consistency, 0.5)
     
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
        """Generate human-readable reasons why candidate is better"""
        reasons = []
     
        declining_score = declining_profile.get('professional_score', 0)
        candidate_score = candidate.get('professional_score', 0)
     
        if candidate_score > declining_score:
            diff = candidate_score - declining_score
            reasons.append(f"Professional score +{diff:.0f} points higher")
     
        declining_runners = declining_profile.get('pump_count', 0)
        candidate_runners = candidate.get('runner_hits_30d', 0)
     
        if candidate_runners > declining_runners:
            reasons.append(
                f"{candidate_runners} runners last 30d "
                f"(vs {declining_runners} for old wallet)"
            )
     
        declining_roi = declining_profile.get('avg_roi', 0)
        candidate_roi = candidate.get('roi_multiplier', 0) * 100
     
        if candidate_roi > declining_roi:
            diff = candidate_roi - declining_roi
            reasons.append(f"+{diff:.0f}% better ROI")
     
        if candidate.get('runner_hits_30d', 0) > 0:
            reasons.append("Currently active (recent runner hits)")
     
        candidate_grade = candidate.get('professional_grade', 'C')
        if candidate_grade in ['A+', 'A', 'A-'] and declining_profile['tier'] not in ['S', 'A']:
            reasons.append("Tier upgrade to S/A-tier")
     
        if candidate.get('consistency_grade') in ['A+', 'A']:
            reasons.append(f"High consistency ({candidate['consistency_grade']})")
     
        return reasons