"""
wallet_monitor.py - Real-time wallet activity monitor.

Continuously polls Solana Tracker API for transactions from watched wallets,
creates notifications for watchlist owners, broadcasts Elite 15 signals to
auto-trade-enabled Telegram users, and supports live notification delivery.
"""

import json
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional, Set

import requests

from services.supabase_client import SCHEMA_NAME, get_supabase_client

try:
    from services.alert_router import alert, P0, P1, P2
except ImportError:
    def alert(*a, **kw): pass
    P0 = P1 = P2 = "P3"

if TYPE_CHECKING:
    from services.paper_trader import PaperTrader
    from services.telegram_notifier import TelegramNotifier


def _safe_float(value, fallback=0.0) -> float:
    """Safely convert API values to float."""
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback
    if isinstance(value, dict):
        for key in ("amount", "value", "usd", "sol", "lamports"):
            nested = value.get(key)
            if nested is None:
                continue
            try:
                return float(nested)
            except (TypeError, ValueError):
                continue
    return fallback


class WalletActivityMonitor:
    """Monitor watched wallets and create notification records."""

    def __init__(
        self,
        solanatracker_api_key,
        poll_interval=120,
        telegram_notifier: Optional["TelegramNotifier"] = None,
        paper_trader: Optional["PaperTrader"] = None,
        db_path: str = None,
    ):
        self.solanatracker_key = solanatracker_api_key
        self.poll_interval = poll_interval
        self.solanatracker_trades_url = "https://data.solanatracker.io/wallet"
        self.running = False
        self.monitor_thread = None

        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME
        self.telegram_notifier = telegram_notifier
        self.paper_trader = paper_trader

        self.pending_signals = {}
        self.buffer_lock = threading.Lock()
        self._elite15_set: Set[str] = set()
        self._elite15_ts = 0.0

        telegram_status = "Enabled" if telegram_notifier else "Disabled"
        print(
            f"""
============================================================
WALLET ACTIVITY MONITOR INITIALIZED
============================================================
  Database: Supabase ({self.schema})
  Poll Interval: {poll_interval}s ({poll_interval / 60:.1f} minutes)
  Solana Tracker API: Configured
  Telegram Alerts: {telegram_status}
"""
        )

    def _table(self, name: str):
        return self.supabase.schema(self.schema).table(name)

    def start(self):
        if self.running:
            print("Monitor already running")
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print(f"Wallet monitor started (polling every {self.poll_interval / 60:.1f} min)")

    def stop(self):
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        print("Wallet monitor stopped")

    def _monitor_loop(self):
        print(f"\n{'=' * 80}")
        print(f"MONITORING STARTED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if self.telegram_notifier:
            print("Telegram alerts: ENABLED")
        print(f"{'=' * 80}\n")

        while self.running:
            try:
                cycle_start = time.time()
                wallets_to_monitor = self._get_monitored_wallets()

                if not wallets_to_monitor:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] No wallets to monitor, sleeping...")
                    time.sleep(self.poll_interval)
                    continue

                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Monitoring {len(wallets_to_monitor)} wallets...")

                for wallet_info in wallets_to_monitor:
                    if not self.running:
                        break
                    self._check_wallet_activity(wallet_info)

                if self.paper_trader:
                    self.paper_trader.check_exits()

                cycle_duration = time.time() - cycle_start
                print(f"Cycle complete in {cycle_duration:.1f}s")

                sleep_time = max(0, self.poll_interval - cycle_duration)
                if sleep_time > 0:
                    print(f"Sleeping {sleep_time:.1f}s until next cycle...\n")
                    time.sleep(sleep_time)

            except Exception as e:
                print(f"\nERROR in monitor loop: {e}")
                import traceback

                traceback.print_exc()
                time.sleep(30)

    def _get_monitored_wallets(self) -> List[Dict]:
        try:
            result = self._table("wallet_watchlist").select(
                "wallet_address, tier, alert_enabled"
            ).eq("alert_enabled", True).execute()

            wallets = []
            seen_addresses = set()
            elite15_set = self._get_elite15_set()

            for row in result.data or []:
                addr = row["wallet_address"]
                if addr in seen_addresses:
                    continue

                seen_addresses.add(addr)
                status_result = self._table("wallet_monitor_status").select(
                    "last_checked_at, last_activity_at"
                ).eq("wallet_address", addr).limit(1).execute()
                status = status_result.data[0] if status_result.data else {}

                wallets.append(
                    {
                        "wallet_address": addr,
                        "tier": row.get("tier"),
                        "monitor_source": "watchlist",
                        "last_checked_at": status.get("last_checked_at"),
                        "last_activity_at": status.get("last_activity_at"),
                    }
                )

            for addr in elite15_set:
                if addr in seen_addresses:
                    continue
                seen_addresses.add(addr)
                status_result = self._table("wallet_monitor_status").select(
                    "last_checked_at, last_activity_at"
                ).eq("wallet_address", addr).limit(1).execute()
                status = status_result.data[0] if status_result.data else {}
                wallets.append(
                    {
                        "wallet_address": addr,
                        "tier": "S",
                        "monitor_source": "elite15",
                        "last_checked_at": status.get("last_checked_at"),
                        "last_activity_at": status.get("last_activity_at"),
                    }
                )

            wallets.sort(key=lambda row: row.get("last_checked_at") or 0)
            return wallets

        except Exception as e:
            print(f"[MONITOR] Error getting monitored wallets: {e}")
            alert(P1, "SUPABASE", "Failed to fetch monitored wallets", details={
                "error": str(e),
            })
            return []

    def _check_wallet_activity(self, wallet_info):
        wallet_address = wallet_info["wallet_address"]
        last_checked = wallet_info.get("last_checked_at")
        is_elite15 = wallet_info.get("monitor_source") == "elite15" or wallet_address in self._get_elite15_set()

        if last_checked:
            try:
                if isinstance(last_checked, str):
                    dt = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
                    last_checked_epoch = int(dt.timestamp())
                else:
                    last_checked_epoch = int(last_checked)
            except Exception:
                last_checked_epoch = 0
        else:
            last_checked_epoch = 0

        lookback_buffer = 300
        after_time = max(0, last_checked_epoch - lookback_buffer)
        before_time = int(time.time())

        try:
            transactions = self._fetch_wallet_all_trades(
                wallet_address,
                after_time=after_time,
                before_time=before_time,
            )

            if transactions:
                print(f"  {wallet_address[:8]}... -> {len(transactions)} new tx(s)")

                new_activities = []
                tokens_bought = defaultdict(list)

                for tx in transactions:
                    activity_id = self._save_wallet_activity(tx, wallet_address)
                    if not activity_id:
                        continue

                    new_activities.append({"activity_id": activity_id, "tx": tx})
                    if tx.get("side") == "buy":
                        tokens_bought[tx.get("token_address")].append(
                            {
                                "wallet": wallet_address,
                                "tier": wallet_info.get("tier", "C"),
                                "usd_value": tx.get("usd_value", 0),
                                "token_ticker": tx.get("token_ticker"),
                                "token_name": tx.get("token_name"),
                                "tx_hash": tx.get("tx_hash"),
                                "block_time": tx.get("block_time"),
                                "side": tx.get("side"),
                                "source": "elite15" if is_elite15 else "watchlist",
                            }
                        )

                if new_activities:
                    self._create_notifications_for_wallet(wallet_address, new_activities)

                for token_address, wallets_buying in tokens_bought.items():
                    self._buffer_multi_wallet_signal(token_address, wallets_buying)

            now_unix = int(time.time())
            self._update_monitor_status(
                wallet_address,
                last_checked_at=now_unix,
                last_activity_at=now_unix if transactions else None,
                success=True,
            )

        except Exception as e:
            print(f"  Error checking {wallet_address[:8]}...: {e}")
            self._update_monitor_status(
                wallet_address,
                last_checked_at=int(time.time()),
                success=False,
                error_message=str(e),
            )

    def _buffer_multi_wallet_signal(self, token_address: str, wallets_buying: List[Dict]):
        with self.buffer_lock:
            if token_address not in self.pending_signals:
                self.pending_signals[token_address] = {"entries": []}
                threading.Timer(60.0, self._flush_multi_signal, [token_address]).start()

            self.pending_signals[token_address]["entries"].extend(wallets_buying)

    def _flush_multi_signal(self, token_address: str):
        with self.buffer_lock:
            payload = self.pending_signals.pop(token_address, {"entries": []})
            trades = payload.get("entries", [])

        if not trades:
            return

        seen_wallets = set()
        deduped_trades = []
        for trade in trades:
            wallet = trade.get("wallet")
            if wallet in seen_wallets:
                continue
            seen_wallets.add(wallet)
            deduped_trades.append(trade)
        trades = deduped_trades

        source = "elite15" if any(trade.get("source") == "elite15" for trade in trades) else "watchlist"

        signal_strength = 0
        tier_weights = {"S": 4, "A": 3, "B": 2, "C": 1}
        for trade in trades:
            signal_strength += tier_weights.get(trade["tier"], 1)

        wallet_count = len(trades)
        qualifies = (source == "elite15" and wallet_count >= 1) or (wallet_count >= 2 and signal_strength >= 5)

        if qualifies:
            latest_trade = max(trades, key=lambda row: row.get("block_time") or 0)
            signal_bucket = int((latest_trade.get("block_time") or time.time()) // 60)
            signal = {
                "token_address": token_address,
                "token_ticker": latest_trade.get("token_ticker"),
                "token_name": latest_trade.get("token_name"),
                "side": "buy",
                "source": source,
                "signal_strength": signal_strength,
                "signal_type": "mega" if wallet_count >= 3 else "double" if wallet_count == 2 else "single",
                "wallet_count": wallet_count,
                "total_usd": round(sum(float(trade.get("usd_value") or 0) for trade in trades), 2),
                "wallets": trades,
                "trades": trades,
                "timestamp": int(time.time()),
                "signal_key": f"{source}:{token_address}:{signal_bucket}",
            }
            self._create_signal_alert(signal)

    def _fetch_wallet_all_trades(self, wallet_address, after_time, before_time):
        url = f"{self.solanatracker_trades_url}/{wallet_address}/trades"
        headers = {"accept": "application/json", "x-api-key": self.solanatracker_key}
        params = {"since_time": after_time * 1000, "limit": 100, "tx_type": "swap"}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            if response.status_code != 200:
                print(f"    Solana Tracker API returned status {response.status_code}")
                if response.status_code == 429:
                    alert(P1, "SOLANATRACKER", "Rate limited (429)", details={
                        "wallet": wallet_address,
                        "status_code": 429,
                    })
                else:
                    alert(P2, "SOLANATRACKER", f"API error {response.status_code}", details={
                        "wallet": wallet_address,
                        "status_code": response.status_code,
                    })
                return []

            data = response.json()
            raw_trades = data.get("trades", [])
            normalized_trades = []

            for trade in raw_trades:
                sol_amount = _safe_float(trade.get("sol_amount") or trade.get("solAmount"), 0.0)
                usd_value = sol_amount * 150
                normalized_trades.append(
                    {
                        "token_address": trade.get("token_address") or trade.get("tokenAddress"),
                        "token_ticker": trade.get("symbol") or trade.get("tokenSymbol"),
                        "token_name": trade.get("token_name") or trade.get("tokenName"),
                        "side": trade.get("type", "").lower(),
                        "token_amount": _safe_float(trade.get("token_amount") or trade.get("tokenAmount"), 0.0),
                        "usd_value": usd_value,
                        "price": _safe_float(trade.get("price"), 0.0),
                        "tx_hash": trade.get("signature") or trade.get("tx_hash"),
                        "block_time": int(trade.get("timestamp", 0) / 1000)
                        if trade.get("timestamp")
                        else int(time.time()),
                        "dex": trade.get("dex", "unknown"),
                    }
                )

            return normalized_trades

        except Exception as e:
            print(f"    Error fetching trades from Solana Tracker: {e}")
            alert(P1, "SOLANATRACKER", f"Request exception: {e}", details={
                "wallet": wallet_address,
                "error": str(e),
            })
            import traceback

            traceback.print_exc()
            return []

    def _create_signal_alert(self, signal):
        print(
            f"  MULTI-WALLET SIGNAL: {signal['wallet_count']} wallets bought "
            f"{signal['token_address'][:8]}..."
        )
        if signal.get("source") == "elite15" and self.paper_trader:
            self.paper_trader.process_signal(signal)
        try:
            if signal.get("source") == "elite15":
                return
            wallet_addresses = [wallet["wallet"] for wallet in signal["wallets"]]
            result = self._table("wallet_watchlist").select("user_id").in_(
                "wallet_address", wallet_addresses
            ).eq("alert_enabled", True).execute()
            user_ids = list(set(row["user_id"] for row in (result.data or [])))
            for user_id in user_ids:
                self._send_telegram_alert(user_id, "multi_wallet", signal)
        except Exception as e:
            print(f"  Error creating signal alert: {e}")

    def _save_wallet_activity(self, tx, wallet_address) -> Optional[int]:
        if not tx.get("token_address"):
            return None

        try:
            existing = self._table("wallet_activity").select("id").eq(
                "signature", tx.get("tx_hash")
            ).limit(1).execute()
            if existing.data:
                return None

            result = self._table("wallet_activity").insert(
                {
                    "wallet_address": wallet_address,
                    "token_address": tx.get("token_address"),
                    "token_ticker": tx.get("token_ticker"),
                    "token_name": tx.get("token_name"),
                    "side": tx.get("side"),
                    "amount": tx.get("token_amount", 0),
                    "usd_value": tx.get("usd_value", 0),
                    "price_per_token": tx.get("price", 0),
                    "signature": tx.get("tx_hash"),
                    "block_time": int(tx.get("block_time", time.time())),
                }
            ).execute()
            return result.data[0]["id"] if result.data else None
        except Exception as e:
            print(f"    Error saving activity: {e}")
            alert(P2, "SUPABASE", f"Failed to save wallet activity: {e}", details={
                "wallet": wallet_address,
                "tx_hash": tx.get("tx_hash"),
            })
            return None

    def _get_wallet_info(self, user_id: str, wallet_address: str) -> Dict:
        try:
            result = self._table("wallet_watchlist").select(
                "tier, consistency_score"
            ).eq("user_id", user_id).eq("wallet_address", wallet_address).limit(1).execute()
            if result.data:
                row = result.data[0]
                return {
                    "tier": row.get("tier", "C"),
                    "consistency_score": row.get("consistency_score", 0),
                }
        except Exception as e:
            print(f"[MONITOR] Error getting wallet info: {e}")

        return {"tier": "C", "consistency_score": 0}

    def _send_telegram_alert(self, user_id: str, alert_type: str, alert_data: Dict):
        if not self.telegram_notifier:
            return

        chat_id = self.telegram_notifier.get_user_chat_id(user_id)
        if not chat_id:
            print(f"[WALLET MONITOR] Telegram skip {user_id[:8]}... (type={alert_type})")
            return

        try:
            from services.tasks import send_telegram_alert_async

            send_telegram_alert_async.delay(user_id, alert_type, alert_data)
            print(f"[WALLET MONITOR] Alert queued via Celery for {user_id[:8]}...")
        except Exception as e:
            print(f"[WALLET MONITOR] Celery unavailable ({e}), sending directly...")
            try:
                self._send_alert_direct(user_id, alert_type, alert_data)
            except Exception as fallback_error:
                print(f"[WALLET MONITOR] Direct alert also failed: {fallback_error}")

    def _send_alert_direct(self, user_id: str, alert_type: str, alert_data: Dict):
        if alert_type in ("trade", "watchlist_trade", "elite15_trade"):
            self._send_trade_alert_direct(user_id, alert_data)
        elif alert_type == "multi_wallet":
            self.telegram_notifier.send_multi_wallet_signal_alert(user_id, alert_data)

    def _send_trade_alert_direct(self, user_id: str, tx: Dict):
        try:
            wallet_address = tx.get("wallet_address", "")
            wallet_info = self._get_wallet_info(user_id, wallet_address)
            payload = {
                "wallet": {
                    "address": wallet_address,
                    "tier": tx.get("wallet_tier") or wallet_info.get("tier", "C"),
                    "consistency_score": wallet_info.get("consistency_score", 0),
                },
                "action": tx.get("side", "buy"),
                "source": tx.get("source", "watchlist"),
                "token": {
                    "address": tx.get("token_address", ""),
                    "symbol": tx.get("token_ticker", "UNKNOWN"),
                    "name": tx.get("token_name", "Unknown"),
                },
                "trade": {
                    "amount_tokens": tx.get("token_amount", 0),
                    "amount_usd": tx.get("usd_value", 0),
                    "price": tx.get("price", 0),
                    "tx_hash": tx.get("tx_hash", ""),
                    "dex": tx.get("dex", "unknown"),
                    "timestamp": tx.get("block_time", int(time.time())),
                },
                "links": {
                    "solscan": f"https://solscan.io/tx/{tx.get('tx_hash', '')}",
                    "birdeye": f"https://birdeye.so/token/{tx.get('token_address', '')}",
                    "dexscreener": f"https://dexscreener.com/solana/{tx.get('token_address', '')}",
                },
            }

            if tx.get("source") == "elite15" and hasattr(self.telegram_notifier, "send_elite15_alert"):
                self.telegram_notifier.send_elite15_alert(user_id, payload)
            elif hasattr(self.telegram_notifier, "send_watchlist_alert"):
                self.telegram_notifier.send_watchlist_alert(user_id, payload)
            else:
                self.telegram_notifier.send_wallet_alert(user_id, payload, tx.get("activity_id"))
        except Exception as e:
            print(f"    Error sending Telegram alert: {e}")

    def _create_notifications_for_wallet(self, wallet_address, activities):
        try:
            watchers_result = self._table("wallet_watchlist").select(
                "user_id, tier, alert_enabled, alert_threshold_usd, min_trade_usd, "
                "alert_on_buy, alert_on_sell, tags"
            ).eq("wallet_address", wallet_address).eq("alert_enabled", True).execute()

            watchers = watchers_result.data or []
            elite15_set = self._get_elite15_set()
            is_elite15 = wallet_address in elite15_set
            notifications_created = 0
            notified_users: Set[str] = set()

            for activity in activities:
                tx = activity["tx"]
                activity_id = activity["activity_id"]

                for watcher in watchers:
                    if not self._should_notify(tx, watcher):
                        continue

                    user_id = watcher["user_id"]
                    source = self._derive_notification_source(watcher, is_elite15)
                    wallet_tier = watcher.get("tier") or ("S" if is_elite15 else "C")

                    try:
                        notification_id = self._insert_notification(
                            user_id=user_id,
                            wallet_address=wallet_address,
                            wallet_tier=wallet_tier,
                            source=source,
                            tx=tx,
                            activity_id=activity_id,
                        )
                        notifications_created += 1
                        notified_users.add(user_id)

                        if self.telegram_notifier:
                            payload = {
                                **tx,
                                "wallet_address": wallet_address,
                                "activity_id": activity_id,
                                "wallet_tier": wallet_tier,
                                "source": source,
                                "notification_id": notification_id,
                            }
                            alert_type = "elite15_trade" if source == "elite15" else "watchlist_trade"
                            self._send_telegram_alert(user_id, alert_type, payload)
                    except Exception as e:
                        print(f"    Error creating notification: {e}")

            if is_elite15:
                notifications_created += self._broadcast_elite15_to_all_users(
                    wallet_address=wallet_address,
                    activities=activities,
                    already_notified=notified_users,
                )

            if notifications_created > 0:
                print(f"    Created {notifications_created} notification(s)")

        except Exception as e:
            print(f"[MONITOR] Error creating notifications: {e}")
            alert(P2, "SUPABASE", f"Failed to create notifications: {e}", details={
                "wallet": wallet_address,
            })

    def _derive_notification_source(self, watcher: Dict, is_elite15: bool) -> str:
        tags = watcher.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = [tags]
        if is_elite15:
            return "elite15"
        if any(tag in ("exchange", "external") for tag in tags):
            return "external"
        return "watchlist"

    def _insert_notification(
        self,
        *,
        user_id: str,
        wallet_address: str,
        wallet_tier: str,
        source: str,
        tx: Dict,
        activity_id: int,
    ):
        side = tx.get("side", "trade")
        token_ticker = tx.get("token_ticker", "UNKNOWN")
        token_name = tx.get("token_name", "Unknown")
        token_address = tx.get("token_address", "")
        usd_value = float(tx.get("usd_value", 0) or 0)
        tx_hash = tx.get("tx_hash", "")
        metadata = {
            "activity_id": activity_id,
            "side": side,
            "token_address": token_address,
            "token_ticker": token_ticker,
            "token_name": token_name,
            "usd_value": usd_value,
            "tx_hash": tx_hash,
            "price": tx.get("price", 0),
            "token_amount": tx.get("token_amount", 0),
            "block_time": tx.get("block_time", int(time.time())),
            "dex": tx.get("dex", "unknown"),
            "wallet_tier": wallet_tier,
            "source": source,
            "is_elite15": source == "elite15",
            "solscan_url": f"https://solscan.io/tx/{tx_hash}",
            "birdeye_url": f"https://birdeye.so/token/{token_address}",
            "dexscreener_url": f"https://dexscreener.com/solana/{token_address}",
        }
        title_prefix = "ELITE 15 " if source == "elite15" else ""
        result = self._table("wallet_notifications").insert(
            {
                "user_id": user_id,
                "wallet_address": wallet_address,
                "notification_type": side,
                "title": f"{title_prefix}{side.upper()}: {token_ticker}",
                "message": f"${usd_value:.2f} {side} - {token_ticker}",
                "metadata": metadata,
                "is_read": False,
                "side": side,
                "token_ticker": token_ticker,
                "token_name": token_name,
                "token_address": token_address,
                "usd_value": usd_value,
                "tx_hash": tx_hash,
                "wallet_tier": wallet_tier,
                "source": source,
            }
        ).execute()
        return result.data[0]["id"] if result.data else None

    def _get_elite15_set(self) -> Set[str]:
        now = time.time()
        if now - self._elite15_ts < 300:
            return self._elite15_set

        addresses: Set[str] = set()
        try:
            result = self._table("elite_100_cache").select("data").order(
                "created_at", desc=True
            ).limit(1).execute()
            if result.data:
                payload = result.data[0].get("data") or []
                if isinstance(payload, list):
                    ranked = sorted(payload, key=lambda row: row.get("rank", 9999))
                    addresses = {
                        row.get("wallet_address")
                        for row in ranked[:15]
                        if row.get("wallet_address")
                    }
        except Exception as e:
            print(f"[MONITOR] Elite 15 lookup failed: {e}")

        self._elite15_set = addresses
        self._elite15_ts = now
        return addresses

    def _get_all_auto_trade_users(self) -> List[Dict]:
        try:
            result = self._table("telegram_users").select(
                "user_id, auto_trade_enabled, auto_trade_max_usd, auto_trade_source, alerts_enabled"
            ).eq("alerts_enabled", True).eq("auto_trade_enabled", True).execute()
            return result.data or []
        except Exception as e:
            print(f"[MONITOR] Auto-trade user lookup failed: {e}")
            return []

    def _broadcast_elite15_to_all_users(
        self,
        wallet_address: str,
        activities: List[Dict],
        already_notified: Set[str],
    ) -> int:
        created = 0
        auto_users = self._get_all_auto_trade_users()
        for activity in activities:
            tx = activity["tx"]
            activity_id = activity["activity_id"]
            for user in auto_users:
                user_id = user.get("user_id")
                if not user_id or user_id in already_notified:
                    continue
                if user.get("auto_trade_source", "elite15") not in ("elite15", "all"):
                    continue

                try:
                    notification_id = self._insert_notification(
                        user_id=user_id,
                        wallet_address=wallet_address,
                        wallet_tier="S",
                        source="elite15",
                        tx=tx,
                        activity_id=activity_id,
                    )
                    created += 1
                    if self.telegram_notifier:
                        self._send_telegram_alert(
                            user_id,
                            "elite15_trade",
                            {
                                **tx,
                                "wallet_address": wallet_address,
                                "activity_id": activity_id,
                                "wallet_tier": "S",
                                "source": "elite15",
                                "notification_id": notification_id,
                                "auto_trade_max_usd": user.get("auto_trade_max_usd", 100),
                            },
                        )
                except Exception as e:
                    print(f"    Elite15 broadcast error for {user_id[:8]}...: {e}")
        return created

    def _should_notify(self, tx, settings):
        side = tx.get("side", "buy")
        if side == "buy" and not settings.get("alert_on_buy", True):
            return False
        if side == "sell" and not settings.get("alert_on_sell", False):
            return False

        usd_value = tx.get("usd_value", 0)
        threshold = settings.get("min_trade_usd") or settings.get("alert_threshold_usd") or 100
        return usd_value >= threshold

    def _update_monitor_status(
        self,
        wallet_address,
        last_checked_at,
        last_activity_at=None,
        success=True,
        error_message=None,
    ):
        try:
            def to_unix(ts):
                if ts is None:
                    return None
                if isinstance(ts, str):
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        return int(dt.timestamp())
                    except Exception:
                        return None
                return int(ts)

            last_checked_unix = to_unix(last_checked_at)
            last_activity_unix = to_unix(last_activity_at) if last_activity_at else None
            updated_at_iso = datetime.utcnow().isoformat() + "Z"

            existing = self._table("wallet_monitor_status").select("wallet_address").eq(
                "wallet_address", wallet_address
            ).limit(1).execute()

            if existing.data:
                update_data = {
                    "last_checked_at": last_checked_unix,
                    "updated_at": updated_at_iso,
                }
                if success:
                    update_data["error_count"] = 0
                    update_data["last_error"] = None
                    if last_activity_unix:
                        update_data["last_activity_at"] = last_activity_unix
                else:
                    update_data["last_error"] = error_message

                self._table("wallet_monitor_status").update(update_data).eq(
                    "wallet_address", wallet_address
                ).execute()

                try:
                    self.supabase.rpc(
                        "increment_check_count",
                        {
                            "p_wallet_address": wallet_address,
                            "p_error_increment": 0 if success else 1,
                        },
                    ).execute()
                except Exception:
                    pass
            else:
                self._table("wallet_monitor_status").insert(
                    {
                        "wallet_address": wallet_address,
                        "last_checked_at": last_checked_unix,
                        "last_activity_at": last_activity_unix,
                        "updated_at": updated_at_iso,
                        "check_count": 1,
                        "error_count": 0 if success else 1,
                        "last_error": None if success else error_message,
                        "is_active": True,
                    }
                ).execute()

        except Exception as e:
            print(f"[MONITOR] Error updating status: {e}")
            alert(P2, "SUPABASE", f"Failed to update monitor status: {e}", details={
                "wallet": wallet_address,
            })

    def get_monitoring_stats(self) -> Dict:
        try:
            active_result = self._table("wallet_watchlist").select(
                "wallet_address", count="exact"
            ).eq("alert_enabled", True).execute()
            active_wallets = active_result.count or 0

            one_hour_ago = datetime.utcfromtimestamp(time.time() - 3600).isoformat()
            activity_result = self._table("wallet_activity").select(
                "id", count="exact"
            ).gte("created_at", one_hour_ago).execute()
            recent_activities = activity_result.count or 0

            pending_result = self._table("wallet_notifications").select(
                "id", count="exact"
            ).eq("is_read", False).execute()
            pending_notifications = pending_result.count or 0

            health_result = self._table("wallet_monitor_status").select(
                "wallet_address, error_count, check_count"
            ).execute()
            health_rows = health_result.data or []
            total_monitored = len(health_rows)
            with_errors = sum(1 for row in health_rows if (row.get("error_count") or 0) > 0)
            avg_checks = sum(row.get("check_count", 0) for row in health_rows) / max(total_monitored, 1)

            return {
                "active_wallets": active_wallets,
                "recent_activities": recent_activities,
                "pending_notifications": pending_notifications,
                "monitor_health": {
                    "total_monitored": total_monitored,
                    "with_errors": with_errors,
                    "avg_checks": round(avg_checks, 1),
                },
                "running": self.running,
                "poll_interval_seconds": self.poll_interval,
                "telegram_enabled": self.telegram_notifier is not None,
            }

        except Exception as e:
            print(f"[MONITOR] Error getting stats: {e}")
            return {
                "active_wallets": 0,
                "recent_activities": 0,
                "pending_notifications": 0,
                "monitor_health": {"total_monitored": 0, "with_errors": 0, "avg_checks": 0},
                "running": self.running,
                "poll_interval_seconds": self.poll_interval,
                "telegram_enabled": self.telegram_notifier is not None,
            }

    def force_check_wallet(self, wallet_address):
        wallet_info = {
            "wallet_address": wallet_address,
            "tier": None,
            "monitor_source": "manual",
            "last_checked_at": None,
            "last_activity_at": None,
        }
        print(f"\nForce checking wallet: {wallet_address[:8]}...")
        self._check_wallet_activity(wallet_info)
        print("Check complete\n")


def get_recent_wallet_activity(wallet_address=None, limit=50, db_path=None) -> List[Dict]:
    try:
        supabase = get_supabase_client()
        query = supabase.schema(SCHEMA_NAME).table("wallet_activity").select("*")
        if wallet_address:
            query = query.eq("wallet_address", wallet_address)
        return query.order("block_time", desc=True).limit(limit).execute().data
    except Exception as e:
        print(f"[MONITOR] Error getting recent activity: {e}")
        return []


def get_user_notifications(user_id, unread_only=False, limit=50, offset=0, db_path=None) -> List[Dict]:
    try:
        supabase = get_supabase_client()
        query = supabase.schema(SCHEMA_NAME).table("wallet_notifications").select("*").eq("user_id", user_id)
        if unread_only:
            query = query.eq("is_read", False)
        result = query.order("sent_at", desc=True).range(offset, offset + limit - 1).execute()
        return result.data or []
    except Exception as e:
        print(f"[MONITOR] Error getting notifications: {e}")
        return []


def mark_notification_read(notification_id, user_id, db_path=None) -> bool:
    try:
        supabase = get_supabase_client()
        supabase.schema(SCHEMA_NAME).table("wallet_notifications").update(
            {"is_read": True}
        ).eq("id", notification_id).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        print(f"[MONITOR] Error marking notification read: {e}")
        return False


def mark_all_notifications_read(user_id, db_path=None) -> int:
    try:
        supabase = get_supabase_client()
        count_result = supabase.schema(SCHEMA_NAME).table("wallet_notifications").select(
            "id", count="exact"
        ).eq("user_id", user_id).eq("is_read", False).execute()
        count = count_result.count or 0
        supabase.schema(SCHEMA_NAME).table("wallet_notifications").update(
            {"is_read": True}
        ).eq("user_id", user_id).eq("is_read", False).execute()
        return count
    except Exception as e:
        print(f"[MONITOR] Error marking all notifications read: {e}")
        return 0


def update_alert_settings(user_id, wallet_address, settings, db_path=None) -> bool:
    try:
        supabase = get_supabase_client()
        update_data = {"last_updated": datetime.utcnow().isoformat()}
        if "alert_enabled" in settings:
            update_data["alert_enabled"] = settings["alert_enabled"]
        if "alert_threshold_usd" in settings:
            update_data["alert_threshold_usd"] = settings["alert_threshold_usd"]
        supabase.schema(SCHEMA_NAME).table("wallet_watchlist").update(update_data).eq(
            "user_id", user_id
        ).eq("wallet_address", wallet_address).execute()
        return True
    except Exception as e:
        print(f"[MONITOR] Error updating alert settings: {e}")
        return False


if __name__ == "__main__":
    import os

    monitor = WalletActivityMonitor(
        solanatracker_api_key=os.environ.get("SOLANATRACKER_API_KEY", ""),
        poll_interval=120,
    )

    print("\nWallet Activity Monitor")
    print("Press Ctrl+C to stop\n")

    try:
        monitor.start()
        while True:
            time.sleep(300)
            stats = monitor.get_monitoring_stats()
            print(f"\n{'=' * 80}")
            print(f"MONITORING STATS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'=' * 80}")
            print(f"  Active Wallets:           {stats['active_wallets']}")
            print(f"  Recent Activities (1h):   {stats['recent_activities']}")
            print(f"  Pending Notifications:    {stats['pending_notifications']}")
            print(f"  Monitor Health:           {stats['monitor_health']}")
            print(f"  Telegram:                 {'Enabled' if stats['telegram_enabled'] else 'Disabled'}")
            print(f"{'=' * 80}\n")
    except KeyboardInterrupt:
        print("\nReceived shutdown signal...")
        monitor.stop()
        print("Monitor stopped gracefully\n")
