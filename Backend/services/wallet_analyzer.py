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
import json
import redis as redis_lib
import os
import random
from utils import _roi_to_score

# ============================================================
# CACHE TTL CONSTANTS
# ============================================================
CACHE_TTL_PNL         = 21600   # 6 hours
CACHE_TTL_RUNNERS     = 43200   # 12 hours
CACHE_TTL_TOKEN_INFO  = 86400   # 24 hours
CACHE_TTL_LAUNCH      = 86400   # 24 hours
CACHE_TTL_TRENDING    = 600     # 10 min
CACHE_TTL_QUAL        = 43200   # 12 h — slot held in leaderboard
CACHE_TTL_QUAL_NEG    = 3600    # 1 h  — failed tokens suppressed
MAX_RUNNERS           = 100      # leaderboard capacity

REDIS_TTL_PNL         = CACHE_TTL_PNL + 3600
REDIS_TTL_RUNNERS     = CACHE_TTL_RUNNERS + 3600
REDIS_TTL_TOKEN_INFO  = CACHE_TTL_TOKEN_INFO + 3600
REDIS_TTL_LAUNCH      = CACHE_TTL_LAUNCH + 3600
REDIS_TTL_TRENDING    = CACHE_TTL_TRENDING + 300


class WalletPumpAnalyzer:
    """
    HYBRID CACHE WALLET ANALYZER
    Redis = Hot cache (fast reads, all workers write)
    DuckDB = Cold storage (persistent, flushed from Redis every hour via Celery)

    WALLET SOURCES (3):
      1. top_traders   — wallets ranked by realized PnL (active traders, exited positions)
      2. first_buyers  — wallets that entered earliest by time
      3. top_holders   — wallets holding the largest current positions
                         Catches conviction holders (no/partial sells) invisible to top_traders.
                         Qualifies via total_multiplier (realized + unrealized >= 3x).

    SCORING (log-scale via _roi_to_score, ceiling=1000 throughout):
      Single token:  60% entry_to_ath_multiplier | 30% total_multiplier | 10% realized_multiplier
      Batch cross-token:    60% avg entry_to_ath_multiplier | 30% avg total ROI | 10% entry consistency
      Batch single-token:   individual professional_score (same as single token mode)

      Percentages (distance_to_ath_pct, avg_distance_to_ath_pct) are display-only and
      never feed into any score calculation.

    TRENDING LEADERBOARD:
      Tokens qualify by pumping >= min_multiplier within window.
      Leaderboard ranked by MULTIPLIER (static) until Live button refreshes.
      Live button refreshes market data AND re-ranks by MOMENTUM SCORE:
        - Volume surge (40%)
        - Price momentum (30%)
        - Holder growth (20%)
        - Liquidity depth (10%)
        - Multiplier provides up to 20% bonus
      Tokens that pump again get their 7-day window extended.
    """
    def __init__(self, solanatracker_api_key, birdeye_api_key=None, debug_mode=True, read_only=False):
        self.solanatracker_key = solanatracker_api_key.strip()
        # birdeye_api_key retained for future premium access — not used in analysis
        self.birdeye_key       = birdeye_api_key or ""
        self.st_base_url       = "https://data.solanatracker.io"
        self.birdeye_base_url  = "https://public-api.birdeye.so"
        self.debug_mode        = debug_mode
        self.read_only         = read_only
        self.duckdb_path       = 'wallet_analytics.duckdb'

        self.worker_mode = os.environ.get('WORKER_MODE') == 'true'

        self.con = None
        if not self.worker_mode:
            try:
                if read_only:
                    self.con = duckdb.connect(self.duckdb_path, read_only=True)
                    self._log("DuckDB opened in READ-ONLY mode")
                else:
                    self.con = duckdb.connect(self.duckdb_path)
                    self._log("DuckDB opened in READ-WRITE mode")
            except Exception as e:
                self._log(f"DuckDB connection failed (continuing with Redis only): {e}")
        else:
            self._log("Worker mode: DuckDB disabled, using Redis only")

        self._redis = self._init_redis()

        self.max_workers = 8
        self.solana_tracker_semaphore       = Semaphore(1)
        self.pnl_semaphore                  = Semaphore(1)
        # FIX: Reduced async semaphores from 1 to match safe concurrency levels.
        # With multiple concurrent workers, even AsyncSemaphore(2) can mean 10+ simultaneous
        # requests to SolanaTracker, which triggers rate limiting.
        self.solana_tracker_async_semaphore = AsyncSemaphore(1)
        self.pnl_async_semaphore            = AsyncSemaphore(1)
        self.executor = None

        self._trending_cache = {}
        self._cache_expiry   = {}

        if self.con and not read_only and not self.worker_mode:
            self._init_db()

        self._log(
            f"Initialized (read_only={read_only}, worker_mode={self.worker_mode}) | "
            f"Redis: {'✅' if self._redis else '❌ fallback to DuckDB'}"
        )

    # =========================================================================
    # REDIS INIT + HELPERS
    # =========================================================================

    def _init_redis(self):
        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        try:
            r = redis_lib.from_url(redis_url, decode_responses=True, socket_timeout=3)
            r.ping()
            self._log(f"Redis connected ✅")
            return r
        except Exception as e:
            self._log(f"Redis connection failed: {e} — falling back to DuckDB only")
            return None

    def _redis_get(self, key):
        if not self._redis:
            return None
        try:
            raw = self._redis.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            self._log(f"Redis GET error ({key}): {e}")
            return None

    def _redis_set(self, key, value, ttl):
        if not self._redis:
            return
        try:
            self._redis.setex(key, ttl, json.dumps(value))
        except Exception as e:
            self._log(f"Redis SET error ({key}): {e}")

    def _redis_delete(self, key):
        if not self._redis:
            return
        try:
            self._redis.delete(key)
        except Exception as e:
            self._log(f"Redis DEL error ({key}): {e}")

    # =========================================================================
    # HYBRID CACHE CORE
    # =========================================================================

    def _get_from_cache(self, redis_key, duckdb_query, duckdb_params):
        data = self._redis_get(redis_key)
        if data is not None:
            return data, 'redis'
        if not self.con or self.worker_mode:
            return None, None
        try:
            result = self.con.execute(duckdb_query, duckdb_params).fetchone()
            if result:
                return result, 'duckdb'
        except Exception as e:
            self._log(f"DuckDB read error: {e}")
        return None, None

    def _save_to_cache(self, redis_key, redis_value, redis_ttl,
                       duckdb_query=None, duckdb_params=None):
        self._redis_set(redis_key, redis_value, redis_ttl)
        if self.con and not self.read_only and not self.worker_mode and duckdb_query and duckdb_params:
            try:
                self.con.execute(duckdb_query, duckdb_params)
            except Exception as e:
                self._log(f"DuckDB write error: {e}")

    # =========================================================================
    # DB INIT
    # =========================================================================

    def _init_db(self):
        if not self.con or self.worker_mode:
            return
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS wallet_token_cache (
                wallet TEXT, token TEXT,
                realized REAL, unrealized REAL, total_invested REAL,
                entry_price REAL, first_buy_time BIGINT,
                last_updated REAL, runner_multiplier REAL,
                PRIMARY KEY (wallet, token)
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS wallet_runner_cache (
                wallet STRING PRIMARY KEY,
                other_runners JSON, stats JSON, last_updated FLOAT
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS token_runner_cache (
                token STRING PRIMARY KEY, runner_info JSON, last_updated FLOAT
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS token_launch_cache (
                token TEXT PRIMARY KEY, launch_price REAL, last_updated REAL
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS token_info_cache (
                token TEXT PRIMARY KEY, symbol TEXT, name TEXT,
                liquidity REAL, volume_24h REAL, price REAL,
                holders INTEGER, age_days REAL, last_updated REAL
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS token_ath_cache (
                token TEXT PRIMARY KEY, highest_price REAL,
                timestamp INTEGER, last_updated REAL
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS token_security_cache (
                token TEXT PRIMARY KEY, security_data JSON, last_updated REAL
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS trending_runners_cache (
                cache_key TEXT PRIMARY KEY, runners JSON, last_updated REAL
            )
        """)
        self.con.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_token ON wallet_token_cache(wallet, token)"
        )

    def _log(self, message):
        if self.debug_mode:
            print(f"[WALLET ANALYZER] {message}")

    def _get_solanatracker_headers(self):
        return {'accept': 'application/json', 'x-api-key': self.solanatracker_key}

    def fetch_with_retry(self, url, headers, params=None, semaphore=None, max_retries=3):
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
                    wait_time = int(response.headers.get('Retry-After', 10))
                    self._log(f"Rate limited. Waiting {wait_time}s...")
                    time.sleep(wait_time + 2)
                    continue
                else:
                    return None
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return None

    async def async_fetch_with_retry(self, session, url, headers, params=None,
                                     semaphore=None, max_retries=3):
        """
        FIX: Rewrote to properly handle 429 rate limits with continue (old version had a
        scoping bug where continue inside the `if semaphore` block could break out of the
        wrong scope). Also added:
          - Jitter on all retries to spread load across concurrent workers
          - Increased timeout from 15s to 20s for slow endpoints
          - Proper handling of 502/503/504 gateway errors with exponential backoff
          - 429 does NOT consume a retry attempt (don't count against max_retries)
        """
        timeout = aiohttp.ClientTimeout(total=20)
        for attempt in range(max_retries):
            try:
                kwargs = dict(headers=headers, params=params, timeout=timeout)
                ctx = semaphore if semaphore else asyncio.nullcontext()
                async with ctx:
                    async with session.get(url, **kwargs) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 404:
                            return None
                        elif response.status == 429:
                            wait_time = int(response.headers.get('Retry-After', 15))
                            self._log(f"Rate limited on {url[-30:]} — waiting {wait_time}s")
                            await asyncio.sleep(wait_time + random.uniform(1, 3))
                            # 429 does not count as an attempt — loop continues without
                            # incrementing attempt, so we fall through to next iteration
                            continue
                        elif response.status in (502, 503, 504):
                            await asyncio.sleep(2 ** attempt + random.uniform(0, 1))
                            continue
                        else:
                            return None
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt + random.uniform(0, 1))
            except Exception:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        return None

    # =========================================================================
    # CACHE METHODS
    # =========================================================================

    def _get_cached_pnl_and_entry(self, wallet, token):
        now       = time.time()
        redis_key = f"pnl:{wallet}:{token}"

        cached = self._redis_get(redis_key)
        if cached is not None:
            return cached

        if self.con and not self.worker_mode:
            try:
                result = self.con.execute("""
                    SELECT realized, unrealized, total_invested, entry_price, first_buy_time
                    FROM wallet_token_cache
                    WHERE wallet = ? AND token = ? AND last_updated > ?
                """, [wallet, token, now - CACHE_TTL_PNL]).fetchone()
                if result:
                    data = {
                        'realized': result[0], 'unrealized': result[1],
                        'total_invested': result[2], 'entry_price': result[3],
                        'first_buy_time': result[4]
                    }
                    self._redis_set(redis_key, data, REDIS_TTL_PNL)
                    return data
            except Exception as e:
                self._log(f"DuckDB PnL read error: {e}")

        pnl = self.get_wallet_pnl_solanatracker(wallet, token)

        if pnl:
            # Extract entry_price from first_buy in PnL response
            first_buy   = pnl.get('first_buy', {})
            amount      = first_buy.get('amount', 0)
            volume_usd  = first_buy.get('volume_usd', 0)
            entry_price = (volume_usd / amount) if amount > 0 else None

            data = {
                'realized':       pnl.get('realized', 0),
                'unrealized':     pnl.get('unrealized', 0),
                'total_invested': pnl.get('total_invested') or pnl.get('totalInvested', 0),
                'entry_price':    entry_price,
                'first_buy_time': first_buy.get('time') if first_buy else None,
            }
            self._save_to_cache(
                redis_key, data, REDIS_TTL_PNL,
                duckdb_query="""
                    INSERT OR REPLACE INTO wallet_token_cache
                    (wallet, token, realized, unrealized, total_invested,
                     entry_price, first_buy_time, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                duckdb_params=[
                    wallet, token, data['realized'], data['unrealized'],
                    data['total_invested'], data['entry_price'],
                    data['first_buy_time'], now
                ]
            )
            return data
        return None

    def _get_cached_other_runners(self, wallet, current_token=None, min_multiplier=10.0):
        now       = time.time()
        redis_key = f"runners:{wallet}"

        cached = self._redis_get(redis_key)
        if cached is not None:
            # Ensure backward compat keys exist on cached result
            if 'other_runners' not in cached:
                cached['other_runners'] = cached.get('runners_30d', [])
            if 'stats' not in cached:
                cached['stats'] = cached.get('stats_30d', {})
            return cached

        if self.con and not self.worker_mode:
            try:
                result = self.con.execute("""
                    SELECT other_runners, stats FROM wallet_runner_cache
                    WHERE wallet = ? AND last_updated > ?
                """, [wallet, now - CACHE_TTL_RUNNERS]).fetchone()
                if result:
                    # Old cache format — migrate on read
                    data = {
                        'other_runners': json.loads(result[0]),
                        'stats':         json.loads(result[1]),
                        'runners_7d':    [],
                        'runners_14d':   [],
                        'runners_30d':   json.loads(result[0]),
                        'stats_7d':      {},
                        'stats_14d':     {},
                        'stats_30d':     json.loads(result[1]),
                    }
                    self._redis_set(redis_key, data, REDIS_TTL_RUNNERS)
                    return data
            except Exception as e:
                self._log(f"DuckDB runners read error: {e}")

        runners = self.get_wallet_other_runners(wallet, current_token, min_multiplier)
        if runners:
            self._save_to_cache(
                redis_key, runners, REDIS_TTL_RUNNERS,
                duckdb_query="""
                    INSERT OR REPLACE INTO wallet_runner_cache
                    (wallet, other_runners, stats, last_updated) VALUES (?, ?, ?, ?)
                """,
                duckdb_params=[
                    wallet,
                    json.dumps(runners.get('runners_30d', [])),
                    json.dumps(runners.get('stats_30d', {})),
                    now
                ]
            )
            return runners
        return self._empty_runner_result()

    def _get_cached_check_if_runner(self, token, min_multiplier=5.0):
        now       = time.time()
        redis_key = f"token_runner:{token}"

        cached = self._redis_get(redis_key)
        if cached is not None:
            return cached

        if self.con and not self.worker_mode:
            try:
                result = self.con.execute(
                    "SELECT runner_info FROM token_runner_cache WHERE token = ? AND last_updated > ?",
                    [token, now - CACHE_TTL_RUNNERS]
                ).fetchone()
                if result:
                    data = json.loads(result[0])
                    self._redis_set(redis_key, data, REDIS_TTL_RUNNERS)
                    return data
            except Exception as e:
                self._log(f"DuckDB token_runner read error: {e}")

        runner_info = self._check_if_runner(token, min_multiplier)
        if runner_info:
            self._save_to_cache(
                redis_key, runner_info, REDIS_TTL_RUNNERS,
                duckdb_query="INSERT OR REPLACE INTO token_runner_cache VALUES (?, ?, ?)",
                duckdb_params=[token, json.dumps(runner_info), now]
            )
            return runner_info
        return None

    def _get_token_launch_price(self, token_address):
        now       = time.time()
        redis_key = f"launch_price:{token_address}"

        cached = self._redis_get(redis_key)
        if cached is not None:
            return cached.get('price')

        if self.con and not self.worker_mode:
            try:
                result = self.con.execute("""
                    SELECT launch_price FROM token_launch_cache
                    WHERE token = ? AND last_updated > ?
                """, [token_address, now - CACHE_TTL_LAUNCH]).fetchone()
                if result:
                    self._redis_set(redis_key, {'price': result[0]}, REDIS_TTL_LAUNCH)
                    return result[0]
            except Exception as e:
                self._log(f"DuckDB launch_price read error: {e}")

        try:
            url  = f"{self.st_base_url}/tokens/{token_address}"
            data = self.fetch_with_retry(url, self._get_solanatracker_headers(),
                                         semaphore=self.solana_tracker_semaphore)
            if data and data.get('pools'):
                primary_pool = max(data['pools'], key=lambda p: p.get('liquidity', {}).get('usd', 0))
                launch_price = primary_pool.get('price', {}).get('usd', 0)
                if launch_price and launch_price > 0:
                    self._save_to_cache(
                        redis_key, {'price': launch_price}, REDIS_TTL_LAUNCH,
                        duckdb_query="""
                            INSERT OR REPLACE INTO token_launch_cache
                            (token, launch_price, last_updated) VALUES (?, ?, ?)
                        """,
                        duckdb_params=[token_address, launch_price, now]
                    )
                    return launch_price
        except Exception as e:
            self._log(f"Error fetching launch price: {e}")
        return None

    def get_token_ath(self, token_address):
        now       = time.time()
        redis_key = f"token_ath:{token_address}"

        cached = self._redis_get(redis_key)
        if cached is not None:
            return cached

        if self.con and not self.worker_mode:
            try:
                result = self.con.execute("""
                    SELECT highest_price, timestamp FROM token_ath_cache
                    WHERE token = ? AND last_updated > ?
                """, [token_address, now - CACHE_TTL_TOKEN_INFO]).fetchone()
                if result:
                    data = {'highest_price': result[0], 'timestamp': result[1]}
                    self._redis_set(redis_key, data, REDIS_TTL_TOKEN_INFO)
                    return data
            except Exception as e:
                self._log(f"DuckDB ATH read error: {e}")

        try:
            url  = f"{self.st_base_url}/tokens/{token_address}/ath"
            data = self.fetch_with_retry(url, self._get_solanatracker_headers(),
                                         semaphore=self.solana_tracker_semaphore)
            if data:
                self._save_to_cache(
                    redis_key, data, REDIS_TTL_TOKEN_INFO,
                    duckdb_query="""
                        INSERT OR REPLACE INTO token_ath_cache
                        (token, highest_price, timestamp, last_updated) VALUES (?, ?, ?, ?)
                    """,
                    duckdb_params=[
                        token_address, data.get('highest_price', 0),
                        data.get('timestamp', 0), now
                    ]
                )
                return data
        except Exception as e:
            self._log(f"⚠️ Error fetching ATH: {str(e)}")
        return None

    def _get_token_detailed_info(self, token_address):
        now       = time.time()
        redis_key = f"token_info:{token_address}"

        cached = self._redis_get(redis_key)
        if cached is not None:
            return cached

        if self.con and not self.worker_mode:
            try:
                result = self.con.execute("""
                    SELECT symbol, name, liquidity, volume_24h, price, holders, age_days
                    FROM token_info_cache WHERE token = ? AND last_updated > ?
                """, [token_address, now - CACHE_TTL_TOKEN_INFO]).fetchone()
                if result:
                    info = {
                        'symbol': result[0], 'name': result[1], 'address': token_address,
                        'liquidity': result[2], 'volume_24h': result[3], 'price': result[4],
                        'holders': result[5], 'age_days': result[6],
                        'age': f"{result[6]:.1f}d" if result[6] > 0 else 'N/A',
                        'creation_time': None
                    }
                    self._redis_set(redis_key, info, REDIS_TTL_TOKEN_INFO)
                    return info
            except Exception as e:
                self._log(f"DuckDB token_info read error: {e}")

        try:
            url  = f"{self.st_base_url}/tokens/{token_address}"
            data = self.fetch_with_retry(url, self._get_solanatracker_headers(),
                                         semaphore=self.solana_tracker_semaphore)
            if not data or not data.get('pools'):
                return None

            primary_pool   = max(data['pools'], key=lambda p: p.get('liquidity', {}).get('usd', 0))
            token_meta     = data.get('token', {})
            creation_time  = token_meta.get('creation', {}).get('created_time', 0)
            token_age_days = (time.time() - creation_time) / 86400 if creation_time > 0 else 0

            info = {
                'symbol':        token_meta.get('symbol', 'UNKNOWN'),
                'name':          token_meta.get('name', 'Unknown'),
                'address':       token_address,
                'liquidity':     primary_pool.get('liquidity', {}).get('usd', 0),
                'volume_24h':    primary_pool.get('txns', {}).get('volume24h', 0),
                'price':         primary_pool.get('price', {}).get('usd', 0),
                'holders':       data.get('holders', 0),
                'age_days':      token_age_days,
                'age':           f"{token_age_days:.1f}d" if token_age_days > 0 else 'N/A',
                'creation_time': creation_time,
            }
            self._save_to_cache(
                redis_key, info, REDIS_TTL_TOKEN_INFO,
                duckdb_query="""
                    INSERT OR REPLACE INTO token_info_cache
                    (token, symbol, name, liquidity, volume_24h, price, holders, age_days, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                duckdb_params=[
                    token_address, info['symbol'], info['name'],
                    info['liquidity'], info['volume_24h'], info['price'],
                    info['holders'], info['age_days'], now
                ]
            )
            return info
        except Exception as e:
            self._log(f"⚠️ Token info error: {str(e)}")
            return None

    def _check_token_security(self, token_address):
        now       = time.time()
        redis_key = f"token_security:{token_address}"

        cached = self._redis_get(redis_key)
        if cached is not None:
            return cached

        if self.con and not self.worker_mode:
            try:
                result = self.con.execute("""
                    SELECT security_data FROM token_security_cache
                    WHERE token = ? AND last_updated > ?
                """, [token_address, now - CACHE_TTL_TOKEN_INFO]).fetchone()
                if result:
                    data = json.loads(result[0])
                    self._redis_set(redis_key, data, REDIS_TTL_TOKEN_INFO)
                    return data
            except Exception as e:
                self._log(f"DuckDB security read error: {e}")

        try:
            url  = f"{self.st_base_url}/tokens/{token_address}"
            data = self.fetch_with_retry(url, self._get_solanatracker_headers(),
                                         semaphore=self.solana_tracker_semaphore)
            if not data or not data.get('pools'):
                return None

            token_meta   = data.get('token', {})
            symbol       = token_meta.get('symbol', token_address[:8])
            primary_pool = max(data['pools'], key=lambda p: p.get('liquidity', {}).get('usd', 0))

            security_obj     = primary_pool.get('security', {})
            is_mint_revoked  = security_obj.get('mintAuthority') is None
            freeze_revoked   = security_obj.get('freezeAuthority') is None
            lp_burn_pct      = primary_pool.get('lpBurn', 0) or 0
            is_liq_locked    = lp_burn_pct >= 90
            strict_socials   = token_meta.get('strictSocials', {})
            social_count     = sum(1 for v in strict_socials.values() if v) if strict_socials else 0
            jupiter_verified = data.get('risk', {}).get('jupiterVerified', False)
            has_social       = social_count >= 1 or jupiter_verified

            passes = is_mint_revoked and is_liq_locked and has_social
            security_data = {
                'is_mint_revoked':     is_mint_revoked,
                'is_liquidity_locked': is_liq_locked,
                'freeze_revoked':      freeze_revoked,
                'has_social':          has_social,
                'social_count':        social_count,
                'socials':             strict_socials,
                'passes_security':     passes,
            }
            self._save_to_cache(
                redis_key, security_data, REDIS_TTL_TOKEN_INFO,
                duckdb_query="""
                    INSERT OR REPLACE INTO token_security_cache
                    (token, security_data, last_updated) VALUES (?, ?, ?)
                """,
                duckdb_params=[token_address, json.dumps(security_data), now]
            )
            return security_data
        except Exception as e:
            self._log(f"Security check error for {token_address}: {e}")
            return None

    # =========================================================================
    # DATA FETCHING
    # =========================================================================

    def get_wallet_pnl_solanatracker(self, wallet_address, token_address):
        try:
            url = f"{self.st_base_url}/pnl/{wallet_address}/{token_address}"
            return self.fetch_with_retry(url, self._get_solanatracker_headers(),
                                         semaphore=self.pnl_semaphore)
        except Exception as e:
            self._log(f"⚠️ Error fetching PnL: {str(e)}")
            return None

    def _fetch_wallet_all_positions(self, wallet_address):
        """
        Fetches /pnl/{wallet} — returns ALL tokens ever traded by this wallet.

        Response shape per token:
          realized, unrealized, total_invested, cost_basis (= avg entry price),
          first_buy_time, last_trade_time, buy_transactions, sell_transactions

        cost_basis is the average buy price across all purchases — used as entry_price
        for runner history scoring.
        """
        try:
            url  = f"{self.st_base_url}/pnl/{wallet_address}"
            data = self.fetch_with_retry(
                url, self._get_solanatracker_headers(),
                semaphore=self.pnl_semaphore
            )
            if data and data.get('tokens'):
                return data['tokens']   # {token_addr: {realized, total_invested, cost_basis, ...}}
            return {}
        except Exception as e:
            self._log(f"[ALL POSITIONS] Error for {wallet_address[:8]}: {e}")
            return {}

    def _bucket_runners_by_window(self, runner_records):
        """
        Given a list of runner dicts (already confirmed as runners with security pass),
        split them into 7d, 14d, 30d buckets based on first_buy_time.

        A wallet's position falls in the tightest window that contains its first_buy_time.
        e.g. if bought 5 days ago → in 7d, 14d, AND 30d buckets (cumulative).

        Returns:
          {
            'runners_7d':  [list],
            'runners_14d': [list],
            'runners_30d': [list],
            'stats_7d':    {success_rate, avg_roi, avg_entry_to_ath, total},
            'stats_14d':   {...},
            'stats_30d':   {...},
          }
        """
        now       = time.time() * 1000   # ms
        window_7  = now - (7  * 86400 * 1000)
        window_14 = now - (14 * 86400 * 1000)
        window_30 = now - (30 * 86400 * 1000)

        buckets = {'7d': [], '14d': [], '30d': []}

        for r in runner_records:
            first_buy_time = r.get('first_buy_time', 0)
            if first_buy_time >= window_7:
                buckets['7d'].append(r)
                buckets['14d'].append(r)
                buckets['30d'].append(r)
            elif first_buy_time >= window_14:
                buckets['14d'].append(r)
                buckets['30d'].append(r)
            elif first_buy_time >= window_30:
                buckets['30d'].append(r)
            # older than 30d — excluded from all buckets

        def _compute_stats(runners):
            if not runners:
                return {
                    'total_other_runners': 0,
                    'success_rate':        0,
                    'avg_roi':             0,
                    'avg_entry_to_ath':    0,
                    'total_invested':      0,
                    'total_realized':      0,
                }
            successful    = sum(1 for r in runners if r.get('roi_multiplier', 0) > 1)
            roi_vals      = [r['roi_multiplier'] for r in runners if r.get('roi_multiplier')]
            ath_vals      = [r['entry_to_ath_multiplier'] for r in runners
                             if r.get('entry_to_ath_multiplier')]
            return {
                'total_other_runners': len(runners),
                'success_rate':        round(successful / len(runners) * 100, 1),
                'avg_roi':             round(sum(roi_vals) / len(roi_vals), 2) if roi_vals else 0,
                'avg_entry_to_ath':    round(sum(ath_vals) / len(ath_vals), 2) if ath_vals else 0,
                'total_invested':      round(sum(r.get('invested', 0) for r in runners), 2),
                'total_realized':      round(sum(r.get('realized', 0) for r in runners), 2),
            }

        return {
            'runners_7d':  buckets['7d'],
            'runners_14d': buckets['14d'],
            'runners_30d': buckets['30d'],
            'stats_7d':    _compute_stats(buckets['7d']),
            'stats_14d':   _compute_stats(buckets['14d']),
            'stats_30d':   _compute_stats(buckets['30d']),
            # Keep flat list + stats for backward compatibility with existing callers
            'other_runners': buckets['30d'],
            'stats':         _compute_stats(buckets['30d']),
        }

    def _empty_runner_result(self):
        """Consistent empty result structure."""
        empty_stats = {
            'total_other_runners': 0,
            'success_rate':        0,
            'avg_roi':             0,
            'avg_entry_to_ath':    0,
            'total_invested':      0,
            'total_realized':      0,
        }
        return {
            'runners_7d':    [],
            'runners_14d':   [],
            'runners_30d':   [],
            'stats_7d':      empty_stats,
            'stats_14d':     empty_stats,
            'stats_30d':     empty_stats,
            'other_runners': [],
            'stats':         empty_stats,
        }

    def get_wallet_other_runners(self, wallet_address, current_token_address=None,
                                  min_multiplier=10.0):
        """
        Find other runner tokens this wallet traded, using /pnl/{wallet}.

        Flow:
          1. Fetch all positions via /pnl/{wallet}
          2. For each token (excluding current_token):
               a. Check security (mint revoked, liquidity locked, has social)
               b. Check if it's a runner (_get_price_range_in_period with 30d window)
               c. Compute ROI and entry_to_ath from cost_basis + ATH
          3. Bucket qualifying runners into 7d / 14d / 30d by first_buy_time
          4. Return bucketed results + backward-compatible flat list

        Returns:
          {
            'runners_7d':    [...],
            'runners_14d':   [...],
            'runners_30d':   [...],
            'stats_7d':      {...},
            'stats_14d':     {...},
            'stats_30d':     {...},
            'other_runners': [...],   # = runners_30d (backward compat)
            'stats':         {...},   # = stats_30d   (backward compat)
          }
        """
        try:
            self._log(f"\n[RUNNER HISTORY] {'='*50}")
            self._log(f"[RUNNER HISTORY] Fetching for wallet {wallet_address[:8]}...")

            all_positions = self._fetch_wallet_all_positions(wallet_address)
            if not all_positions:
                self._log(f"[RUNNER HISTORY] ❌ No positions found for {wallet_address[:8]}")
                return self._empty_runner_result()

            self._log(f"[RUNNER HISTORY] ✅ Found {len(all_positions)} positions")

            runner_records = []

            for token_addr, position in list(all_positions.items())[:20]:
                if token_addr == current_token_address:
                    continue

                total_invested = position.get('total_invested', 0)
                if total_invested <= 0:
                    continue

                # ── Security check ────────────────────────────────────────────────
                security = self._check_token_security(token_addr)
                if not security or not security.get('passes_security'):
                    self._log(f"[RUNNER HISTORY] ❌ {token_addr[:8]} failed security")
                    continue

                # ── Runner check (10x+ in 30d) ────────────────────────────────────
                runner_info = self._get_cached_check_if_runner(token_addr, min_multiplier)
                if not runner_info:
                    self._log(f"[RUNNER HISTORY] ❌ {token_addr[:8]} not a runner")
                    continue

                self._log(f"[RUNNER HISTORY] ✅ {token_addr[:8]} is a runner ({runner_info.get('multiplier')}x)")

                # ── ROI from position data ────────────────────────────────────────
                realized     = position.get('realized', 0)
                unrealized   = position.get('unrealized', 0)
                roi_mult     = (realized + total_invested) / total_invested

                # ── Entry price from cost_basis (avg buy price) ───────────────────
                # cost_basis = average price paid per token across all buys
                entry_price  = position.get('cost_basis')
                ath_price    = runner_info.get('ath_price', 0)

                entry_to_ath = None
                if entry_price and entry_price > 0 and ath_price and ath_price > 0:
                    entry_to_ath = round(ath_price / entry_price, 2)

                record = {
                    'address':               token_addr,
                    'symbol':                runner_info.get('symbol', token_addr[:8]),
                    'name':                  runner_info.get('name', ''),
                    'multiplier':            runner_info.get('multiplier'),
                    'current_price':         runner_info.get('current_price', 0),
                    'ath_price':             ath_price,
                    'liquidity':             runner_info.get('liquidity', 0),
                    'roi_multiplier':        round(roi_mult, 2),
                    'invested':              round(total_invested, 2),
                    'realized':              round(realized, 2),
                    'unrealized':            round(unrealized, 2),
                    'entry_price':           entry_price,
                    'entry_to_ath_multiplier': entry_to_ath,
                    'distance_to_ath_pct':   round(((ath_price - entry_price) / ath_price) * 100, 2)
                                             if entry_price and ath_price and ath_price > 0 else None,
                    'first_buy_time':        position.get('first_buy_time', 0),
                    'last_trade_time':       position.get('last_trade_time', 0),
                    'buy_transactions':      position.get('buy_transactions', 0),
                    'sell_transactions':     position.get('sell_transactions', 0),
                    # Security info for display
                    'security': {
                        'mint_revoked':     security.get('is_mint_revoked', False),
                        'liquidity_locked': security.get('is_liquidity_locked', False),
                        'has_social':       security.get('has_social', False),
                    },
                }
                runner_records.append(record)
                time.sleep(0.2)

            self._log(f"[RUNNER HISTORY] {len(runner_records)} qualifying runners found")
            self._log(f"[RUNNER HISTORY] {'='*50}\n")

            return self._bucket_runners_by_window(runner_records)

        except Exception as e:
            self._log(f"⚠️ Error in get_wallet_other_runners: {e}")
            import traceback; traceback.print_exc()
            return self._empty_runner_result()

    # =========================================================================
    # TRENDING RUNNER DISCOVERY
    # =========================================================================

    def _get_price_range_in_period(self, token_address, days_back):
        """
        Best pump multiplier within the last days_back days, using the O(n)
        best-profit algorithm.
        """
        try:
            time_to   = int(time.time())
            time_from = time_to - (days_back * 86400)
            candle_type = '1h' if days_back <= 7 else '4h'

            url    = f"{self.st_base_url}/chart/{token_address}"
            params = {'type': candle_type, 'time_from': time_from, 'time_to': time_to, 'currency': 'usd'}
            data   = self.fetch_with_retry(url, self._get_solanatracker_headers(),
                                           params=params, semaphore=self.solana_tracker_semaphore)
            if not data:
                return None

            candles = data.get('oclhv', [])
            if not candles:
                return None

            best_multiplier    = 0.0
            best_low           = None
            best_high          = None
            running_min_low    = float('inf')

            for candle in candles:
                low  = candle.get('low')
                high = candle.get('high')
                if low is None or high is None or low <= 0:
                    continue

                if low < running_min_low:
                    running_min_low = low

                if running_min_low > 0:
                    mult = high / running_min_low
                    if mult > best_multiplier:
                        best_multiplier = mult
                        best_low        = running_min_low
                        best_high       = high

            if best_multiplier == 0 or best_low is None:
                return None

            return {
                'lowest_price':  best_low,
                'highest_price': best_high,
                'multiplier':    best_multiplier,
                'candle_count':  len(candles),
                'qualified_at':  int(time.time()),
            }
        except Exception as e:
            self._log(f"⚠️ Price range error: {e}")
            return None

    def find_trending_runners_enhanced(self, days_back=7, min_multiplier=5.0, min_liquidity=50000):
        """
        Maintain a ranked leaderboard of tokens that pumped >= min_multiplier.
        """
        from datetime import datetime, timedelta

        cache_key      = f"{days_back}_{min_multiplier}_{min_liquidity}_secure"
        now            = datetime.now()
        list_cache_key = f"trending:{cache_key}"
        board_key      = f"trending_leaderboard:{cache_key}"

        # ── Fast path: 10-min list cache still hot ────────────────────────────────
        cached = self._redis_get(list_cache_key)
        if cached is not None:
            return cached

        if days_back != 30 and cache_key in self._trending_cache:
            age = now - self._cache_expiry.get(cache_key, now)
            if age < timedelta(seconds=CACHE_TTL_TRENDING):
                return self._trending_cache[cache_key]

        if self.con and not self.worker_mode:
            try:
                row = self.con.execute("""
                    SELECT runners FROM trending_runners_cache
                    WHERE cache_key = ? AND last_updated > ?
                """, [cache_key, time.time() - CACHE_TTL_TRENDING]).fetchone()
                if row:
                    runners = json.loads(row[0])
                    self._redis_set(list_cache_key, runners, REDIS_TTL_TRENDING)
                    return runners
            except Exception as e:
                self._log(f"DuckDB trending read error: {e}")

        # ── Load persisted leaderboard ────────────────────────────────────────────
        leaderboard      = self._redis_get(board_key) or []
        board_by_address = {r['address']: r for r in leaderboard}

        self._log(f"\n{'='*70}")
        self._log(f"LEADERBOARD UPDATE {days_back}d {min_multiplier}x+ "
                  f"({len(leaderboard)}/{MAX_RUNNERS} slots)")
        self._log(f"{'='*70}")

        # ── Fetch platform candidates ─────────────────────────────────────────────
        try:
            response = self.fetch_with_retry(
                f"{self.st_base_url}/tokens/trending",
                self._get_solanatracker_headers(),
                semaphore=self.solana_tracker_semaphore
            )
            if not response:
                self._log("Platform API unavailable — returning existing leaderboard")
                self._redis_set(list_cache_key, leaderboard, REDIS_TTL_TRENDING)
                return leaderboard
            trending_data = response if isinstance(response, list) else []
        except Exception as e:
            self._log(f"❌ Trending fetch error: {e}")
            return leaderboard

        for item in trending_data:
            try:
                token = item.get('token', {})
                pools = item.get('pools', [])
                if not pools or not token:
                    continue

                mint      = token.get('mint')
                pool      = pools[0]
                liquidity = pool.get('liquidity', {}).get('usd', 0)
                symbol    = token.get('symbol', '?')

                if liquidity < min_liquidity:
                    continue

                qual_key = f"trending_qual:{mint}:{cache_key}"

                # ── INCUMBENT: already on leaderboard ─────────────────────────────
                if mint in board_by_address:
                    cached_qual = self._redis_get(qual_key)
                    if cached_qual is None:
                        price_range = self._get_price_range_in_period(mint, days_back)
                        if price_range:
                            old_mult = board_by_address[mint]['multiplier']
                            new_mult = round(price_range['multiplier'], 2)
                            if new_mult > old_mult:
                                self._log(f"  ⬆ {symbol} re-pumped {old_mult}x→{new_mult}x")
                                board_by_address[mint].update({
                                    'multiplier':    new_mult,
                                    'lowest_price':  price_range['lowest_price'],
                                    'highest_price': price_range['highest_price'],
                                    'qualified_at':  price_range['qualified_at'],
                                })
                            self._redis_set(qual_key, {
                                'qualified':    True,
                                'multiplier':   new_mult,
                                'qualified_at': price_range['qualified_at'],
                            }, CACHE_TTL_QUAL)
                        else:
                            self._redis_set(qual_key, {
                                'qualified':    True,
                                'multiplier':   board_by_address[mint]['multiplier'],
                                'qualified_at': int(time.time()),
                            }, CACHE_TTL_QUAL)
                    continue

                # ── NEW CANDIDATE ─────────────────────────────────────────────────
                cached_qual = self._redis_get(qual_key)
                if cached_qual is not None and not cached_qual.get('qualified'):
                    continue   # recently failed — skip

                security = self._check_token_security(mint)
                if not security or not security['passes_security']:
                    continue

                price_range = self._get_price_range_in_period(mint, days_back)

                if not price_range or price_range['multiplier'] < min_multiplier:
                    self._redis_set(qual_key, {'qualified': False}, CACHE_TTL_QUAL_NEG)
                    continue

                # Build the runner record
                token_info = self._get_token_detailed_info(mint)
                if not token_info:
                    continue

                ath_data   = self.get_token_ath(mint)
                new_runner = {
                    'symbol':         symbol,
                    'ticker':         symbol,
                    'name':           token.get('name', 'Unknown'),
                    'address':        mint,
                    'chain':          'solana',
                    'multiplier':     round(price_range['multiplier'], 2),
                    'period_days':    days_back,
                    'lowest_price':   price_range['lowest_price'],
                    'highest_price':  price_range['highest_price'],
                    'current_price':  token_info['price'],
                    'ath_price':      ath_data.get('highest_price', 0) if ath_data else 0,
                    'ath_time':       ath_data.get('timestamp', 0)     if ath_data else 0,
                    'liquidity':      liquidity,
                    'volume_24h':     token_info['volume_24h'],
                    'holders':        token_info['holders'],
                    'token_age_days': round(token_info.get('age_days', 0), 1),
                    'age':            token_info.get('age', 'N/A'),
                    'pair_address':   pool.get('poolId', mint),
                    'qualified_at':   price_range['qualified_at'],
                    'security': {
                        'mint_revoked':     security['is_mint_revoked'],
                        'liquidity_locked': security['is_liquidity_locked'],
                        'has_social':       security['has_social'],
                        'social_count':     security['social_count'],
                    },
                }

                if len(board_by_address) < MAX_RUNNERS:
                    # Free slot
                    board_by_address[mint] = new_runner
                    self._log(f"  ✅ {symbol} added ({new_runner['multiplier']}x) "
                              f"— {len(board_by_address)}/{MAX_RUNNERS} slots")
                else:
                    # Board full — only displace the weakest if we beat it
                    weakest = min(board_by_address.values(), key=lambda r: r['multiplier'])
                    if new_runner['multiplier'] > weakest['multiplier']:
                        self._log(f"  🔄 {symbol} ({new_runner['multiplier']}x) displaces "
                                  f"{weakest['symbol']} ({weakest['multiplier']}x)")
                        self._redis_delete(f"trending_qual:{weakest['address']}:{cache_key}")
                        del board_by_address[weakest['address']]
                        board_by_address[mint] = new_runner
                    else:
                        self._log(f"  ✗ {symbol} ({new_runner['multiplier']}x) not strong enough "
                                  f"— weakest is {weakest['symbol']} ({weakest['multiplier']}x)")
                        self._redis_set(qual_key, {'qualified': False}, CACHE_TTL_QUAL_NEG)
                        continue

                # Store positive qual result for this token
                self._redis_set(qual_key, {
                    'qualified':    True,
                    'multiplier':   new_runner['multiplier'],
                    'qualified_at': price_range['qualified_at'],
                }, CACHE_TTL_QUAL)

                time.sleep(0.3)

            except Exception as e:
                self._log(f"⚠️ Token skip: {e}")
                continue

        # ── Sort and persist ──────────────────────────────────────────────────────
        leaderboard = sorted(board_by_address.values(),
                             key=lambda r: r['multiplier'], reverse=True)

        self._redis_set(board_key,      leaderboard, CACHE_TTL_QUAL)
        self._redis_set(list_cache_key, leaderboard, REDIS_TTL_TRENDING)

        if self.con and not self.worker_mode:
            try:
                self.con.execute("""
                    INSERT OR REPLACE INTO trending_runners_cache
                    (cache_key, runners, last_updated) VALUES (?, ?, ?)
                """, [cache_key, json.dumps(leaderboard), time.time()])
            except Exception as e:
                self._log(f"DuckDB write error: {e}")

        if days_back != 30:
            self._trending_cache[cache_key] = leaderboard
            self._cache_expiry[cache_key]   = now

        self._log(f"✅ Leaderboard: {len(leaderboard)} runners")
        return leaderboard

    def preload_trending_cache(self):
        for days_back in [7, 14]:
            runners = self.find_trending_runners_enhanced(days_back=days_back)
            self._log(f"✅ Preloaded {len(runners)} runners for {days_back}d")

    # =========================================================================
    # MOMENTUM SCORING + LIVE REFRESH
    # =========================================================================

    def _calculate_momentum_score(self, runner):
        try:
            score = 0

            volume = runner.get('volume_24h', 0)
            if volume > 0:
                volume_score = min(40, (volume / 100000) * 10)
                score += volume_score

            multiplier = runner.get('multiplier', 1)
            price_score = min(30, (multiplier - 1) * 5)
            score += price_score

            holders = runner.get('holders', 0)
            holder_score = min(20, holders / 100)
            score += holder_score

            liquidity = runner.get('liquidity', 0)
            liquidity_score = min(10, liquidity / 50000)
            score += liquidity_score

            multiplier_bonus = min(20, runner.get('multiplier', 1) * 2)
            score = score * (1 + multiplier_bonus / 100)

            return round(score, 2)

        except Exception as e:
            self._log(f"  ⚠️ Momentum score error: {e}")
            return runner.get('multiplier', 1) * 10

    def refresh_runner_market_data(self, days_back=7, min_multiplier=5.0, min_liquidity=50000):
        cache_key      = f"{days_back}_{min_multiplier}_{min_liquidity}_secure"
        board_key      = f"trending_leaderboard:{cache_key}"
        list_cache_key = f"trending:{cache_key}"

        leaderboard = self._redis_get(board_key)
        if not leaderboard:
            return self.find_trending_runners_enhanced(days_back, min_multiplier, min_liquidity)

        self._log(f"\n[LIVE] Refreshing market data and re-ranking {len(leaderboard)} runners...")

        updated_runners = []
        for runner in leaderboard:
            try:
                info = self._get_token_detailed_info(runner['address'])
                if info:
                    runner['current_price'] = info['price']
                    runner['volume_24h'] = info['volume_24h']
                    runner['holders'] = info['holders']
                    runner['liquidity'] = info.get('liquidity', runner.get('liquidity', 0))

                price_range = self._get_price_range_in_period(runner['address'], days_back)
                if price_range and price_range['multiplier'] >= min_multiplier:
                    if price_range['qualified_at'] > runner.get('qualified_at', 0):
                        self._log(f"  🔥 {runner['symbol']} pumped again! Extending window")
                        runner['multiplier'] = round(price_range['multiplier'], 2)
                        runner['lowest_price'] = price_range['lowest_price']
                        runner['highest_price'] = price_range['highest_price']
                        runner['qualified_at'] = price_range['qualified_at']

                        qual_key = f"trending_qual:{runner['address']}:{cache_key}"
                        self._redis_set(qual_key, {
                            'qualified': True,
                            'multiplier': runner['multiplier'],
                            'qualified_at': runner['qualified_at'],
                        }, CACHE_TTL_QUAL)

                runner['momentum_score'] = self._calculate_momentum_score(runner)
                updated_runners.append(runner)

            except Exception as e:
                self._log(f"  ⚠️ Market data failed for {runner.get('symbol')}: {e}")
                runner['momentum_score'] = self._calculate_momentum_score(runner)
                updated_runners.append(runner)

        updated_runners.sort(key=lambda r: r['momentum_score'], reverse=True)

        for idx, runner in enumerate(updated_runners, 1):
            runner['rank'] = idx
            runner['rank_change'] = runner.get('rank', idx) - idx

        self._redis_set(board_key, updated_runners, CACHE_TTL_QUAL)
        self._redis_set(list_cache_key, updated_runners, REDIS_TTL_TRENDING)

        self._log(f"[LIVE] Done — {len(updated_runners)} runners re-ranked by momentum")
        return updated_runners

    # =========================================================================
    # SCORING
    # =========================================================================

    def calculate_wallet_relative_score(self, wallet_data, consistency_score=None):
        """
        Score a wallet's entry and ROI quality using log-scale via _roi_to_score().

        Weights:
          60% — entry_to_ath_multiplier  (how early relative to ATH, log-scaled)
          30% — total_multiplier         (realized + unrealized ROI, log-scaled)
          10% — realized_multiplier      (single token) OR consistency_score (batch)

        Percentages (distance_to_ath_pct) are computed for display only and never
        feed into the score calculation.
        """
        try:
            entry_price         = wallet_data.get('entry_price') or 0
            ath_price           = wallet_data.get('ath_price') or 0
            realized_multiplier = wallet_data.get('realized_multiplier') or 0
            total_multiplier    = wallet_data.get('total_multiplier') or 0

            # ── 60%: entry timing relative to ATH — log-scaled ───────────────────
            if entry_price > 0 and ath_price > 0:
                entry_to_ath_multiplier = ath_price / entry_price
                distance_to_ath_pct     = ((ath_price - entry_price) / ath_price) * 100  # display only
                entry_score             = _roi_to_score(entry_to_ath_multiplier)
            else:
                entry_to_ath_multiplier = 0
                distance_to_ath_pct     = 0
                entry_score             = 0

            # ── 30%: total ROI (realized + unrealized) — log-scaled ──────────────
            total_roi_score = _roi_to_score(total_multiplier)

            # ── 10%: realized ROI (single token) OR entry consistency (batch) ────
            if consistency_score is not None:
                tenth_score         = consistency_score
                score_breakdown_key = 'consistency_score'
            else:
                tenth_score         = _roi_to_score(realized_multiplier)
                score_breakdown_key = 'realized_score'

            professional_score = (0.60 * entry_score + 0.30 * total_roi_score + 0.10 * tenth_score)

            if professional_score >= 90:   grade = 'A+'
            elif professional_score >= 85: grade = 'A'
            elif professional_score >= 80: grade = 'A-'
            elif professional_score >= 75: grade = 'B+'
            elif professional_score >= 70: grade = 'B'
            elif professional_score >= 65: grade = 'B-'
            elif professional_score >= 60: grade = 'C+'
            elif professional_score >= 50: grade = 'C'
            elif professional_score >= 40: grade = 'D'
            else:                          grade = 'F'

            return {
                'professional_score':      round(professional_score, 2),
                'professional_grade':      grade,
                'entry_to_ath_multiplier': round(entry_to_ath_multiplier, 2) if entry_to_ath_multiplier else None,
                'distance_to_ath_pct':     round(distance_to_ath_pct, 2) if distance_to_ath_pct else None,  # display only
                'realized_multiplier':     round(realized_multiplier, 2) if realized_multiplier else None,
                'total_multiplier':        round(total_multiplier, 2) if total_multiplier else None,
                'score_breakdown': {
                    'entry_score':       round(entry_score, 2),
                    'total_roi_score':   round(total_roi_score, 2),
                    score_breakdown_key: round(tenth_score, 2),
                }
            }
        except Exception as e:
            self._log(f"[SCORING ERROR] {str(e)}")
            return {
                'professional_score': 0, 'professional_grade': 'F',
                'entry_to_ath_multiplier': None, 'distance_to_ath_pct': None,
                'realized_multiplier': None, 'total_multiplier': None,
                'score_breakdown': {'entry_score': 0, 'total_roi_score': 0, 'realized_score': 0}
            }

    # =========================================================================
    # 30-DAY RUNNER HISTORY - FIXED WITH DEBUG LOGGING
    # =========================================================================

    def _check_if_runner(self, token_address, min_multiplier=10.0):
        try:
            self._log(f"[RUNNER CHECK] Checking token {token_address[:8]}...")
            price_range = self._get_price_range_in_period(token_address, 30)
            if not price_range:
                self._log(f"[RUNNER CHECK] ❌ No price range found for {token_address[:8]}")
                return None
            if price_range['multiplier'] < min_multiplier:
                self._log(f"[RUNNER CHECK] ❌ Multiplier {price_range['multiplier']:.2f}x < {min_multiplier}x")
                return None

            token_info = self._get_token_detailed_info(token_address)
            if not token_info:
                self._log(f"[RUNNER CHECK] ❌ No token info for {token_address[:8]}")
                return None

            ath_data = self.get_token_ath(token_address)
            self._log(f"[RUNNER CHECK] ✅ Token {token_address[:8]} is a runner with {price_range['multiplier']:.2f}x")
            return {
                'address':       token_address,
                'symbol':        token_info['symbol'],
                'name':          token_info['name'],
                'multiplier':    round(price_range['multiplier'], 2),
                'current_price': token_info['price'],
                'ath_price':     ath_data.get('highest_price', 0) if ath_data else 0,
                'liquidity':     token_info['liquidity']
            }
        except Exception as e:
            self._log(f"[RUNNER CHECK] ❌ Exception: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    # =========================================================================
    # 4-STEP SINGLE TOKEN ANALYSIS
    # =========================================================================

    def analyze_token_professional(self, token_address, token_symbol="UNKNOWN",
                                   min_roi_multiplier=3.0, user_id='default_user'):
        self._log(f"\n{'='*80}")
        self._log(f"4-STEP ANALYSIS: {token_symbol}")
        self._log(f"{'='*80}")

        try:
            all_wallets = set()
            wallet_data = {}

            # ------------------------------------------------------------------
            # STEP 1: Top traders
            # ------------------------------------------------------------------
            self._log("\n[STEP 1] Fetching top traders...")
            url  = f"{self.st_base_url}/top-traders/{token_address}"
            data = self.fetch_with_retry(url, self._get_solanatracker_headers(),
                                         semaphore=self.solana_tracker_semaphore)
            if data:
                traders = data if isinstance(data, list) else []
                self._log(f"✓ Found {len(traders)} top traders")
                for trader in traders:
                    wallet = trader.get('wallet')
                    if wallet:
                        all_wallets.add(wallet)
                        wallet_data[wallet] = {
                            'source':         'top_traders',
                            'pnl_data':       trader,
                            'earliest_entry': None,
                            'entry_price':    None,
                        }

            # ------------------------------------------------------------------
            # STEP 2: First buyers
            # ------------------------------------------------------------------
            self._log("\n[STEP 2] Fetching first buyers...")
            url  = f"{self.st_base_url}/first-buyers/{token_address}"
            data = self.fetch_with_retry(url, self._get_solanatracker_headers(),
                                         semaphore=self.solana_tracker_semaphore)
            if data:
                buyers = data if isinstance(data, list) else data.get('buyers', [])
                first_buyer_wallets = set()
                for buyer in buyers:
                    wallet = buyer.get('wallet')
                    if wallet:
                        first_buyer_wallets.add(wallet)
                        first_buy   = buyer.get('first_buy', {})
                        amount      = first_buy.get('amount', 0)
                        volume_usd  = first_buy.get('volume_usd', 0)
                        entry_price = (volume_usd / amount) if amount > 0 else None

                        if wallet not in all_wallets:
                            wallet_data[wallet] = {
                                'source':         'first_buyers',
                                'pnl_data':       buyer,
                                'earliest_entry': buyer.get('first_buy_time', 0),
                                'entry_price':    entry_price,
                            }
                        else:
                            wallet_data[wallet]['pnl_data']       = buyer
                            wallet_data[wallet]['earliest_entry'] = buyer.get('first_buy_time', 0)
                            wallet_data[wallet]['source']         = 'first_buyers'
                            if entry_price and not wallet_data[wallet].get('entry_price'):
                                wallet_data[wallet]['entry_price'] = entry_price

                new_wallets = first_buyer_wallets - all_wallets
                all_wallets.update(first_buyer_wallets)
                self._log(f"✓ Found {len(buyers)} first buyers ({len(new_wallets)} new)")

            # ------------------------------------------------------------------
            # STEP 3: Top holders
            # ------------------------------------------------------------------
            self._log("\n[STEP 3] Fetching top holders...")
            url  = f"{self.st_base_url}/tokens/{token_address}/holders/paginated"
            data = self.fetch_with_retry(
                url, self._get_solanatracker_headers(),
                params={'limit': 500},
                semaphore=self.solana_tracker_semaphore
            )
            if data and data.get('accounts'):
                holder_wallets = set()
                for account in data['accounts']:
                    wallet = account.get('wallet')
                    if wallet:
                        holder_wallets.add(wallet)
                        if wallet not in all_wallets:
                            wallet_data[wallet] = {
                                'source':         'top_holders',
                                'pnl_data':       None,
                                'earliest_entry': None,
                                'entry_price':    None,
                                'holding_amount': account.get('amount', 0),
                                'holding_usd':    account.get('value', {}).get('usd', 0),
                                'holding_pct':    account.get('percentage', 0),
                            }
                        else:
                            wallet_data[wallet]['holding_amount'] = account.get('amount', 0)
                            wallet_data[wallet]['holding_usd']    = account.get('value', {}).get('usd', 0)
                            wallet_data[wallet]['holding_pct']    = account.get('percentage', 0)

                new_wallets = holder_wallets - all_wallets
                all_wallets.update(holder_wallets)
                self._log(
                    f"✓ Found {len(data['accounts'])} top holders "
                    f"({len(new_wallets)} new | total supply holders: {data.get('total', '?')})"
                )
            else:
                self._log("  Holders endpoint returned no data — continuing without holder source")

            # NOTE: Step 4 (separate entry price fetch) removed.
            # Entry price is now extracted from first_buy field in PnL response (Step 5).

            # ------------------------------------------------------------------
            # STEP 5 (now Step 4): PnL fetch + qualify
            # ------------------------------------------------------------------
            self._log(f"\n[STEP 4] Fetching PnL for {len(all_wallets)} wallets...")

            wallets_with_pnl = []
            wallets_to_fetch = []

            for wallet in all_wallets:
                if wallet_data[wallet].get('pnl_data'):
                    wallets_with_pnl.append(wallet)
                else:
                    wallets_to_fetch.append(wallet)

            self._log(f"✓ {len(wallets_with_pnl)} wallets have PnL "
                      f"(top_traders + first_buyers)")
            self._log(f"→ Fetching PnL for {len(wallets_to_fetch)} holder wallets...")

            qualified_wallets = []

            for wallet in wallets_with_pnl:
                pnl_data = wallet_data[wallet]['pnl_data']
                # Extract entry_price from first_buy if not already present
                if not wallet_data[wallet].get('entry_price'):
                    first_buy  = pnl_data.get('first_buy', {})
                    amount     = first_buy.get('amount', 0)
                    volume_usd = first_buy.get('volume_usd', 0)
                    if amount > 0:
                        wallet_data[wallet]['entry_price']    = volume_usd / amount
                        wallet_data[wallet]['earliest_entry'] = first_buy.get('time')
                self._process_wallet_pnl(wallet, pnl_data, wallet_data,
                                         qualified_wallets, min_roi_multiplier)

            async def _async_fetch_pnls():
                async with aiohttp.ClientSession() as session:
                    sem = AsyncSemaphore(2)
                    tasks = []
                    for wallet in wallets_to_fetch:
                        async def fetch_pnl(w=wallet):
                            async with sem:
                                await asyncio.sleep(random.uniform(0.5, 1.5))  # jitter
                                return await self.async_fetch_with_retry(
                                    session,
                                    f"{self.st_base_url}/pnl/{w}/{token_address}",
                                    self._get_solanatracker_headers()
                                )
                        tasks.append(fetch_pnl())
                    return await asyncio.gather(*tasks)

            if wallets_to_fetch:
                results = asyncio.run(_async_fetch_pnls())
                for wallet, pnl_data in zip(wallets_to_fetch, results):
                    if pnl_data:
                        wallet_data[wallet]['pnl_data'] = pnl_data
                        # Extract entry_price from first_buy in PnL response
                        if not wallet_data[wallet].get('entry_price'):
                            first_buy  = pnl_data.get('first_buy', {})
                            amount     = first_buy.get('amount', 0)
                            volume_usd = first_buy.get('volume_usd', 0)
                            if amount > 0:
                                wallet_data[wallet]['entry_price']    = volume_usd / amount
                                wallet_data[wallet]['earliest_entry'] = first_buy.get('time')
                        self._process_wallet_pnl(wallet, pnl_data, wallet_data,
                                                 qualified_wallets, min_roi_multiplier)

            self._log(f"✓ Found {len(qualified_wallets)} qualified wallets")

            # ------------------------------------------------------------------
            # Score and rank — single token mode
            # ------------------------------------------------------------------
            self._log("\n[SCORING] Ranking by professional score...")
            ath_data  = self.get_token_ath(token_address)
            ath_price = ath_data.get('highest_price', 0) if ath_data else 0
            ath_mcap  = ath_data.get('highest_market_cap', 0) if ath_data else 0

            wallet_results = []
            for wallet_info in qualified_wallets:
                wallet_address = wallet_info['wallet']
                runner_history = self._get_cached_other_runners(
                    wallet_address, current_token=token_address, min_multiplier=10.0
                )
                wallet_info['ath_price'] = ath_price
                scoring_data = self.calculate_wallet_relative_score(wallet_info)

                if scoring_data['professional_score'] >= 90:   tier = 'S'
                elif scoring_data['professional_score'] >= 80: tier = 'A'
                elif scoring_data['professional_score'] >= 70: tier = 'B'
                else:                                          tier = 'C'

                entry_price = wallet_info.get('entry_price')
                entry_mcap = None
                if entry_price and ath_price and ath_price > 0 and ath_mcap:
                    entry_mcap = round((entry_price / ath_price) * ath_mcap, 0)

                wallet_result = {
                    'wallet':                  wallet_address,
                    'source':                  wallet_info['source'],
                    'tier':                    tier,
                    'is_cross_token':          False,
                    'roi_percent':             round((wallet_info['realized_multiplier'] - 1) * 100, 2),
                    'roi_multiplier':          round(wallet_info['realized_multiplier'], 2),
                    'entry_to_ath_multiplier': scoring_data.get('entry_to_ath_multiplier'),
                    'distance_to_ath_pct':     scoring_data.get('distance_to_ath_pct'),  # display only
                    'realized_profit':         wallet_info['realized'],
                    'unrealized_profit':       wallet_info['unrealized'],
                    'total_invested':          wallet_info['total_invested'],
                    'cost_basis':              wallet_info.get('cost_basis', 0),
                    'realized_multiplier':     scoring_data.get('realized_multiplier'),
                    'total_multiplier':        scoring_data.get('total_multiplier'),
                    'professional_score':      scoring_data['professional_score'],
                    'professional_grade':      scoring_data['professional_grade'],
                    'score_breakdown':         scoring_data['score_breakdown'],
                    'runner_hits_30d':         runner_history['stats'].get('total_other_runners', 0),
                    'runner_hits_7d':          runner_history.get('stats_7d', {}).get('total_other_runners', 0),
                    'runner_success_rate':     runner_history['stats'].get('success_rate', 0),
                    'runner_avg_roi':          runner_history['stats'].get('avg_roi', 0),
                    'other_runners':           runner_history['other_runners'][:5],
                    'other_runners_stats':     runner_history['stats'],
                    'runners_7d':              runner_history.get('runners_7d', []),
                    'runners_14d':             runner_history.get('runners_14d', []),
                    'runners_30d':             runner_history.get('runners_30d', []),
                    'stats_7d':                runner_history.get('stats_7d', {}),
                    'stats_14d':               runner_history.get('stats_14d', {}),
                    'stats_30d':               runner_history.get('stats_30d', {}),
                    'first_buy_time':          wallet_info.get('earliest_entry'),
                    'entry_price':             entry_price,
                    'ath_price':               ath_price,
                    'ath_market_cap':          ath_mcap,
                    'entry_market_cap':        entry_mcap,
                    'is_fresh':                True,
                }

                for holder_field in ['holding_amount', 'holding_usd', 'holding_pct']:
                    if wallet_info.get(holder_field):
                        wallet_result[holder_field] = wallet_info[holder_field]

                wallet_results.append(wallet_result)

            wallet_results.sort(key=lambda x: x['professional_score'], reverse=True)
            self._log(f"✅ Analysis complete: {len(wallet_results)} qualified wallets")
            if wallet_results:
                self._log(
                    f"   Top score: {wallet_results[0]['professional_score']} "
                    f"({wallet_results[0]['professional_grade']})"
                )

            return wallet_results

        finally:
            pass

    def _process_wallet_pnl(self, wallet, pnl_data, wallet_data,
                             qualified_wallets, min_roi_multiplier):
        realized       = pnl_data.get('realized', 0)
        unrealized     = pnl_data.get('unrealized', 0)
        total_invested = pnl_data.get('total_invested') or pnl_data.get('totalInvested', 0)
        source         = wallet_data[wallet].get('source', 'unknown')

        if not total_invested or total_invested < 100:
            print(f"[QUALIFY] ❌ {wallet[:8]} [{source}] FAIL — invested=${total_invested:.2f} (min=$100)")
            return False

        realized_multiplier = (realized + total_invested) / total_invested
        total_multiplier    = (realized + unrealized + total_invested) / total_invested

        if realized_multiplier < min_roi_multiplier and total_multiplier < min_roi_multiplier:
            print(
                f"[QUALIFY] ❌ {wallet[:8]} [{source}] FAIL — "
                f"realized={realized_multiplier:.2f}x total={total_multiplier:.2f}x "
                f"(min={min_roi_multiplier:.1f}x) invested=${total_invested:.2f}"
            )
            return False

        earliest_entry = wallet_data[wallet].get('earliest_entry')
        if not earliest_entry:
            earliest_entry = pnl_data.get('first_buy_time', 0)

        print(
            f"[QUALIFY] ✅ {wallet[:8]} [{source}] PASS — "
            f"invested=${total_invested:.2f} "
            f"realized={realized_multiplier:.2f}x total={total_multiplier:.2f}x"
        )

        wallet_entry = {
            'wallet':              wallet,
            'source':              source,
            'realized':            realized,
            'unrealized':          unrealized,
            'total_invested':      total_invested,
            'realized_multiplier': realized_multiplier,
            'total_multiplier':    total_multiplier,
            'earliest_entry':      earliest_entry,
            'entry_price':         wallet_data[wallet].get('entry_price'),
            'cost_basis':          pnl_data.get('cost_basis', 0),
        }

        for holder_field in ['holding_amount', 'holding_usd', 'holding_pct']:
            if wallet_data[wallet].get(holder_field):
                wallet_entry[holder_field] = wallet_data[wallet][holder_field]

        qualified_wallets.append(wallet_entry)
        return True

    # =========================================================================
    # BATCH ANALYSIS
    # =========================================================================

    def _assign_tier(self, runner_count, aggregate_score, tokens_analyzed):
        if tokens_analyzed == 0:
            return 'C'
        participation_rate = runner_count / tokens_analyzed
        if participation_rate >= 0.8 and aggregate_score >= 85:   return 'S'
        elif participation_rate >= 0.6 and aggregate_score >= 75: return 'A'
        elif participation_rate >= 0.4 and aggregate_score >= 65: return 'B'
        else:                                                      return 'C'

    def _calculate_consistency(self, wallet_address, tokens_traded_list):
        if len(tokens_traded_list) < 2:
            return 50
        entry_ratios = []
        for token_address in tokens_traded_list:
            launch_price = self._get_token_launch_price(token_address)
            if not launch_price or launch_price == 0:
                continue
            cached_data = self._get_cached_pnl_and_entry(wallet_address, token_address)
            if not cached_data or not cached_data.get('entry_price'):
                continue
            entry_price = cached_data['entry_price']
            if entry_price == 0:
                continue
            entry_ratios.append(entry_price / launch_price)
        if len(entry_ratios) < 2:
            return 50
        try:
            variance = statistics.variance(entry_ratios)
            return round(max(0, 100 - (variance * 10)), 1)
        except Exception:
            return 50

    def batch_analyze_runners_professional(self, runners_list, min_runner_hits=2,
                                           min_roi_multiplier=3.0, user_id='default_user'):
        self._log(f"\n{'='*80}")
        self._log(f"BATCH ANALYSIS: {len(runners_list)} runners")
        self._log(f"{'='*80}")

        wallet_hits = defaultdict(lambda: {
            'wallet':                None,
            'runners_hit':           [],
            'runners_hit_addresses': set(),
            'roi_details':           [],
            'professional_scores':   [],
            'entry_to_ath_vals':     [],
            'distance_to_ath_vals':  [],
            'roi_multipliers':       [],
            'total_roi_multipliers': [],
            'raw_wallet_results':    [],
        })

        for idx, runner in enumerate(runners_list, 1):
            self._log(f"\n[{idx}/{len(runners_list)}] Analyzing {runner.get('symbol', 'UNKNOWN')}")
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
                    'runner':                  runner['symbol'],
                    'runner_address':          runner['address'],
                    'roi_percent':             wallet['roi_percent'],
                    'roi_multiplier':          wallet['roi_multiplier'],
                    'professional_score':      wallet['professional_score'],
                    'professional_grade':      wallet['professional_grade'],
                    'entry_to_ath_multiplier': wallet.get('entry_to_ath_multiplier'),
                    'distance_to_ath_pct':     wallet.get('distance_to_ath_pct'),  # display only
                    'entry_price':             wallet.get('entry_price'),
                })
                wallet_hits[wallet_addr]['professional_scores'].append(wallet['professional_score'])
                wallet_hits[wallet_addr]['raw_wallet_results'].append(wallet)
                if wallet.get('entry_to_ath_multiplier'):
                    wallet_hits[wallet_addr]['entry_to_ath_vals'].append(wallet['entry_to_ath_multiplier'])
                if wallet.get('distance_to_ath_pct'):
                    wallet_hits[wallet_addr]['distance_to_ath_vals'].append(wallet['distance_to_ath_pct'])
                wallet_hits[wallet_addr]['roi_multipliers'].append(wallet['roi_multiplier'])
                wallet_hits[wallet_addr]['total_roi_multipliers'].append(
                    wallet.get('total_multiplier') or wallet['roi_multiplier']
                )

        cross_token_wallets  = []
        single_token_wallets = []

        for wallet_addr, d in wallet_hits.items():
            runner_count  = len(d['runners_hit'])
            avg_ath       = (
                sum(d['entry_to_ath_vals']) / len(d['entry_to_ath_vals'])
                if d['entry_to_ath_vals'] else None
            )
            avg_total_roi = (
                sum(d['total_roi_multipliers']) / len(d['total_roi_multipliers'])
                if d['total_roi_multipliers'] else 0
            )
            # distance_to_ath_pct is display-only — not used in scoring
            avg_dist = (
                sum(d['distance_to_ath_vals']) / len(d['distance_to_ath_vals'])
                if d['distance_to_ath_vals'] else 0
            )

            if runner_count >= min_runner_hits:
                # Cross-token: 60% log entry timing | 30% log total ROI | 10% consistency
                consistency_score = self._calculate_consistency(
                    wallet_addr, list(d['runners_hit_addresses'])
                )
                entry_score     = _roi_to_score(avg_ath) if avg_ath else 0
                roi_score       = _roi_to_score(avg_total_roi)
                aggregate_score = (
                    0.60 * entry_score +
                    0.30 * roi_score +
                    0.10 * consistency_score
                )
                tier = self._assign_tier(runner_count, aggregate_score, len(runners_list))

                full_history  = self._get_cached_other_runners(wallet_addr)
                outside_batch = [
                    r for r in full_history['other_runners']
                    if r['address'] not in d['runners_hit_addresses']
                ]

                cross_token_wallets.append({
                    'wallet':                      wallet_addr,
                    'is_cross_token':              True,
                    'runner_count':                runner_count,
                    'runners_hit':                 d['runners_hit'],
                    'avg_distance_to_ath_pct':     round(avg_dist, 2),        # display only
                    'avg_entry_to_ath_multiplier': round(avg_ath, 2) if avg_ath else None,
                    'avg_total_roi':               round(avg_total_roi, 2),
                    'consistency_score':           consistency_score,
                    'aggregate_score':             round(aggregate_score, 2),
                    'tier':                        tier,
                    'roi_details':                 d['roi_details'][:5],
                    'outside_batch_runners':       outside_batch[:5],
                    'full_30d_stats':              full_history['stats'],
                    'is_fresh':                    True,
                    'score_breakdown': {
                        'entry_score':       round(0.60 * entry_score, 2),
                        'total_roi_score':   round(0.30 * roi_score, 2),
                        'consistency_score': round(0.10 * consistency_score, 2),
                    }
                })

            else:
                # Single-token: individual professional_score
                best_result = max(d['raw_wallet_results'], key=lambda w: w['professional_score'])
                single_token_wallets.append({
                    **best_result,
                    'is_cross_token': False,
                    'runner_count':   runner_count,
                    'runners_hit':    d['runners_hit'],
                    'roi_details':    d['roi_details'][:5],
                })

        cross_token_wallets.sort(
            key=lambda x: (x['runner_count'], x['aggregate_score']), reverse=True
        )
        single_token_wallets.sort(
            key=lambda x: x['professional_score'], reverse=True
        )

        cross_top       = cross_token_wallets[:20]
        slots_remaining = max(0, 20 - len(cross_top))
        single_fill     = single_token_wallets[:slots_remaining]
        final_results   = cross_top + single_fill

        self._log(
            f"\n✅ Batch complete: {len(cross_top)} cross-token + "
            f"{len(single_fill)} single-token fill = {len(final_results)} total"
        )
        return final_results

    def batch_analyze_tokens(self, tokens, min_roi_multiplier=3.0, user_id='default_user'):
        """Legacy synchronous batch — delegates to batch_analyze_runners_professional."""
        runners = [
            {
                'address': t['address'],
                'symbol':  t.get('ticker', t.get('symbol', 'UNKNOWN')),
            }
            for t in tokens
        ]
        return self.batch_analyze_runners_professional(
            runners, min_runner_hits=2,
            min_roi_multiplier=min_roi_multiplier, user_id=user_id
        )

    # =========================================================================
    # REPLACEMENT FINDER
    # =========================================================================

    def find_replacement_wallets(self, declining_wallet_address, user_id='default_user',
                                 min_professional_score=85, max_results=3):
        declining_profile = self._get_wallet_profile_from_watchlist(user_id, declining_wallet_address)
        if not declining_profile:
            return []
        runners = self.find_trending_runners_enhanced(days_back=30, min_multiplier=5.0, min_liquidity=50000)
        if not runners:
            return []

        all_candidates = []
        for runner in runners[:10]:
            wallets   = self.analyze_token_professional(
                token_address=runner['address'],
                token_symbol=runner['symbol'],
                min_roi_multiplier=3.0,
                user_id=user_id
            )
            qualified = [w for w in wallets if w['professional_score'] >= min_professional_score]
            all_candidates.extend(qualified)

        scored_candidates = []
        for candidate in all_candidates:
            similarity = self._calculate_similarity_score(declining_profile, candidate)
            if similarity['total_score'] > 0.3:
                scored_candidates.append({
                    **candidate,
                    'similarity_score':     similarity['total_score'],
                    'similarity_breakdown': similarity['breakdown'],
                    'why_better':           self._explain_why_better(declining_profile, candidate)
                })

        scored_candidates.sort(
            key=lambda x: (x['similarity_score'] * 0.6 + (x['professional_score'] / 100) * 0.4),
            reverse=True
        )
        return scored_candidates[:max_results]

    def _get_wallet_profile_from_watchlist(self, user_id, wallet_address):
        try:
            from db.watchlist_db import WatchlistDatabase
            db        = WatchlistDatabase()
            watchlist = db.get_wallet_watchlist(user_id)
            wallet_data = next((w for w in watchlist if w['wallet_address'] == wallet_address), None)
            if not wallet_data:
                return None
            tokens_traded = wallet_data.get('tokens_hit', [])
            if not isinstance(tokens_traded, list):
                tokens_traded = [t.strip() for t in str(tokens_traded).split(',')]
            return {
                'wallet_address':     wallet_address,
                'tier':               wallet_data.get('tier', 'C'),
                'professional_score': wallet_data.get('avg_professional_score', 0),
                'tokens_traded':      tokens_traded,
                'avg_roi':            wallet_data.get('avg_roi_to_peak', 0),
                'pump_count':         wallet_data.get('pump_count', 0),
                'consistency_score':  wallet_data.get('consistency_score', 0)
            }
        except Exception as e:
            print(f"⚠️ Error loading wallet profile: {e}")
            return None

    def _calculate_similarity_score(self, declining_profile, candidate):
        declining_tokens = set(declining_profile['tokens_traded'])
        candidate_tokens = {r['symbol'] for r in candidate.get('other_runners', [])}

        if declining_tokens and candidate_tokens:
            overlap     = len(declining_tokens & candidate_tokens)
            total       = len(declining_tokens | candidate_tokens)
            token_score = overlap / total if total > 0 else 0
        else:
            token_score = 0.5

        tier_values          = {'S': 4, 'A': 3, 'B': 2, 'C': 1}
        declining_tier_value = tier_values.get(declining_profile['tier'], 1)
        candidate_tier_value = tier_values.get(candidate.get('tier', 'C'), 1)

        if candidate_tier_value >= declining_tier_value:     tier_score = 1.0
        elif candidate_tier_value == declining_tier_value-1: tier_score = 0.7
        else:                                                tier_score = 0.3

        declining_activity = declining_profile.get('pump_count', 0)
        candidate_activity = candidate.get('runner_hits_30d', 0)
        if declining_activity > 0:
            activity_score = min(candidate_activity / declining_activity, 2.0) / 2.0
        else:
            activity_score = 1.0 if candidate_activity > 0 else 0.5

        consistency_values = {'A+': 1.0, 'A': 0.9, 'B': 0.7, 'C': 0.5, 'D': 0.3}
        consistency_score  = consistency_values.get(candidate.get('consistency_grade', 'C'), 0.5)

        total_score = (
            token_score * 0.40 + tier_score * 0.30 +
            activity_score * 0.20 + consistency_score * 0.10
        )
        return {'total_score': total_score, 'breakdown': {
            'token_overlap':  token_score,
            'tier_match':     tier_score,
            'activity_level': activity_score,
            'consistency':    consistency_score
        }}

    def _explain_why_better(self, declining_profile, candidate):
        reasons = []
        if candidate.get('professional_score', 0) > declining_profile.get('professional_score', 0):
            diff = candidate['professional_score'] - declining_profile['professional_score']
            reasons.append(f"Professional score +{diff:.0f} points higher")
        if candidate.get('runner_hits_30d', 0) > declining_profile.get('pump_count', 0):
            reasons.append(f"{candidate['runner_hits_30d']} runners last 30d")
        if candidate.get('runner_hits_30d', 0) > 0:
            reasons.append("Currently active")
        if candidate.get('consistency_grade') in ['A+', 'A']:
            reasons.append(f"High consistency ({candidate['consistency_grade']})")
        return reasons