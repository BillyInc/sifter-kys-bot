import requests
from datetime import datetime
from collections import defaultdict
import statistics

class WalletPumpAnalyzer:
    """
    Analyzes wallets using ONLY Birdeye API.
    Uses hybrid ALL-TIME HIGH: token_overview → history_price max → OHLCV fallback.
    Improved price extraction and debug logging.
    """
    
    def __init__(self, birdeye_api_key, debug_mode=False):
        self.birdeye_key = birdeye_api_key
        self.birdeye_txs_url = "https://public-api.birdeye.so/defi/v3/token/txs"
        self.birdeye_overview_url = "https://public-api.birdeye.so/defi/token_overview"
        self.birdeye_history_url = "https://public-api.birdeye.so/defi/history_price"
        self.debug_mode = debug_mode  # Control verbose logging
        
    def get_true_ath(self, token_address, chain='solana'):
        """Try official ATH from token_overview"""
        headers = {
            'accept': 'application/json',
            'x-chain': chain,
            'X-API-KEY': self.birdeye_key
        }
        params = {
            'address': token_address,
            'ui_amount_mode': 'raw'
        }

        try:
            resp = requests.get(self.birdeye_overview_url, headers=headers, params=params, timeout=10)
            if resp.status_code != 200:
                print(f"[OVERVIEW] Failed {resp.status_code} for {token_address[:8]}...")
                return None
                
            data = resp.json()
            if not data.get('success') or 'data' not in data:
                print(f"[OVERVIEW] No success/data")
                return None

            overview = data['data']
            ath = overview.get('all_time_high') or overview.get('ath') or 0
            ath_ts = overview.get('all_time_high_timestamp') or overview.get('ath_timestamp') or 0
            
            if ath > 0:
                ath_time = datetime.fromtimestamp(ath_ts).strftime('%Y-%m-%d %H:%M') if ath_ts else "unknown"
                print(f"[TRUE ATH] ${ath:.10f} at {ath_time} (from token_overview)")
                return {'ath': float(ath), 'timestamp': ath_ts or 0}
            else:
                print(f"[OVERVIEW] No ATH value found")
                return None

        except Exception as e:
            print(f"[OVERVIEW REQUEST FAILED] {str(e)}")
            return None
    
    def get_long_history_prices(self, token_address, chain='solana', days_back=30):
        """Fetch long historical prices and return max price + timestamp"""
        headers = {
            'accept': 'application/json',
            'x-chain': chain,
            'X-API-KEY': self.birdeye_key
        }
        
        time_to = int(datetime.now().timestamp())
        time_from = time_to - (days_back * 86400)
        
        params = {
            'address': token_address,
            'address_type': 'token',
            'type': '5m',
            'time_from': time_from,
            'time_to': time_to,
            'ui_amount_mode': 'raw'
        }
        
        try:
            resp = requests.get(self.birdeye_history_url, headers=headers, params=params, timeout=20)
            if resp.status_code != 200:
                print(f"[HISTORY] Failed {resp.status_code}")
                return None
                
            data = resp.json()
            if not data.get('success') or 'data' not in data or 'items' not in data['data']:
                print(f"[HISTORY] No valid data")
                return None
            
            items = data['data']['items']
            if not items:
                print(f"[HISTORY] Empty items")
                return None
            
            max_item = max(items, key=lambda x: x.get('value', 0))
            max_price = max_item['value']
            max_ts = max_item['unixTime']
            
            print(f"[HISTORY ATH] Max ${max_price:.10f} at {datetime.fromtimestamp(max_ts)} "
                  f"({len(items)} points)")
            
            return {'ath': max_price, 'timestamp': max_ts}
            
        except Exception as e:
            print(f"[HISTORY ERROR] {str(e)}")
            return None
    
    def get_pre_pump_buyers(self, token_address, chain, rally_start_unix, 
                           window_minutes_before=35, window_minutes_after=0):
        print(f"\n[BIRDEYE WALLET ANALYSIS] Fetching pre-pump buyers...")
        print(f"  Token: {token_address[:8]}...{token_address[-6:]}")
        
        after_time = rally_start_unix - (window_minutes_before * 60)
        before_time = rally_start_unix + (window_minutes_after * 60)
        
        after_dt = datetime.fromtimestamp(after_time)
        before_dt = datetime.fromtimestamp(before_time)
        rally_dt = datetime.fromtimestamp(rally_start_unix)
        
        print(f"  Window: {after_dt.strftime('%H:%M:%S')} to {before_dt.strftime('%H:%M:%S')}")
        print(f"  Rally Start: {rally_dt.strftime('%H:%M:%S')}")
        
        all_buys = self._fetch_buys_in_window(token_address, chain, after_time, before_time)
        unique_buyers = self._aggregate_by_wallet(all_buys)
        
        print(f"  ✓ {len(all_buys)} buy txs → {len(unique_buyers)} unique wallets")
        return unique_buyers
    
    def _fetch_buys_in_window(self, token_address, chain, after_time, before_time):
        headers = {
            'accept': 'application/json',
            'x-chain': chain,
            'X-API-KEY': self.birdeye_key
        }
        
        params = {
            'address': token_address,
            'tx_type': 'swap',
            'after_time': after_time,
            'before_time': before_time,
            'sort_by': 'block_unix_time',
            'sort_type': 'desc',
            'limit': 100,
            'offset': 0
        }
        
        all_buys = []
        processed_txs = set()  # Track processed transactions to avoid duplicates
        
        while True:
            try:
                response = requests.get(self.birdeye_txs_url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if not data.get('success') or not data.get('data', {}).get('items'):
                    break
                
                items = data['data']['items']
                
                for tx in items:
                    tx_hash = tx.get('tx_hash', '')
                    if tx_hash in processed_txs:
                        continue
                    
                    processed_txs.add(tx_hash)
                    
                    if tx.get('side') == 'buy' or tx.get('tx_type') == 'buy':
                        price = self._extract_token_price(tx, token_address)
                        if price > 0:
                            all_buys.append({
                                'wallet': tx.get('owner', ''),
                                'timestamp': tx.get('block_unix_time', 0),
                                'tx_hash': tx_hash,
                                'volume_usd': tx.get('volume_usd', 0),
                                'price': price
                            })
                
                if len(items) < 100:
                    break
                
                params['offset'] += 100
                if params['offset'] >= 2000:
                    print(f"  ⚠️ Hit safe tx limit (2000), stopping")
                    break
                
            except requests.exceptions.RequestException as e:
                print(f"  ⚠️ Birdeye tx error: {e}")
                break
        
        return all_buys
    
    def _extract_token_price(self, tx, token_address):
        """
        Improved: Try direct price fields, then volume_usd / token_amount fallback
        REDUCED VERBOSE LOGGING
        """
        # Direct price fields (most accurate when present)
        price = (
            tx.get('priceUsd') or
            tx.get('price') or
            tx.get('price_pair') or
            tx.get('token_price_usd')
        )
        
        if price is not None and 0 < price < 10:  # memecoins usually < $10
            if self.debug_mode:
                print(f"[PRICE OK] Direct: ${price:.10f}")
            return float(price)

        # Fallback: volume_usd / token amount
        volume_usd = tx.get('volume_usd', 0)
        token_amount = 0

        for side in ['from', 'to']:
            side_data = tx.get(side, {})
            if side_data.get('address') == token_address:
                token_amount = side_data.get('ui_amount') or side_data.get('amount', 0)
                break

        if token_amount > 0 and volume_usd > 0:
            calc_price = volume_usd / token_amount
            if 0 < calc_price < 10:  # Reasonable price range
                if self.debug_mode:
                    print(f"[PRICE CALC] Volume fallback: ${calc_price:.10f}")
                return calc_price

        if self.debug_mode:
            print(f"[PRICE FAIL] No valid price for tx {tx.get('tx_hash', 'unknown')[:10]}...")
        return 0.00000001  # tiny fallback to avoid division issues
    
    def _aggregate_by_wallet(self, buys):
        wallet_data = defaultdict(lambda: {
            'total_volume_usd': 0,
            'timestamps': [],
            'tx_hashes': [],
            'prices': []
        })
        
        for buy in buys:
            wallet = buy['wallet']
            price = buy['price']
            
            if not wallet or price <= 0.000000001:
                continue
            
            wallet_data[wallet]['total_volume_usd'] += buy['volume_usd']
            wallet_data[wallet]['timestamps'].append(buy['timestamp'])
            wallet_data[wallet]['tx_hashes'].append(buy['tx_hash'])
            wallet_data[wallet]['prices'].append(price)
        
        unique_buyers = []
        
        for wallet, data in wallet_data.items():
            if not data['prices']:
                continue
                
            avg_price = sum(data['prices']) / len(data['prices'])
            first_timestamp = min(data['timestamps'])
            
            unique_buyers.append({
                'wallet': wallet,
                'timestamp': first_timestamp,
                'price': avg_price,
                'total_volume_usd': data['total_volume_usd'],
                'num_buys': len(data['timestamps']),
                'tx_hashes': data['tx_hashes']
            })
        
        return unique_buyers
    
    def calculate_wallet_performance(self, buy_data, global_ath, global_ath_timestamp):
        entry_price = buy_data['price']
        buy_timestamp = buy_data['timestamp']
        
        # Distance (positive only)
        if global_ath > 0 and entry_price > 0:
            distance_to_ath = ((global_ath - entry_price) / global_ath) * 100
            distance_to_ath = max(distance_to_ath, 0.0)
        else:
            distance_to_ath = 0.0
        
        # ROI (positive only)
        if entry_price > 0 and global_ath > 0:
            roi_to_ath = ((global_ath / entry_price) - 1) * 100
            roi_to_ath = max(roi_to_ath, 0.0)
        else:
            roi_to_ath = 0.0
        
        hours_to_ath = max((global_ath_timestamp - buy_timestamp) / 3600, 0)
        
        if self.debug_mode:
            print(f"[PERF DEBUG] Entry: ${entry_price:.10f} | ATH: ${global_ath:.10f} | "
                  f"Dist: {distance_to_ath:.2f}% | ROI: {roi_to_ath:.2f}%")
        
        return {
            'wallet': buy_data['wallet'],
            'num_buys': buy_data['num_buys'],
            'entry_price': entry_price,
            'distance_to_ath_pct': round(distance_to_ath, 2),
            'roi_to_ath_pct': round(roi_to_ath, 2),
            'hours_to_ath': round(hours_to_ath, 2),
            'total_volume_usd': round(buy_data['total_volume_usd'], 2),
            'tx_hashes': buy_data['tx_hashes']
        }
    
    def analyze_multi_token_wallets(self, token_rally_data, 
                                   window_minutes_before=35,
                                   window_minutes_after=0,
                                   min_pump_count=3):
        print(f"\n{'='*100}")
        print(f"MULTI-TOKEN WALLET ANALYSIS - HYBRID ATH VERSION")
        print(f"Analyzing {len(token_rally_data)} tokens")
        print(f"{'='*100}\n")
        
        wallet_stats = defaultdict(lambda: {
            'pump_count': 0,
            'distances_to_ath': [],
            'rois': [],
            'hours_to_ath': [],
            'tokens_hit': set(),
            'total_buys': 0,
            'total_volume_usd': 0,
            'rally_details': []
        })
        
        for token_data in token_rally_data:
            token = token_data['token']
            rallies = token_data['rallies']
            ohlcv_data = token_data.get('ohlcv_data', [])
            
            if not ohlcv_data:
                print(f"\n⚠️ No OHLCV for {token['ticker']}, skipping...")
                continue
            
            # === IMPROVED ATH LOGIC ===
            # First, check OHLCV data for ATH (most accurate for recent pumps)
            all_closes = [c['c'] for c in ohlcv_data if c.get('c', 0) > 0]
            
            if all_closes:
                ohlcv_ath = max(all_closes)
                ohlcv_ath_candle = max(ohlcv_data, key=lambda c: c.get('c', 0))
                ohlcv_ath_timestamp = ohlcv_ath_candle.get('unix_time', 0)
                print(f"\n[TOKEN] {token['ticker']} ({token['name']})")
                print(f"  Mint: {token['address'][:8]}...")
                print(f"  📊 OHLCV ATH: ${ohlcv_ath:.10f} at {datetime.fromtimestamp(ohlcv_ath_timestamp) if ohlcv_ath_timestamp else 'unknown'}")
            
            # === HYBRID ATH LOGIC ===
            ath_info = self.get_true_ath(token['address'], token_data.get('chain', 'solana'))

            if ath_info and ath_info['ath'] > 0:
                global_ath = ath_info['ath']
                global_ath_timestamp = ath_info['timestamp']
                ath_source = "token_overview (official)"
                
            else:
                print(f"  [ATH] No overview ATH → trying history_price...")
                history_ath = self.get_long_history_prices(
                    token['address'],
                    chain=token_data.get('chain', 'solana'),
                    days_back=90  # Increased to catch older pumps
                )
                
                if history_ath and history_ath['ath'] > 0:
                    global_ath = history_ath['ath']
                    global_ath_timestamp = history_ath['timestamp']
                    ath_source = "history_price max"
                else:
                    print(f"  [ATH] history_price failed → OHLCV fallback")
                    global_ath = ohlcv_ath if 'ohlcv_ath' in locals() else 0.0
                    global_ath_timestamp = ohlcv_ath_timestamp if 'ohlcv_ath_timestamp' in locals() else 0
                    ath_source = "OHLCV max close"
            
            print(f"  🏆 GLOBAL ATH: ${global_ath:.10f} at {datetime.fromtimestamp(global_ath_timestamp) if global_ath_timestamp else 'unknown'}")
            print(f"  Source: {ath_source}")
            print(f"  Rallies: {len(rallies)}")
            
            for idx, rally in enumerate(rallies, 1):
                rally_start = rally['window'][0]['unix_time']
                rally_time = datetime.fromtimestamp(rally_start)
                
                buyers = self.get_pre_pump_buyers(
                    token_address=token['address'],
                    chain=token_data.get('chain', 'solana'),
                    rally_start_unix=rally_start,
                    window_minutes_before=window_minutes_before,
                    window_minutes_after=window_minutes_after
                )
                
                for buy_data in buyers:
                    wallet = buy_data['wallet']
                    
                    perf = self.calculate_wallet_performance(
                        buy_data, global_ath, global_ath_timestamp
                    )
                    
                    wallet_stats[wallet]['pump_count'] += 1
                    wallet_stats[wallet]['distances_to_ath'].append(perf['distance_to_ath_pct'])
                    wallet_stats[wallet]['rois'].append(perf['roi_to_ath_pct'])
                    wallet_stats[wallet]['hours_to_ath'].append(perf['hours_to_ath'])
                    wallet_stats[wallet]['tokens_hit'].add(token['ticker'])
                    wallet_stats[wallet]['total_buys'] += perf['num_buys']
                    wallet_stats[wallet]['total_volume_usd'] += perf['total_volume_usd']
                    wallet_stats[wallet]['rally_details'].append({
                        'token': token['ticker'],
                        'rally_date': rally_time.strftime('%Y-%m-%d %H:%M'),
                        'distance_pct': perf['distance_to_ath_pct'],
                        'roi_pct': perf['roi_to_ath_pct'],
                        'entry_price': perf['entry_price'],
                        'global_ath': global_ath,
                        'hours_to_ath': perf['hours_to_ath']
                    })
        
        ranked = self._rank_wallets(wallet_stats, min_pump_count)
        
        print(f"\nRANKING COMPLETE - {len(ranked)} qualified wallets")
        return ranked
    
    def _rank_wallets(self, wallet_stats, min_pump_count):
        ranked = []
        
        for wallet, stats in wallet_stats.items():
            if stats['pump_count'] < min_pump_count:
                continue
            
            avg_distance = statistics.mean(stats['distances_to_ath']) if stats['distances_to_ath'] else 0
            avg_roi = statistics.mean(stats['rois']) if stats['rois'] else 0
            avg_hours = statistics.mean(stats['hours_to_ath']) if stats['hours_to_ath'] else 0
            
            stdev_distance = statistics.stdev(stats['distances_to_ath']) if len(stats['distances_to_ath']) > 1 else 0
            consistency_score = max(0, 100 - stdev_distance)
            
            tier = self._assign_tier(stats['pump_count'], avg_distance, stdev_distance)
            
            ranked.append({
                'wallet': wallet,
                'tier': tier,
                'pump_count': stats['pump_count'],
                'tokens_hit': len(stats['tokens_hit']),
                'token_list': sorted(list(stats['tokens_hit'])),
                'avg_distance_to_ath_pct': round(avg_distance, 2),
                'avg_roi_to_ath_pct': round(avg_roi, 2),
                'avg_hours_to_ath': round(avg_hours, 2),
                'consistency_score': round(consistency_score, 2),
                'stdev_distance': round(stdev_distance, 2),
                'total_buys': stats['total_buys'],
                'total_volume_usd': round(stats['total_volume_usd'], 2),
                'rally_history': stats['rally_details'][:10]
            })
        
        ranked.sort(
            key=lambda x: (
                x['pump_count'] *
                x['avg_distance_to_ath_pct'] *
                x['consistency_score']
            ),
            reverse=True
        )
        
        return ranked
    
    def _assign_tier(self, pump_count, avg_distance, stdev):
        if pump_count >= 10 and avg_distance >= 75 and stdev < 15:
            return 'S'
        elif pump_count >= 6 and avg_distance >= 60 and stdev < 25:
            return 'A'
        elif pump_count >= 3 and avg_distance >= 45:
            return 'B'
        else:
            return 'C'
    
    def display_top_wallets(self, ranked_wallets, top_n=20):
        print(f"\n{'='*100}")
        print(f"TOP {min(top_n, len(ranked_wallets))} SMART MONEY WALLETS")
        print(f"{'='*100}\n")
        
        for idx, w in enumerate(ranked_wallets[:top_n], 1):
            print(f"#{idx} - TIER {w['tier']}")
            print(f"Wallet: {w['wallet']}")
            print(f"Pumps Hit: {w['pump_count']}")
            print(f"Tokens: {', '.join(w['token_list'])}")
            print(f"Avg Distance to ATH: {w['avg_distance_to_ath_pct']}%")
            print(f"Avg ROI to ATH: {w['avg_roi_to_ath_pct']}%")
            print(f"Avg Hours to ATH: {w['avg_hours_to_ath']}h")
            print(f"Consistency: {w['consistency_score']}/100")
            print(f"Total Volume: ${w['total_volume_usd']:,.2f}")
            print(f"--- Recent Rallies ---")
            for r in w['rally_history'][:5]:
                print(f"  • {r['token']} {r['rally_date']}: "
                      f"Entry ${r['entry_price']:.8f} → ATH ${r['global_ath']:.8f} "
                      f"({r['distance_pct']}% dist, {r['roi_pct']}% ROI)")
            print()