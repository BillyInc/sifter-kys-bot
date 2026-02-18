"""
wallet_monitor.py - Real-time Wallet Activity Monitor
Continuously polls Solana Tracker API for transactions from watched wallets
Creates notifications when activity matches user alert settings
Supports Telegram alerts integration

Uses Supabase for persistent storage.
"""

import requests
import time
from datetime import datetime
from collections import defaultdict
import threading
from typing import Optional, TYPE_CHECKING, List, Dict

from services.supabase_client import get_supabase_client, SCHEMA_NAME

if TYPE_CHECKING:
    from services.telegram_notifier import TelegramNotifier


class WalletActivityMonitor:
    """
    Monitors wallets in real-time and creates notifications.
    Runs as a background service polling Solana Tracker API.
    Uses Supabase for data persistence.
    """

    def __init__(self, solanatracker_api_key, poll_interval=120,
                 telegram_notifier: Optional['TelegramNotifier'] = None,
                 db_path: str = None):  # db_path kept for backward compatibility
        self.solanatracker_key = solanatracker_api_key
        self.poll_interval = poll_interval  # seconds (default: 2 minutes)
        self.solanatracker_trades_url = "https://data.solanatracker.io/wallet"
        self.running = False
        self.monitor_thread = None

        # Supabase client
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME

        # Telegram notifier for sending alerts
        self.telegram_notifier = telegram_notifier

        # NEW: Multi-wallet signal buffering
        self.pending_signals = {}  # {token_address: [list_of_trades]}
        self.buffer_lock = threading.Lock()

        telegram_status = "Enabled" if telegram_notifier else "Disabled"
        print(f"""
╔══════════════════════════════════════════════════════════════════╗
║           WALLET ACTIVITY MONITOR - INITIALIZED                  ║
╚══════════════════════════════════════════════════════════════════╝
  📊 Database: Supabase ({self.schema})
  🔄 Poll Interval: {poll_interval}s ({poll_interval/60:.1f} minutes)
  🔑 Solana Tracker API: Configured
  📱 Telegram Alerts: {telegram_status}
""")

    def _table(self, name: str):
        """Get table reference with schema."""
        return self.supabase.schema(self.schema).table(name)

    def start(self):
        """Start the monitoring service in a background thread"""
        if self.running:
            print("⚠️ Monitor already running")
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print(f"✅ Wallet monitor started (polling every {self.poll_interval/60:.1f} min)")

    def stop(self):
        """Stop the monitoring service"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        print("🛑 Wallet monitor stopped")

    def _monitor_loop(self):
        """Main monitoring loop - runs continuously"""
        print(f"\n{'='*80}")
        print(f"🚀 MONITORING STARTED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if self.telegram_notifier:
            print(f"📱 Telegram alerts: ENABLED")
        print(f"{'='*80}\n")

        while self.running:
            try:
                cycle_start = time.time()

                # Get all wallets that need monitoring
                wallets_to_monitor = self._get_monitored_wallets()

                if not wallets_to_monitor:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] No wallets to monitor, sleeping...")
                    time.sleep(self.poll_interval)
                    continue

                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Monitoring {len(wallets_to_monitor)} wallets...")

                # Check each wallet for new activity
                for wallet_info in wallets_to_monitor:
                    if not self.running:
                        break

                    self._check_wallet_activity(wallet_info)

                # Update cycle stats
                cycle_duration = time.time() - cycle_start
                print(f"✓ Cycle complete in {cycle_duration:.1f}s")

                # Sleep until next poll
                sleep_time = max(0, self.poll_interval - cycle_duration)
                if sleep_time > 0:
                    print(f"💤 Sleeping {sleep_time:.1f}s until next cycle...\n")
                    time.sleep(sleep_time)

            except Exception as e:
                print(f"\n❌ ERROR in monitor loop: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(30)  # Brief pause before retrying

    def _get_monitored_wallets(self) -> List[Dict]:
        """Get all wallets that have alerts enabled from any user"""
        try:
            # Get unique wallets with alert settings from all users
            result = self._table('wallet_watchlist').select(
                'wallet_address, tier, alert_enabled'
            ).eq('alert_enabled', True).execute()

            wallets = []
            seen_addresses = set()

            for row in result.data:
                addr = row['wallet_address']
                if addr not in seen_addresses:
                    seen_addresses.add(addr)

                    # Get monitor status for this wallet
                    status_result = self._table('wallet_monitor_status').select(
                        'last_checked_at, last_activity_at'
                    ).eq('wallet_address', addr).limit(1).execute()

                    status = status_result.data[0] if status_result.data else {}

                    wallets.append({
                        'wallet_address': addr,
                        'tier': row.get('tier'),
                        'last_checked_at': status.get('last_checked_at'),
                        'last_activity_at': status.get('last_activity_at')
                    })

            # Sort by last_checked_at (oldest first)
            wallets.sort(key=lambda x: x.get('last_checked_at') or 0)

            return wallets

        except Exception as e:
            print(f"[MONITOR] Error getting monitored wallets: {e}")
            return []

    def _get_user_settings(self, user_id: str) -> Dict:
        """Fetch user settings from database."""
        try:
            result = self._table('user_settings').select(
                'min_buy_usd'
            ).eq('user_id', user_id).limit(1).execute()
            
            if result.data:
                return result.data[0]
            return {'min_buy_usd': 50.0}
        except Exception as e:
            print(f"[MONITOR] Error fetching user settings: {e}")
            return {'min_buy_usd': 50.0}

    def _check_wallet_activity(self, wallet_info):
        """Check a single wallet for new transactions - ENHANCED"""
        wallet_address = wallet_info['wallet_address']
        last_checked = wallet_info.get('last_checked_at')

        # ✅ FIX: Handle both ISO strings and Unix timestamps
        if last_checked:
            try:
                if isinstance(last_checked, str):
                    dt = datetime.fromisoformat(last_checked.replace('Z', '+00:00'))
                    last_checked_epoch = int(dt.timestamp())
                else:
                    last_checked_epoch = int(last_checked)
            except:
                last_checked_epoch = 0
        else:
            last_checked_epoch = 0

        lookback_buffer = 300
        after_time = max(0, last_checked_epoch - lookback_buffer)
        before_time = int(time.time())

        try:
            # Fetch ALL recent trades (not just first buys)
            transactions = self._fetch_wallet_all_trades(
                wallet_address,
                after_time=after_time,
                before_time=before_time
            )

            if transactions:
                print(f"  {wallet_address[:8]}... → {len(transactions)} new tx(s)")

                new_activities = []
                tokens_bought = defaultdict(list)  # Track buys by token

                for tx in transactions:
                    activity_id = self._save_wallet_activity(tx, wallet_address)
                    if activity_id:
                        new_activities.append({
                            'activity_id': activity_id,
                            'tx': tx
                        })

                        # Track buys for multi-wallet detection
                        if tx.get('side') == 'buy':
                            tokens_bought[tx.get('token_address')].append({
                                'wallet': wallet_address,
                                'tier': wallet_info.get('tier', 'C'),
                                'usd_value': tx.get('usd_value', 0)
                            })

                # Create notifications for users watching this wallet
                if new_activities:
                    self._create_notifications_for_wallet(wallet_address, new_activities)

                # Check for multi-wallet signals using buffering system
                for token_address, wallets_buying in tokens_bought.items():
                    self._buffer_multi_wallet_signal(token_address, wallets_buying, wallet_info)

            # ✅ FIX: Pass Unix timestamps
            self._update_monitor_status(
                wallet_address,
                last_checked_at=int(time.time()),  # ✅ Unix timestamp
                last_activity_at=int(time.time()) if transactions else None,  # ✅ Unix timestamp
                success=True
            )

        except Exception as e:
            print(f"  ❌ Error checking {wallet_address[:8]}...: {e}")
            self._update_monitor_status(
                wallet_address,
                last_checked_at=int(time.time()),  # ✅ Unix timestamp
                success=False,
                error_message=str(e)
            )

    def _buffer_multi_wallet_signal(self, token_address: str, wallets_buying: List[Dict], wallet_info: Dict):
        """Buffer multi-wallet signals with 60s window for grouping."""
        with self.buffer_lock:
            if token_address not in self.pending_signals:
                self.pending_signals[token_address] = []
                # Start 60s window to group other watchlist buys
                threading.Timer(60.0, self._flush_multi_signal, [token_address]).start()
            
            for wallet_buy in wallets_buying:
                self.pending_signals[token_address].append({
                    'wallet': wallet_buy['wallet'],
                    'tier': wallet_buy['tier'],
                    'usd_value': wallet_buy['usd_value']
                })

    def _flush_multi_signal(self, token_address: str):
        """Sends the accumulated signals after the 60s window."""
        with self.buffer_lock:
            trades = self.pending_signals.pop(token_address, [])
        
        if len(trades) >= 2:
            # Calculate signal strength
            signal_strength = 0
            tier_weights = {'S': 4, 'A': 3, 'B': 2, 'C': 1}

            for trade in trades:
                signal_strength += tier_weights.get(trade['tier'], 1)

            # Strong signal if 2+ wallets AND combined strength ≥ 5
            if signal_strength >= 5:
                signal = {
                    'token_address': token_address,
                    'signal_strength': signal_strength,
                    'wallet_count': len(trades),
                    'wallets': trades,
                    'timestamp': int(time.time())
                }
                self._create_signal_alert(signal)

    def _fetch_wallet_all_trades(self, wallet_address, after_time, before_time):
        """
        ✅ UPDATED: Fetch ALL trades (buys AND sells) for a wallet using Solana Tracker API
        """
        url = f"{self.solanatracker_trades_url}/{wallet_address}/trades"
        headers = {
            'accept': 'application/json',
            'x-api-key': self.solanatracker_key
        }
        params = {
            'since_time': after_time * 1000,  # Convert to ms
            'limit': 100
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                raw_trades = data.get('trades', [])
                
                # ✅ Normalize Solana Tracker response format
                normalized_trades = []
                for trade in raw_trades:
                    normalized_trades.append({
                        'token_address': trade.get('token_address') or trade.get('tokenAddress'),
                        'token_ticker': trade.get('symbol') or trade.get('tokenSymbol'),
                        'token_name': trade.get('token_name') or trade.get('tokenName'),
                        'side': trade.get('type', '').lower(),  # 'buy' or 'sell'
                        'token_amount': float(trade.get('token_amount', 0) or trade.get('tokenAmount', 0)),
                        'usd_value': float(trade.get('sol_amount', 0) or trade.get('solAmount', 0)) * 150,  # Approximate USD
                        'price': float(trade.get('price', 0)),
                        'tx_hash': trade.get('signature') or trade.get('tx_hash'),
                        'block_time': int(trade.get('timestamp', 0) / 1000) if trade.get('timestamp') else int(time.time()),
                        'dex': trade.get('dex', 'unknown')
                    })
                
                return normalized_trades
            else:
                print(f"    ⚠️ Solana Tracker API returned status {response.status_code}")
                
        except Exception as e:
            print(f"    ❌ Error fetching trades from Solana Tracker: {e}")

        return []

    def _detect_multi_wallet_signal(self, token_address, wallets_buying):
        """Detect if multiple high-tier wallets bought same token"""
        if len(wallets_buying) < 2:
            return None

        # Calculate signal strength
        signal_strength = 0
        tier_weights = {'S': 4, 'A': 3, 'B': 2, 'C': 1}

        for wallet_info in wallets_buying:
            signal_strength += tier_weights.get(wallet_info['tier'], 1)

        # Strong signal if 2+ wallets AND combined strength ≥ 5
        if signal_strength >= 5:
            return {
                'token_address': token_address,
                'signal_strength': signal_strength,
                'wallet_count': len(wallets_buying),
                'wallets': wallets_buying,
                'timestamp': int(time.time())
            }

        return None

    def _create_signal_alert(self, signal):
        """Create alert for multi-wallet signal"""
        print(f"  🚨 MULTI-WALLET SIGNAL: {signal['wallet_count']} wallets bought {signal['token_address'][:8]}...")

        try:
            # Get all users watching any of these wallets
            wallet_addresses = [w['wallet'] for w in signal['wallets']]

            result = self._table('wallet_watchlist').select('user_id').in_(
                'wallet_address', wallet_addresses
            ).eq('alert_enabled', True).execute()

            user_ids = list(set(row['user_id'] for row in result.data))

            for user_id in user_ids:
                # Queue Telegram alert
                self._send_telegram_alert(user_id, 'multi_wallet', signal)

        except Exception as e:
            print(f"  ⚠️ Error creating signal alert: {e}")

    def _save_wallet_activity(self, tx, wallet_address) -> Optional[int]:
        """Save transaction to wallet_activity table"""
        try:
            # Check if tx_hash already exists
            existing = self._table('wallet_activity').select('id').eq(
                'signature', tx.get('tx_hash')
            ).limit(1).execute()

            if existing.data:
                # Already exists
                return None

            result = self._table('wallet_activity').insert({
                'wallet_address': wallet_address,
                'token_address': tx.get('token_address'),
                'token_ticker': tx.get('token_ticker'),
                'token_name': tx.get('token_name'),
                'side': tx.get('side'),
                'amount': tx.get('token_amount', 0),
                'usd_value': tx.get('usd_value', 0),
                'price_per_token': tx.get('price', 0),
                'signature': tx.get('tx_hash'),
                'block_time': datetime.fromtimestamp(tx.get('block_time', time.time())).isoformat()
            }).execute()

            if result.data:
                return result.data[0]['id']
            return None

        except Exception as e:
            print(f"    ⚠️ Error saving activity: {e}")
            return None

    def _get_wallet_info(self, user_id: str, wallet_address: str) -> dict:
        """Get wallet tier and stats from watchlist for Telegram alerts"""
        try:
            result = self._table('wallet_watchlist').select(
                'tier, consistency_score'
            ).eq('user_id', user_id).eq('wallet_address', wallet_address).limit(1).execute()

            if result.data:
                row = result.data[0]
                return {'tier': row.get('tier', 'C'), 'consistency_score': row.get('consistency_score', 0)}

            return {'tier': 'C', 'consistency_score': 0}

        except Exception as e:
            print(f"[MONITOR] Error getting wallet info: {e}")
            return {'tier': 'C', 'consistency_score': 0}

    def _send_telegram_alert(self, user_id: str, alert_type: str, alert_data: Dict):
        """Queue Telegram alert for background sending"""
        if not self.telegram_notifier:
            return
        
        # ✅ Custom Threshold Check
        if alert_type == 'trade':
            settings = self._get_user_settings(user_id)
            if alert_data.get('usd_value', 0) < settings.get('min_buy_usd', 50.0):
                print(f"    ⏭️ Trade below user threshold: ${alert_data.get('usd_value')}")
                return
        
        # ✅ Use RQ queue if available (production)
        try:
            from flask import current_app
            q = current_app.config.get('RQ_QUEUE')
            
            if q:
                q.enqueue('tasks.send_telegram_alert_async', 
                          user_id, alert_type, alert_data)
                print(f"[WALLET MONITOR] ✓ Alert queued for {user_id[:8]}...")
            else:
                # Fallback: Send directly (local dev)
                self._send_alert_direct(user_id, alert_type, alert_data)
        except Exception as e:
            print(f"[WALLET MONITOR] ⚠️ Alert queue failed: {e}")
            # Fallback: Send directly
            self._send_alert_direct(user_id, alert_type, alert_data)

    def _send_alert_direct(self, user_id: str, alert_type: str, alert_data: Dict):
        """Direct send (fallback)"""
        if alert_type == 'trade':
            self._send_trade_alert_direct(user_id, alert_data)
        elif alert_type == 'multi_wallet':
            self.telegram_notifier.send_multi_wallet_signal_alert(user_id, alert_data)

    def _send_trade_alert_direct(self, user_id: str, tx: dict):
        """Send direct trade alert"""
        try:
            wallet_address = tx.get('wallet_address', '')
            
            # Get wallet tier/stats from watchlist
            wallet_info = self._get_wallet_info(user_id, wallet_address)

            # Format alert payload
            alert_payload = {
                'wallet': {
                    'address': wallet_address,
                    'tier': wallet_info.get('tier', 'C'),
                    'consistency_score': wallet_info.get('consistency_score', 0)
                },
                'action': tx.get('side', 'buy'),
                'token': {
                    'address': tx.get('token_address', ''),
                    'symbol': tx.get('token_ticker', 'UNKNOWN'),
                    'name': tx.get('token_name', 'Unknown')
                },
                'trade': {
                    'amount_tokens': tx.get('token_amount', 0),
                    'amount_usd': tx.get('usd_value', 0),
                    'price': tx.get('price', 0),
                    'tx_hash': tx.get('tx_hash', ''),
                    'dex': tx.get('dex', 'unknown'),
                    'timestamp': tx.get('block_time', int(time.time()))
                },
                'links': {
                    'solscan': f"https://solscan.io/tx/{tx.get('tx_hash', '')}",
                    'birdeye': f"https://birdeye.so/token/{tx.get('token_address', '')}",
                    'dexscreener': f"https://dexscreener.com/solana/{tx.get('token_address', '')}"
                }
            }

            # Send to Telegram
            self.telegram_notifier.send_wallet_alert(user_id, alert_payload, tx.get('activity_id'))
            print(f"    📱 Telegram alert sent to user {user_id}")

        except Exception as e:
            print(f"    ⚠️ Error sending Telegram alert: {e}")

    def _create_notifications_for_wallet(self, wallet_address, activities):
        """Create notifications for all users watching this wallet"""
        try:
            # Get all users watching this wallet with their alert settings
            result = self._table('wallet_watchlist').select(
                'user_id, alert_enabled, alert_threshold_usd'
            ).eq('wallet_address', wallet_address).eq('alert_enabled', True).execute()

            watchers = result.data

            if not watchers:
                return

            notifications_created = 0

            for activity in activities:
                tx = activity['tx']
                activity_id = activity['activity_id']

                for watcher in watchers:
                    # Check if transaction meets user's alert criteria
                    if self._should_notify(tx, watcher):
                        try:
                            self._table('wallet_notifications').insert({
                                'user_id': watcher['user_id'],
                                'wallet_address': wallet_address,
                                'notification_type': tx.get('side', 'trade'),
                                'title': f"{tx.get('side', 'Trade').upper()}: {tx.get('token_ticker', 'UNKNOWN')}",
                                'message': f"${tx.get('usd_value', 0):.2f} {tx.get('side', 'trade')}",
                                'metadata': {
                                    'activity_id': activity_id,
                                    'token_address': tx.get('token_address'),
                                    'tx_hash': tx.get('tx_hash'),
                                    'usd_value': tx.get('usd_value', 0)
                                }
                            }).execute()

                            notifications_created += 1

                            # Send Telegram alert
                            if self.telegram_notifier:
                                tx['wallet_address'] = wallet_address
                                tx['activity_id'] = activity_id
                                self._send_telegram_alert(
                                    watcher['user_id'],
                                    'trade',
                                    tx
                                )

                        except Exception as e:
                            print(f"    ⚠️ Error creating notification: {e}")

            if notifications_created > 0:
                print(f"    🔔 Created {notifications_created} notification(s)")

        except Exception as e:
            print(f"[MONITOR] Error creating notifications: {e}")

    def _should_notify(self, tx, settings):
        """Determine if user should be notified about this transaction"""
        usd_value = tx.get('usd_value', 0)
        threshold = settings.get('alert_threshold_usd', 100)

        # Check minimum USD value
        if usd_value < threshold:
            return False

        return True

    def _update_monitor_status(self, wallet_address, last_checked_at,
                               last_activity_at=None, success=True, error_message=None):
        """Update monitoring status for a wallet"""
        try:
            # ✅ FIX: Convert ISO strings to Unix timestamps
            if isinstance(last_checked_at, str):
                last_checked_at = int(datetime.fromisoformat(last_checked_at.replace('Z', '+00:00')).timestamp())
            
            if last_activity_at and isinstance(last_activity_at, str):
                last_activity_at = int(datetime.fromisoformat(last_activity_at.replace('Z', '+00:00')).timestamp())
            
            # Check if status exists
            existing = self._table('wallet_monitor_status').select('wallet_address').eq(
                'wallet_address', wallet_address
            ).limit(1).execute()

            if existing.data:
                # Update existing status
                update_data = {
                    'last_checked_at': last_checked_at,
                    'updated_at': int(datetime.utcnow().timestamp())  # ✅ FIX: Unix timestamp
                }

                if success:
                    update_data['error_count'] = 0
                    update_data['last_error'] = None
                    if last_activity_at:
                        update_data['last_activity_at'] = last_activity_at
                else:
                    update_data['last_error'] = error_message

                self._table('wallet_monitor_status').update(update_data).eq(
                    'wallet_address', wallet_address
                ).execute()

                # Increment check_count with raw SQL via RPC
                self.supabase.rpc('increment_check_count', {
                    'p_wallet_address': wallet_address,
                    'p_error_increment': 0 if success else 1
                }).execute()

            else:
                # Insert new status
                self._table('wallet_monitor_status').insert({
                    'wallet_address': wallet_address,
                    'last_checked_at': last_checked_at,
                    'last_activity_at': last_activity_at,
                    'check_count': 1,
                    'error_count': 0 if success else 1,
                    'last_error': None if success else error_message,
                    'is_active': True
                }).execute()

        except Exception as e:
            print(f"[MONITOR] Error updating status: {e}")

    def get_monitoring_stats(self) -> Dict:
        """Get current monitoring statistics"""
        try:
            # Active wallets being monitored
            active_result = self._table('wallet_watchlist').select(
                'wallet_address', count='exact'
            ).eq('alert_enabled', True).execute()
            active_wallets = active_result.count or 0

            # Recent activity (last hour)
            one_hour_ago = datetime.utcfromtimestamp(time.time() - 3600).isoformat()
            activity_result = self._table('wallet_activity').select(
                'id', count='exact'
            ).gte('created_at', one_hour_ago).execute()
            recent_activities = activity_result.count or 0

            # Pending notifications
            pending_result = self._table('wallet_notifications').select(
                'id', count='exact'
            ).eq('is_read', False).execute()
            pending_notifications = pending_result.count or 0

            # Monitor health
            health_result = self._table('wallet_monitor_status').select(
                'wallet_address, error_count, check_count'
            ).execute()

            total_monitored = len(health_result.data)
            with_errors = sum(1 for r in health_result.data if (r.get('error_count') or 0) > 0)
            avg_checks = sum(r.get('check_count', 0) for r in health_result.data) / max(total_monitored, 1)

            return {
                'active_wallets': active_wallets,
                'recent_activities': recent_activities,
                'pending_notifications': pending_notifications,
                'monitor_health': {
                    'total_monitored': total_monitored,
                    'with_errors': with_errors,
                    'avg_checks': round(avg_checks, 1)
                },
                'running': self.running,
                'poll_interval_seconds': self.poll_interval,
                'telegram_enabled': self.telegram_notifier is not None
            }

        except Exception as e:
            print(f"[MONITOR] Error getting stats: {e}")
            return {
                'active_wallets': 0,
                'recent_activities': 0,
                'pending_notifications': 0,
                'monitor_health': {'total_monitored': 0, 'with_errors': 0, 'avg_checks': 0},
                'running': self.running,
                'poll_interval_seconds': self.poll_interval,
                'telegram_enabled': self.telegram_notifier is not None
            }

    def force_check_wallet(self, wallet_address):
        """Manually trigger a check for a specific wallet (for testing/debugging)"""
        wallet_info = {
            'wallet_address': wallet_address,
            'tier': None,
            'last_checked_at': None,
            'last_activity_at': None
        }

        print(f"\n🔍 Force checking wallet: {wallet_address[:8]}...")
        self._check_wallet_activity(wallet_info)
        print(f"✅ Check complete\n")


# =============================================================================
# HELPER FUNCTIONS FOR API INTEGRATION (Using Supabase)
# =============================================================================

def get_recent_wallet_activity(wallet_address=None, limit=50, db_path=None) -> List[Dict]:
    """Get recent wallet activity (for API endpoint)"""
    try:
        supabase = get_supabase_client()
        query = supabase.schema(SCHEMA_NAME).table('wallet_activity').select('*')

        if wallet_address:
            query = query.eq('wallet_address', wallet_address)

        result = query.order('block_time', desc=True).limit(limit).execute()
        return result.data

    except Exception as e:
        print(f"[MONITOR] Error getting recent activity: {e}")
        return []


def get_user_notifications(user_id, unread_only=False, limit=50, db_path=None) -> List[Dict]:
    """Get notifications for a user (for API endpoint)"""
    try:
        supabase = get_supabase_client()
        query = supabase.schema(SCHEMA_NAME).table('wallet_notifications').select('*').eq('user_id', user_id)

        if unread_only:
            query = query.eq('is_read', False)

        result = query.order('sent_at', desc=True).limit(limit).execute()
        return result.data

    except Exception as e:
        print(f"[MONITOR] Error getting notifications: {e}")
        return []


def mark_notification_read(notification_id, user_id, db_path=None) -> bool:
    """Mark a notification as read"""
    try:
        supabase = get_supabase_client()
        supabase.schema(SCHEMA_NAME).table('wallet_notifications').update({
            'is_read': True
        }).eq('id', notification_id).eq('user_id', user_id).execute()
        return True

    except Exception as e:
        print(f"[MONITOR] Error marking notification read: {e}")
        return False


def mark_all_notifications_read(user_id, db_path=None) -> int:
    """Mark all notifications as read for a user"""
    try:
        supabase = get_supabase_client()

        # Count first
        count_result = supabase.schema(SCHEMA_NAME).table('wallet_notifications').select(
            'id', count='exact'
        ).eq('user_id', user_id).eq('is_read', False).execute()

        count = count_result.count or 0

        # Update
        supabase.schema(SCHEMA_NAME).table('wallet_notifications').update({
            'is_read': True
        }).eq('user_id', user_id).eq('is_read', False).execute()

        return count

    except Exception as e:
        print(f"[MONITOR] Error marking all notifications read: {e}")
        return 0


def update_alert_settings(user_id, wallet_address, settings, db_path=None) -> bool:
    """Update alert settings for a wallet"""
    try:
        supabase = get_supabase_client()

        update_data = {
            'last_updated': datetime.utcnow().isoformat()
        }

        if 'alert_enabled' in settings:
            update_data['alert_enabled'] = settings['alert_enabled']
        if 'alert_threshold_usd' in settings:
            update_data['alert_threshold_usd'] = settings['alert_threshold_usd']

        supabase.schema(SCHEMA_NAME).table('wallet_watchlist').update(update_data).eq(
            'user_id', user_id
        ).eq('wallet_address', wallet_address).execute()

        return True

    except Exception as e:
        print(f"[MONITOR] Error updating alert settings: {e}")
        return False


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == '__main__':
    import os

    SOLANATRACKER_API_KEY = os.environ.get('SOLANATRACKER_API_KEY', '')

    monitor = WalletActivityMonitor(
        solanatracker_api_key=SOLANATRACKER_API_KEY,
        poll_interval=120  # 2 minutes
    )

    print("\n🎯 Wallet Activity Monitor")
    print("   Press Ctrl+C to stop\n")

    try:
        monitor.start()

        # Keep main thread alive and print stats periodically
        while True:
            time.sleep(300)  # Every 5 minutes
            stats = monitor.get_monitoring_stats()

            print(f"\n{'='*80}")
            print(f"MONITORING STATS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*80}")
            print(f"  Active Wallets: {stats['active_wallets']}")
            print(f"  Recent Activities (1h): {stats['recent_activities']}")
            print(f"  Pending Notifications: {stats['pending_notifications']}")
            print(f"  Monitor Health: {stats['monitor_health']}")
            print(f"  Telegram: {'Enabled' if stats['telegram_enabled'] else 'Disabled'}")
            print(f"{'='*80}\n")

    except KeyboardInterrupt:
        print("\n\n⚠️ Received shutdown signal...")
        monitor.stop()
        print("✅ Monitor stopped gracefully\n")