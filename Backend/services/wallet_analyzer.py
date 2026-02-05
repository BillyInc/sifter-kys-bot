import requests
from datetime import datetime
from collections import defaultdict
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore

class WalletPumpAnalyzer:
    """
    PROFESSIONAL WALLET ANALYZER with COMPLETE 6-Step Analysis
    
    THE 6 STEPS (from Document 6):
    1. Fetch top traders from Solana Tracker + first buy timestamps
    2. Fetch first buyers from Solana Tracker + entry prices
    3. Fetch Birdeye historical trades (30 days back)
    4. Fetch recent Solana Tracker trades
    5. Fetch PnL for ALL wallets, filter for ≥3x ROI AND ≥$100 invested
    6. Rank by professional score (60% timing, 30% profit, 10% overall)
    
    Additional Features:
    - 30-day runner history tracking with verification
    - Cross-runner consistency grading
    - Batch analysis with variance tracking
    - Professional scoring (60/30/10)
    
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
        """Get all-time high price data"""
        try:
            url = f"{self.st_base_url}/tokens/{token_address}/ath"
            response = requests.get(url, headers=self._get_solanatracker_headers(), timeout=15)
            
            if response.status_code != 200:
                return None
            
            return response.json()
            
        except Exception as e:
            self._log(f"  ⚠️ Error fetching ATH: {str(e)}")
            return None

    def get_wallet_trades_30days(self, wallet_address, limit=100):
        """Get wallet's trades from last 30 days"""
        try:
            url = f"{self.st_base_url}/wallet/{wallet_address}/trades"
            params = {'limit': limit}
            
            response = requests.get(url, headers=self._get_solanatracker_headers(), timeout=10)
            
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
            
            response = requests.get(url, headers=self._get_solanatracker_headers(), params=params, timeout=15)
            
            if response.status_code != 200:
                return None
            
            data = response.json()
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
            return None

    def _get_token_detailed_info(self, token_address):
        """Get detailed token information"""
        try:
            url = f"{self.st_base_url}/tokens/{token_address}"
            response = requests.get(url, headers=self._get_solanatracker_headers(), timeout=10)
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            pools = data.get('pools', [])
            if not pools:
                return None
            
            primary_pool = max(pools, key=lambda p: p.get('liquidity', {}).get('usd', 0))
            
            return {
                'symbol': data.get('symbol', 'UNKNOWN'),
                'name': data.get('name', 'Unknown'),
                'address': token_address,
                'liquidity': primary_pool.get('liquidity', {}).get('usd', 0),
                'volume_24h': primary_pool.get('txns', {}).get('volume24h', 0),
                'price': primary_pool.get('price', {}).get('usd', 0),
                'holders': data.get('holders', 0)
            }
            
        except Exception as e:
            return None

    def find_trending_runners_enhanced(self, days_back=7, min_multiplier=5.0, min_liquidity=50000):
        """Enhanced trending runner discovery"""
        self._log(f"\n{'='*80}")
        self._log(f"FINDING TRENDING RUNNERS: {days_back} days, {min_multiplier}x+")
        self._log(f"{'='*80}")
        
        try:
            timeframe_map = {7: '24h', 14: '24h', 30: '24h', 1: '24h'}
            st_timeframe = timeframe_map.get(days_back, '24h')
            
            url = f"{self.st_base_url}/tokens/trending/{st_timeframe}"
            response = requests.get(url, headers=self._get_solanatracker_headers(), timeout=10)
            
            if response.status_code != 200:
                return []
            
            trending_data = response.json()
            qualified_runners = []
            
            for item in trending_data[:100]:
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
                    
                    creation_time = token.get('creation', {}).get('created_time', 0)
                    token_age_days = 0
                    if creation_time > 0:
                        token_age_days = (time.time() - creation_time) / 86400
                    
                    qualified_runners.append({
                        'symbol': token.get('symbol', 'UNKNOWN'),
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
                        'pair_address': pool.get('poolId', mint)
                    })
                    
                except Exception as e:
                    continue
            
            qualified_runners.sort(key=lambda x: x['multiplier'], reverse=True)
            
            self._log(f"  ✅ Found {len(qualified_runners)} runners")
            
            return qualified_runners
            
        except Exception as e:
            self._log(f"  ❌ Error finding runners: {str(e)}")
            return []

    # =========================================================================
    # PROFESSIONAL SCORING (60/30/10)
    # =========================================================================

    def calculate_wallet_professional_score(self, wallet_data, ath_price, ath_time=None):
        """Professional scoring: 60% timing, 30% profit, 10% overall"""
        try:
            entry_price = wallet_data.get('entry_price')
            realized_multiplier = wallet_data.get('realized_multiplier', 0)
            total_multiplier = wallet_data.get('total_multiplier', 0)
            first_buy_time = wallet_data.get('first_buy_time')
            
            # Calculate Entry-to-ATH multiplier
            entry_to_ath_multiplier = None
            if entry_price and ath_price and ath_price > 0 and entry_price > 0:
                entry_to_ath_multiplier = ath_price / entry_price
            
            # 1. TIMING SCORE (60%)
            timing_score = 0
            if entry_to_ath_multiplier:
                timing_score = min(100, entry_to_ath_multiplier * 20)
            elif first_buy_time and ath_time:
                buy_time_sec = first_buy_time / 1000 if first_buy_time > 1000000000000 else first_buy_time
                seconds_before_ath = ath_time - buy_time_sec
                days_before_ath = seconds_before_ath / 86400
                
                if days_before_ath > 0:
                    timing_score = min(100, (days_before_ath / 30) * 100)
                else:
                    timing_score = 50
            else:
                timing_score = 50
            
            # 2. PROFIT SCORE (30%)
            profit_score = 0
            if realized_multiplier > 0:
                profit_score = min(100, (realized_multiplier - 1) * 20)
            
            # 3. OVERALL SCORE (10%)
            overall_score = 0
            if total_multiplier > 0:
                overall_score = min(100, (total_multiplier - 1) * 10)
            
            professional_score = (
                timing_score * 0.60 +
                profit_score * 0.30 +
                overall_score * 0.10
            )
            
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
                'score_breakdown': {
                    'timing_score': round(timing_score, 2),
                    'profit_score': round(profit_score, 2),
                    'overall_score': round(overall_score, 2)
                }
            }
            
        except Exception as e:
            return {
                'professional_score': 0,
                'professional_grade': 'F',
                'entry_to_ath_multiplier': None,
                'score_breakdown': {'timing_score': 0, 'profit_score': 0, 'overall_score': 0}
            }

    # =========================================================================
    # 30-DAY RUNNER HISTORY (THE DROPDOWN FEATURE)
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
        Get other 5x+ runners a wallet has traded in last 30 days
        Powers the DROPDOWN feature
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
                runner_info = self._check_if_runner(token_addr, min_multiplier)
                
                if runner_info:
                    pnl_data = self.get_wallet_pnl_solanatracker(wallet_address, token_addr)
                    
                    if pnl_data:
                        realized = pnl_data.get('realized', 0)
                        invested = pnl_data.get('total_invested', 0)
                        
                        if invested > 0:
                            roi_mult = (realized + invested) / invested
                            runner_info['roi_multiplier'] = round(roi_mult, 2)
                            runner_info['invested'] = round(invested, 2)
                            runner_info['realized'] = round(realized, 2)
                        
                        other_runners.append(runner_info)
            
            stats = {}
            if other_runners:
                successful = sum(1 for r in other_runners if r.get('roi_multiplier', 0) > 1)
                stats['success_rate'] = round(successful / len(other_runners) * 100, 1)
                
                roi_values = [r.get('roi_multiplier', 0) for r in other_runners if r.get('roi_multiplier')]
                if roi_values:
                    stats['avg_roi'] = round(sum(roi_values) / len(roi_values), 2)
                
                stats['total_other_runners'] = len(other_runners)
            
            return {
                'other_runners': other_runners,
                'stats': stats
            }
            
        except Exception as e:
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
                
                # Get 30-day runner history (THE DROPDOWN)
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
                    'realized_profit': wallet_info['realized'],
                    'unrealized_profit': wallet_info['unrealized'],
                    'total_invested': wallet_info['total_invested'],
                    'cost_basis': wallet_info.get('cost_basis', 0),
                    
                    # Professional scoring
                    'professional_score': professional_score_data['professional_score'],
                    'professional_grade': professional_score_data['professional_grade'],
                    'score_breakdown': professional_score_data['score_breakdown'],
                    
                    # 30-day runner history (DROPDOWN DATA)
                    'runner_hits_30d': runner_history['stats'].get('total_other_runners', 0),
                    'runner_success_rate': runner_history['stats'].get('success_rate', 0),
                    'runner_avg_roi': runner_history['stats'].get('avg_roi', 0),
                    'other_runners': runner_history['other_runners'][:5],
                    
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