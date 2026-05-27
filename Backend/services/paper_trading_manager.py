"""Paper Trading Manager - Virtual trades triggered by Elite 15 wallet activity.

Manages paper trade recording, portfolio tracking, PnL computation,
and position lifecycle for users following Elite wallets.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from config import Config
from services.http_session import get_http_session
from services.redis_pool import get_redis_client
from services.supabase_client import get_supabase_client, SCHEMA_NAME

KILL_SWITCH_KEY = "sifter:kill_switch"

try:
    from services.alert_router import alert, P0, P1, P2
except ImportError:
    def alert(*a, **kw): pass
    P0 = P1 = P2 = "P3"


class PaperTradingManager:
    """Manages virtual paper trades and portfolio positions."""

    def __init__(self):
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME

    # ── Helpers ────────────────────────────────────────────────────────────

    def _table(self, name: str):
        """Get a table reference scoped to the project schema."""
        return self.supabase.schema(self.schema).table(name)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _fetch_token_price(self, token_address: str) -> Optional[float]:
        """Fetch the current USD price for a token via shared ST client.

        Uses the centralized SolanaTrackerV2Client which has rate limiting,
        retries, and Redis caching — prevents 429 storms when other tasks
        are also making API calls.

        Returns None if the price cannot be determined.
        """
        try:
            from services.solana_tracker_client import get_st_client
            data = get_st_client().get_token_info(token_address)
            if not data:
                return None
            # Extract price from pools[0].price.usd or token.price_usd
            price = None
            pools = data.get("pools") or []
            if pools:
                price = (pools[0].get("price") or {}).get("usd")
            if price is None:
                price = (data.get("token") or {}).get("price_usd")
            if price is not None:
                return float(price)
        except Exception as exc:
            logger.error("[PAPER] action=fetch_price status=failed token=%s error=%s", token_address[:16], str(exc)[:200])
        return None

    def _log_event(
        self,
        user_id: str,
        event_type: str,
        details: dict,
    ) -> None:
        """Insert a row into paper_trade_logs."""
        try:
            self._table("paper_trade_logs").insert({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "event_type": event_type,
                "details": details,
                "created_at": self._now_iso(),
            }).execute()
        except Exception as exc:
            logger.error("[PAPER] action=log_event status=failed user=%s error=%s", user_id[:8], str(exc)[:200])

    # ── Kill Switch ────────────────────────────────────────────────────────

    def is_kill_switch_active(self) -> bool:
        """Return True if the kill switch is engaged.

        Accepts both simple truthy values ("1") and JSON ({"active": true}).
        Fails closed — if Redis is down, trading is blocked.
        """
        try:
            r = get_redis_client()
            raw = r.get(KILL_SWITCH_KEY)
            if not raw:
                return False
            # Handle both "1" (from /kill command) and JSON {"active": true}
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            raw = str(raw).strip()
            if raw in ("1", "true", "True"):
                return True
            try:
                data = json.loads(raw)
                return bool(data.get("active", False))
            except (json.JSONDecodeError, AttributeError):
                return bool(raw)  # any non-empty value = active
        except Exception as exc:
            logger.error("[PAPER] action=kill_switch status=redis_fail error=%s", str(exc)[:200])
            try:
                from services.alert_router import alert, P0
                alert(P0, "REDIS", f"Kill switch Redis read failed — trading blocked: {exc}")
            except ImportError:
                pass
            return True  # Fail closed — block trading when Redis is unreachable

    # ── Trade Recording ────────────────────────────────────────────────────

    def record_trade(
        self,
        user_id: str,
        token_address: str,
        token_symbol: str,
        side: str,
        amount_usd: float,
        price_per_token: float,
        trigger_wallet: Optional[str] = None,
        trigger_type: str = "manual",
    ) -> Optional[Dict]:
        """Record a paper trade and update the user's portfolio.

        Args:
            user_id: The user placing the virtual trade.
            token_address: Solana token mint address.
            token_symbol: Human-readable symbol (e.g. "SOL").
            side: "buy" or "sell".
            amount_usd: Notional USD value of the trade.
            price_per_token: Execution price in USD.
            trigger_wallet: Elite wallet address that triggered (if auto).
            trigger_type: "auto_elite" or "manual".

        Returns:
            The inserted trade record dict, or None on failure.
        """
        if self.is_kill_switch_active():
            logger.warning("[PAPER] action=trade status=blocked user=%s reason=kill_switch", user_id[:8])
            self._log_event(user_id, "kill_switch", {
                "action": "trade_rejected",
                "token": token_symbol,
                "side": side,
            })
            return None

        trade_id = str(uuid.uuid4())
        now = self._now_iso()

        trade_row = {
            "id": trade_id,
            "user_id": user_id,
            "token_address": token_address,
            "token_symbol": token_symbol,
            "side": side,
            "amount_usd": amount_usd,
            "price_per_token": price_per_token,
            "trigger_wallet": trigger_wallet,
            "trigger_type": trigger_type,
            "created_at": now,
        }

        try:
            # 1. Insert the trade
            result = self._table("paper_trades").insert(trade_row).execute()
            trade = result.data[0] if result.data else trade_row

            # 2. Update portfolio
            self._update_portfolio(
                user_id, token_address, token_symbol,
                side, amount_usd, price_per_token, now,
            )

            # 3. Audit log
            self._log_event(user_id, "trade", {
                "trade_id": trade_id,
                "token": token_symbol,
                "side": side,
                "amount_usd": amount_usd,
                "price": price_per_token,
                "trigger_wallet": trigger_wallet,
                "trigger_type": trigger_type,
            })

            logger.info("[PAPER] action=%s status=ok user=%s token=%s size_usd=%.2f trigger=%s", side, user_id[:8], token_symbol, amount_usd, trigger_type)
            return trade

        except Exception as exc:
            logger.error("[PAPER] action=trade status=failed user=%s error=%s", user_id[:8], str(exc)[:200])
            alert(P0, "TRADE", f"Paper trade recording failed: {exc}",
                  details={"user_id": user_id, "token": token_symbol, "side": side})
            self._log_event(user_id, "error", {
                "action": "record_trade",
                "error": str(exc),
            })
            return None

    def _update_portfolio(
        self,
        user_id: str,
        token_address: str,
        token_symbol: str,
        side: str,
        amount_usd: float,
        price_per_token: float,
        now: str,
    ) -> None:
        """Create or update the portfolio position for a token."""
        try:
            existing = (
                self._table("paper_portfolio")
                .select("*")
                .eq("user_id", user_id)
                .eq("token_address", token_address)
                .eq("status", "open")
                .execute()
            )

            if side == "buy":
                if existing.data:
                    pos = existing.data[0]
                    old_invested = float(pos["total_invested_usd"] or 0)
                    old_avg = float(pos["avg_entry_price"] or 0)

                    new_invested = old_invested + amount_usd
                    # Weighted average entry price
                    if old_avg > 0 and price_per_token > 0:
                        old_qty = old_invested / old_avg
                        new_qty = amount_usd / price_per_token
                        new_avg = new_invested / (old_qty + new_qty)
                    else:
                        new_avg = price_per_token

                    self._table("paper_portfolio").update({
                        "total_invested_usd": new_invested,
                        "avg_entry_price": new_avg,
                    }).eq("id", pos["id"]).execute()
                else:
                    # First buy — create position
                    self._table("paper_portfolio").insert({
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "token_address": token_address,
                        "token_symbol": token_symbol,
                        "total_invested_usd": amount_usd,
                        "avg_entry_price": price_per_token,
                        "current_value_usd": amount_usd,
                        "unrealized_pnl_usd": 0,
                        "status": "open",
                        "opened_at": now,
                    }).execute()

            elif side == "sell":
                if existing.data:
                    pos = existing.data[0]
                    old_invested = float(pos["total_invested_usd"] or 0)
                    remaining = max(old_invested - amount_usd, 0)

                    if remaining <= 0:
                        # Fully exited — close position
                        self._table("paper_portfolio").update({
                            "total_invested_usd": 0,
                            "current_value_usd": 0,
                            "unrealized_pnl_usd": 0,
                            "status": "closed",
                            "closed_at": now,
                        }).eq("id", pos["id"]).execute()
                    else:
                        self._table("paper_portfolio").update({
                            "total_invested_usd": remaining,
                        }).eq("id", pos["id"]).execute()
                else:
                    logger.warning("[PAPER] action=sell status=ignored token=%s reason=no_open_position", token_symbol)

        except Exception as exc:
            logger.error("[PAPER] action=update_portfolio status=failed user=%s error=%s", user_id[:8], str(exc)[:200])

    # ── Portfolio Reads ────────────────────────────────────────────────────

    def get_portfolio(self, user_id: str) -> List[Dict]:
        """Return all open positions with live prices and unrealized PnL.

        Fetches the current price for each held token and updates the
        stored current_value_usd / unrealized_pnl_usd in-place.
        """
        try:
            result = (
                self._table("paper_portfolio")
                .select("*")
                .eq("user_id", user_id)
                .eq("status", "open")
                .execute()
            )
            positions = result.data or []
        except Exception as exc:
            logger.error("[PAPER] action=get_portfolio status=failed user=%s error=%s", user_id[:8], str(exc)[:200])
            return []

        enriched: List[Dict] = []
        for pos in positions:
            token_address = pos["token_address"]
            invested = float(pos["total_invested_usd"] or 0)
            avg_price = float(pos["avg_entry_price"] or 0)

            current_price = self._fetch_token_price(token_address)
            if current_price is not None and avg_price > 0:
                quantity = invested / avg_price
                current_value = quantity * current_price
                pnl = current_value - invested
            else:
                current_value = float(pos.get("current_value_usd") or invested)
                pnl = float(pos.get("unrealized_pnl_usd") or 0)

            # Persist the refreshed values
            try:
                self._table("paper_portfolio").update({
                    "current_value_usd": current_value,
                    "unrealized_pnl_usd": pnl,
                }).eq("id", pos["id"]).execute()
            except Exception:
                pass  # non-critical

            pos["current_value_usd"] = current_value
            pos["unrealized_pnl_usd"] = pnl
            pos["current_price"] = current_price
            enriched.append(pos)

        return enriched

    def get_trade_history(self, user_id: str, limit: int = 20) -> List[Dict]:
        """Return recent paper trades for a user, newest first."""
        try:
            result = (
                self._table("paper_trades")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.error("[PAPER] action=get_trade_history status=failed user=%s error=%s", user_id[:8], str(exc)[:200])
            return []

    # ── PnL Summary ────────────────────────────────────────────────────────

    def get_pnl_summary(self, user_id: str) -> Dict:
        """Aggregate PnL summary across all positions (open and closed).

        Returns:
            Dict with total_invested, current_total_value, total_pnl,
            win_count, loss_count, win_rate.
        """
        summary = {
            "total_invested": 0.0,
            "current_total_value": 0.0,
            "total_pnl": 0.0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
        }

        try:
            result = (
                self._table("paper_portfolio")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            positions = result.data or []
        except Exception as exc:
            logger.error("[PAPER] action=get_pnl status=failed user=%s error=%s", user_id[:8], str(exc)[:200])
            return summary

        for pos in positions:
            invested = float(pos.get("total_invested_usd") or 0)
            status = pos.get("status", "open")

            if status == "open":
                # Use cached values (caller should call get_portfolio first
                # if they need fully up-to-date numbers)
                current_value = float(pos.get("current_value_usd") or invested)
                pnl = float(pos.get("unrealized_pnl_usd") or 0)
                summary["total_invested"] += invested
                summary["current_total_value"] += current_value
            else:
                # Closed position — PnL is realized
                current_value = float(pos.get("current_value_usd") or 0)
                pnl = current_value - invested
                summary["total_invested"] += invested
                summary["current_total_value"] += current_value

            summary["total_pnl"] += pnl

            if pnl >= 0:
                summary["win_count"] += 1
            else:
                summary["loss_count"] += 1

        total_positions = summary["win_count"] + summary["loss_count"]
        if total_positions > 0:
            summary["win_rate"] = round(
                summary["win_count"] / total_positions * 100, 1
            )

        # Round monetary values
        summary["total_invested"] = round(summary["total_invested"], 2)
        summary["current_total_value"] = round(summary["current_total_value"], 2)
        summary["total_pnl"] = round(summary["total_pnl"], 2)

        return summary

    # ── Position Management ────────────────────────────────────────────────

    def close_position(self, user_id: str, token_address: str) -> bool:
        """Mark an open position as closed.

        Returns True if a position was closed, False otherwise.
        """
        try:
            existing = (
                self._table("paper_portfolio")
                .select("id, token_symbol")
                .eq("user_id", user_id)
                .eq("token_address", token_address)
                .eq("status", "open")
                .execute()
            )

            if not existing.data:
                logger.warning("[PAPER] action=close status=no_position token=%s", token_address[:16])
                return False

            pos = existing.data[0]
            now = self._now_iso()

            self._table("paper_portfolio").update({
                "status": "closed",
                "closed_at": now,
            }).eq("id", pos["id"]).execute()

            self._log_event(user_id, "trade", {
                "action": "close_position",
                "token_address": token_address,
                "token_symbol": pos.get("token_symbol"),
            })

            logger.info("[PAPER] action=close token=%s user=%s", pos.get("token_symbol"), user_id[:8])
            return True

        except Exception as exc:
            logger.error("[PAPER] action=close status=failed user=%s error=%s", user_id[:8], str(exc)[:200])
            self._log_event(user_id, "error", {
                "action": "close_position",
                "error": str(exc),
            })
            return False


    # ── Exit Checker ─────────────────────────────────────────────────────────

    # Take-profit tiers: multiplier → sell percentage
    TP_TIERS = [(5.0, 25), (10.0, 33), (20.0, 50), (30.0, 100)]
    STOP_LOSS_MULT = 0.30   # close if price drops to 30% of entry
    MAX_AGE_DAYS = 14       # close after 14 days regardless

    def check_exits(self) -> dict:
        """Check all open positions for take-profit, stop-loss, and max-age exits.

        Called every 2 minutes by the Celery beat task.
        Returns summary of actions taken.
        """
        stats = {"checked": 0, "tp_exits": 0, "sl_exits": 0, "age_exits": 0, "errors": 0}

        try:
            result = (
                self._table("paper_portfolio")
                .select("*")
                .eq("status", "open")
                .execute()
            )
            positions = result.data or []
        except Exception as exc:
            logger.error("[PAPER] action=check_exits status=fetch_failed error=%s", str(exc)[:200])
            return {"error": str(exc)}

        if not positions:
            return stats

        now = datetime.now(timezone.utc)

        for pos in positions:
            stats["checked"] += 1
            token_address = pos.get("token_address", "")
            user_id = pos.get("user_id", "")
            symbol = pos.get("token_symbol", "???")

            try:
                # Fetch current price
                current_price = self._fetch_token_price(token_address)
                if current_price is None or current_price <= 0:
                    continue

                avg_entry = float(pos.get("avg_entry_price", 0))
                if avg_entry <= 0:
                    continue

                multiplier = current_price / avg_entry

                # Check stop-loss
                if multiplier <= self.STOP_LOSS_MULT:
                    self._close_position_by_id(pos, reason="stop_loss")
                    stats["sl_exits"] += 1
                    logger.info("[PAPER] action=sl_exit token=%s mult=%.2f", symbol, multiplier)
                    # Notify user of stop-loss
                    try:
                        import os
                        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                        if bot_token:
                            from services.telegram_notifier import TelegramNotifier
                            tn = TelegramNotifier(bot_token)
                            tn._notify_paper_trade_event(user_id, "sl_exit", {
                                "token_symbol": symbol, "multiplier": multiplier,
                            })
                    except Exception:
                        pass
                    continue

                # Check max age
                opened_at_str = pos.get("opened_at", "")
                if opened_at_str:
                    try:
                        opened_at = datetime.fromisoformat(opened_at_str.replace("Z", "+00:00"))
                        age_days = (now - opened_at).total_seconds() / 86400
                        if age_days >= self.MAX_AGE_DAYS:
                            self._close_position_by_id(pos, reason="max_age")
                            stats["age_exits"] += 1
                            logger.info("[PAPER] action=age_exit token=%s days=%.1f", symbol, age_days)
                            # Notify user of age exit
                            try:
                                import os
                                bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                                if bot_token:
                                    from services.telegram_notifier import TelegramNotifier
                                    tn = TelegramNotifier(bot_token)
                                    tn._notify_paper_trade_event(user_id, "age_exit", {
                                        "token_symbol": symbol, "multiplier": multiplier,
                                    })
                            except Exception:
                                pass
                            continue
                    except (ValueError, TypeError):
                        pass

                # Check take-profit tiers (highest first)
                # Track triggered tiers via metadata to avoid repeated sells
                triggered_tiers = set()
                meta = pos.get("metadata") or {}
                if isinstance(meta, str):
                    try:
                        import json as _json
                        meta = _json.loads(meta)
                    except Exception:
                        meta = {}
                triggered_tiers = set(meta.get("tp_tiers_triggered", []))

                for tp_mult, tp_pct in reversed(self.TP_TIERS):
                    tier_key = f"{tp_mult}x"
                    if tier_key in triggered_tiers:
                        continue  # Already sold at this tier
                    if multiplier >= tp_mult:
                        if tp_pct == 100:
                            self._close_position_by_id(pos, reason=f"tp_{tp_mult}x")
                        else:
                            self.partial_close_position(
                                user_id, token_address, tp_pct,
                                reason=f"tp_{tp_mult}x_{tp_pct}pct",
                            )
                            # Record that this tier was triggered
                            triggered_tiers.add(tier_key)
                            try:
                                self._table("paper_portfolio").update({
                                    "metadata": {"tp_tiers_triggered": list(triggered_tiers)},
                                }).eq("id", pos["id"]).execute()
                            except Exception:
                                pass
                        stats["tp_exits"] += 1
                        logger.info("[PAPER] action=tp_exit token=%s mult=%.1f pct=%d", symbol, multiplier, tp_pct)
                        # Notify user of take-profit exit
                        try:
                            import os
                            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                            if bot_token:
                                from services.telegram_notifier import TelegramNotifier
                                tn = TelegramNotifier(bot_token)
                                tn._notify_paper_trade_event(user_id, "tp_exit", {
                                    "token_symbol": symbol, "multiplier": multiplier,
                                })
                        except Exception:
                            pass
                        break

            except Exception as exc:
                stats["errors"] += 1
                logger.error("[PAPER] action=check_exit status=failed token=%s error=%s", symbol, str(exc)[:200])
                alert(P1, "EXIT_CHECKER", f"Error checking position {symbol}: {exc}",
                      details={"token": token_address, "user_id": user_id})

        logger.info("[PAPER] action=check_exits checked=%d tp=%d sl=%d age=%d errors=%d",
                    stats["checked"], stats["tp_exits"], stats["sl_exits"], stats["age_exits"], stats["errors"])
        if stats["errors"] > 0 and stats["errors"] >= stats["checked"] // 2:
            alert(P0, "EXIT_CHECKER", f"High error rate: {stats['errors']}/{stats['checked']} positions failed",
                  details=stats)
        return stats

    def _close_position_by_id(self, pos: dict, reason: str = "manual") -> bool:
        """Close a position using its row data directly."""
        try:
            pos_id = pos.get("id")
            user_id = pos.get("user_id", "")
            now = self._now_iso()

            self._table("paper_portfolio").update({
                "status": "closed",
                "closed_at": now,
            }).eq("id", pos_id).execute()

            self._log_event(user_id, "trade", {
                "action": "close_position",
                "reason": reason,
                "token_address": pos.get("token_address"),
                "token_symbol": pos.get("token_symbol"),
            })
            return True
        except Exception as exc:
            logger.error("[PAPER] action=close_by_id status=failed token=%s error=%s", pos.get("token_symbol"), str(exc)[:200])
            return False

    def partial_close_position(
        self, user_id: str, token_address: str, pct: int, reason: str = "partial"
    ) -> dict:
        """Close pct% (25/50/75) of an open position.

        Reduces the position size in-place and logs the partial exit.
        Returns {"sol_received": float} on success.
        """
        try:
            result = (
                self._table("paper_portfolio")
                .select("*")
                .eq("user_id", user_id)
                .eq("token_address", token_address)
                .eq("status", "open")
                .execute()
            )
            if not result.data:
                return {"sol_received": 0.0}

            pos = result.data[0]
            invested = float(pos.get("total_invested_usd", 0))
            current_value = float(pos.get("current_value_usd", 0))

            # If current_value is stale, estimate from price
            if current_value <= 0 and invested > 0:
                current_price = self._fetch_token_price(token_address)
                avg_entry = float(pos.get("avg_entry_price", 1.0))
                if current_price and avg_entry > 0:
                    current_value = invested * (current_price / avg_entry)

            fraction = pct / 100.0
            sold_value = current_value * fraction
            remaining_invested = invested * (1 - fraction)
            remaining_value = current_value * (1 - fraction)

            self._table("paper_portfolio").update({
                "total_invested_usd": round(remaining_invested, 2),
                "current_value_usd": round(remaining_value, 2),
            }).eq("id", pos["id"]).execute()

            # Verify update was applied (basic race condition detection)
            verify = self._table("paper_portfolio").select("total_invested_usd").eq("id", pos["id"]).execute()
            if verify.data:
                actual = float(verify.data[0].get("total_invested_usd", 0))
                expected = round(remaining_invested, 2)
                if abs(actual - expected) > 0.01:
                    alert(P0, "TRADE", f"Race condition detected in partial_close: expected={expected} actual={actual}",
                          details={"user_id": user_id, "token": token_address, "pct": pct})

            self._log_event(user_id, "trade", {
                "action": "partial_close",
                "pct": pct,
                "reason": reason,
                "token_address": token_address,
                "token_symbol": pos.get("token_symbol"),
                "sold_value_usd": round(sold_value, 2),
            })

            logger.info("[PAPER] action=partial_close token=%s pct=%d sold_usd=%.2f", pos.get("token_symbol"), pct, sold_value)
            return {"sol_received": sold_value}

        except Exception as exc:
            logger.error("[PAPER] action=partial_close status=failed user=%s error=%s", user_id[:8], str(exc)[:200])
            return {"sol_received": 0.0}

    def close_all_positions(self, reason: str = "manual") -> int:
        """Force-close all open positions. Returns count of positions closed."""
        try:
            result = (
                self._table("paper_portfolio")
                .select("*")
                .eq("status", "open")
                .execute()
            )
            positions = result.data or []
            closed = 0

            for pos in positions:
                if self._close_position_by_id(pos, reason=reason):
                    closed += 1

            logger.info("[PAPER] action=close_all reason=%s closed=%d total=%d", reason, closed, len(positions))
            return closed

        except Exception as exc:
            logger.error("[PAPER] action=close_all status=failed error=%s", str(exc)[:200])
            return 0

    def generate_daily_report(self) -> dict:
        """Generate a daily summary report for the paper trader."""
        try:
            # Get all positions (open + closed today)
            open_result = (
                self._table("paper_portfolio")
                .select("*")
                .eq("status", "open")
                .execute()
            )
            open_positions = open_result.data or []

            # Get today's trades
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            trades_result = (
                self._table("paper_trades")
                .select("*")
                .gte("created_at", f"{today}T00:00:00Z")
                .execute()
            )
            trades_today = trades_result.data or []

            # Compute stats
            total_invested = sum(float(p.get("total_invested_usd", 0)) for p in open_positions)
            total_current = sum(float(p.get("current_value_usd", 0)) for p in open_positions)
            total_pnl = total_current - total_invested

            winning = sum(1 for p in open_positions
                         if float(p.get("current_value_usd", 0)) > float(p.get("total_invested_usd", 0)))

            return {
                "open_positions": len(open_positions),
                "total_trades": len(trades_today),
                "winning_trades": winning,
                "total_invested_usd": round(total_invested, 2),
                "current_value_usd": round(total_current, 2),
                "total_pnl_usd": round(total_pnl, 2),
                "generated_at": self._now_iso(),
            }

        except Exception as exc:
            logger.error("[PAPER] action=daily_report status=failed error=%s", str(exc)[:200])
            return {"error": str(exc)}


# ── Singleton ──────────────────────────────────────────────────────────────

_paper_trading_manager: Optional[PaperTradingManager] = None


def get_paper_trading_manager() -> PaperTradingManager:
    """Return a shared PaperTradingManager instance."""
    global _paper_trading_manager
    if _paper_trading_manager is None:
        _paper_trading_manager = PaperTradingManager()
        logger.info("[PAPER] action=init status=ok")
    return _paper_trading_manager
