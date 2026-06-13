"""Paper trading engine wired to the live Elite 15 signal path."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

from config import Config
from services.execution_adapters import NormalizedTradeSignal, PaperExecutionAdapter
from services.paper_trade_runtime import get_paper_trade_runtime
from services.supabase_client import SCHEMA_NAME, get_supabase_client
from services.trading_rules import (
    DEFAULT_DAILY_TRADE_LIMIT,
    DEFAULT_HOURLY_TRADE_LIMIT,
    DEFAULT_MIN_ELITE_USD,
    EXIT_FRACTIONS,
    MAX_CONCURRENT_POSITIONS,
    MAX_DEPLOYMENT_PCT,
    TAKE_PROFIT_MULTIPLIERS,
    calculate_position_size,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PaperPosition:
    token_address: str
    token_ticker: str
    entry_price: float
    entry_size_usd: float
    token_amount: float
    wallet_count: int
    signal_type: str
    signal_key: str
    opened_at: float
    realized_pnl_usd: float = 0.0
    remaining_amount: float = 0.0
    exits_taken: tuple[float, ...] = ()
    peak_multiple: float = 1.0

    def __post_init__(self):
        if not self.remaining_amount:
            self.remaining_amount = self.token_amount


class PaperTrader:
    """Simulate the existing Elite 15 execution rules without sending swaps."""

    def __init__(
        self,
        *,
        starting_balance_usd: Optional[float] = None,
        hourly_limit: int = DEFAULT_HOURLY_TRADE_LIMIT,
        daily_limit: int = DEFAULT_DAILY_TRADE_LIMIT,
    ):
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME
        self.starting_balance_usd = float(
            starting_balance_usd or os.environ.get("PAPER_TRADING_START_USD", "10000")
        )
        self.hourly_limit = hourly_limit
        self.daily_limit = daily_limit
        # Token price fetches go through get_st_client() in _fetch_token_snapshot
        self.runtime = get_paper_trade_runtime()
        self.execution_adapter = PaperExecutionAdapter()
        self.lock = threading.Lock()
        self.open_positions: Dict[str, PaperPosition] = {}
        self.closed_token_set: set[str] = set()
        self._load_state()

    def _table(self, name: str):
        return self.supabase.schema(self.schema).table(name)

    def _load_state(self):
        try:
            open_rows = (
                self._table("paper_trade_positions")
                .select("*")
                .eq("status", "open")
                .execute()
                .data
                or []
            )
            for row in open_rows:
                self.open_positions[row["token_address"]] = PaperPosition(
                    token_address=row["token_address"],
                    token_ticker=row.get("token_ticker") or "UNKNOWN",
                    entry_price=float(row.get("entry_price_usd") or 0),
                    entry_size_usd=float(row.get("entry_size_usd") or 0),
                    token_amount=float(row.get("token_amount") or 0),
                    wallet_count=int(row.get("wallet_count") or 1),
                    signal_type=row.get("signal_type") or "single",
                    signal_key=row.get("signal_key") or "",
                    opened_at=datetime.fromisoformat(
                        row["opened_at"].replace("Z", "+00:00")
                    ).timestamp(),
                    realized_pnl_usd=float(row.get("realized_pnl_usd") or 0),
                    remaining_amount=float(row.get("remaining_amount") or 0),
                    exits_taken=tuple(row.get("exits_taken") or []),
                    peak_multiple=float(row.get("peak_multiple") or 1),
                )

            closed_rows = (
                self._table("paper_trade_positions")
                .select("token_address")
                .neq("status", "open")
                .execute()
                .data
                or []
            )
            self.closed_token_set = {
                row["token_address"] for row in closed_rows if row.get("token_address")
            }
        except Exception as exc:
            print(f"[PAPER TRADER] State restore failed: {exc}")

    # Sources this paper trader will simulate. ``cluster`` is the new co-entry path;
    # ``elite15`` is kept for backward compatibility (single-wallet legacy); ``single``/
    # ``manual`` cover List-A single-wallet and manual-trader paper variants.
    ACCEPTED_SOURCES = frozenset({"elite15", "cluster", "single", "manual"})

    def process_signal(self, signal: Dict):
        if signal.get("source") not in self.ACCEPTED_SOURCES or signal.get("side") != "buy":
            return

        settings = self.runtime.get_settings()
        if not settings.get("paper_trader_enabled", False):
            self.runtime.log(
                severity="debug",
                component="paper_trader",
                event_type="signal_ignored",
                status="disabled",
                message=f"{signal.get('source')} signal ignored because paper trader is stopped",
                signal_key=signal.get("signal_key"),
                token_address=signal.get("token_address"),
                payload={"source": signal.get("source"), "side": signal.get("side")},
            )
            return

        token_address = signal.get("token_address")
        if not token_address:
            return

        with self.lock:
            outcome = self._evaluate_signal_locked(signal)
            self._log_event(signal, outcome)
            if outcome["status"] != "entered":
                return

            position = outcome["position"]
            self.open_positions[token_address] = position
            self._persist_new_position(position, signal, outcome)

    def check_exits(self):
        with self.lock:
            for token_address in list(self.open_positions.keys()):
                position = self.open_positions[token_address]
                snapshot = self._fetch_token_snapshot(token_address)
                if not snapshot:
                    continue

                current_price = snapshot["price"]
                if current_price <= 0 or position.entry_price <= 0:
                    continue

                multiple = current_price / position.entry_price
                position.peak_multiple = max(position.peak_multiple, multiple)

                if multiple <= 0.30:
                    self._close_position(position, current_price, "dead_token", multiple)
                    continue

                age_days = (time.time() - position.opened_at) / 86400
                if age_days >= 14:
                    self._close_position(position, current_price, "max_age", multiple)
                    continue

                for target in TAKE_PROFIT_MULTIPLIERS:
                    if target in position.exits_taken or multiple < target:
                        continue
                    self._take_profit(position, current_price, multiple, target)
                    if position.remaining_amount <= 0:
                        break

    def get_summary(self) -> Dict:
        try:
            rows = self._table("paper_trade_positions").select("*").execute().data or []
            events = self._table("paper_trade_events").select("*").execute().data or []
        except Exception as exc:
            return {"error": str(exc)}

        open_rows = [row for row in rows if row.get("status") == "open"]
        closed_rows = [row for row in rows if row.get("status") != "open"]
        entered_rows = [row for row in rows if row.get("entry_size_usd")]
        realized = sum(float(row.get("realized_pnl_usd") or 0) for row in closed_rows) + sum(
            float(row.get("realized_pnl_usd") or 0) for row in open_rows
        )
        portfolio = self._portfolio_state()
        skipped = [event for event in events if event.get("event_type") == "skipped"]

        return {
            "portfolio": portfolio,
            "signals": {
                "seen": len([event for event in events if event.get("event_type") == "signal"]),
                "entered": len(entered_rows),
                "skipped": len(skipped),
                "open_positions": len(open_rows),
                "closed_positions": len(closed_rows),
                "realized_pnl_usd": round(realized, 2),
            },
            "skip_breakdown": _count_by(skipped, "reason"),
            "recent_positions": rows[:20],
        }

    def get_failure_report(self) -> Dict:
        summary = self.get_summary()
        if summary.get("error"):
            return summary

        issues: List[str] = []
        actions: List[str] = []
        signals = summary["signals"]
        skip_breakdown = summary["skip_breakdown"]

        if signals["seen"] == 0:
            issues.append("no_elite15_signals")
            actions.append("Confirm Elite 15 wallets are being cached and polled by the monitor.")
        if signals["seen"] > 0 and signals["entered"] == 0:
            issues.append("all_signals_skipped")
            actions.append("Inspect skip reasons before live trading; the signal path is producing no executable trades.")
        if skip_breakdown.get("duplicate_token", 0) > 0:
            issues.append("duplicate_signal_attempts")
            actions.append("Review duplicate suppression before enabling live execution.")
        if skip_breakdown.get("hourly_limit", 0) > 0 or skip_breakdown.get("daily_limit", 0) > 0:
            issues.append("trade_caps_triggering")
            actions.append("Trade caps are firing in paper mode; validate that limits match the rollout plan.")
        if summary["portfolio"]["change_pct"] < -20:
            issues.append("paper_drawdown_gt_20pct")
            actions.append("Paper performance is weak; do not go live until the strategy or wallet set is adjusted.")

        return {
            "issues_found": len(issues),
            "should_tweak": bool(issues),
            "issues": issues,
            "actions": actions,
            "summary": summary,
        }

    def get_readiness_report(self) -> Dict:
        summary = self.get_summary()
        failure_report = self.get_failure_report()
        gates = {
            "elite15_signals_seen": summary.get("signals", {}).get("seen", 0) >= 5,
            "paper_entries_recorded": summary.get("signals", {}).get("entered", 0) >= 3,
            "no_critical_failures": failure_report.get("issues_found", 0) == 0,
            "telegram_live_executor_stubbed": False,
        }
        ready = all(gates.values())
        return {
            "ready_for_live": ready,
            "gates": gates,
            "summary": summary,
            "failure_report": failure_report,
            "notes": [
                "Telegram auto-trade now uses the live execution adapter boundary; signed Jupiter swap submission is still disabled until wallet signing/RPC execution is explicitly enabled.",
                "Paper trading mirrors sizing, duplicate prevention, caps, TP ladder, and Jupiter-style execution friction, but it does not prove private orderflow or signing behavior yet.",
            ],
        }

    def _evaluate_signal_locked(self, signal: Dict) -> Dict:
        token_address = signal["token_address"]
        total_exposure = sum(pos.entry_size_usd for pos in self.open_positions.values())

        if token_address in self.open_positions or token_address in self.closed_token_set:
            return {"event_type": "skipped", "status": "skipped", "reason": "duplicate_token"}

        if self._count_recent_entries(3600) >= self.hourly_limit:
            return {"event_type": "skipped", "status": "skipped", "reason": "hourly_limit"}

        if self._count_recent_entries(86400) >= self.daily_limit:
            return {"event_type": "skipped", "status": "skipped", "reason": "daily_limit"}

        token_address = signal.get("token_address", "")

        logger.info(
            "[PAPER] action=evaluate token=%s wallet_count=%d open_positions=%d",
            token_address[:8],
            int(signal.get("wallet_count") or 1),
            len(self.open_positions),
        )

        if len(self.open_positions) >= MAX_CONCURRENT_POSITIONS:
            logger.info(
                "[PAPER] action=skip status=skipped token=%s reason=max_positions_reached "
                "open=%d max=%d",
                token_address[:8], len(self.open_positions), MAX_CONCURRENT_POSITIONS,
            )
            return {"event_type": "skipped", "status": "skipped", "reason": "max_positions_reached"}

        portfolio = self._portfolio_state()
        deployment_pct = portfolio.get("deployment_pct", 0.0)
        if deployment_pct >= MAX_DEPLOYMENT_PCT:
            logger.info(
                "[PAPER] action=skip status=skipped token=%s reason=deployment_cap_reached "
                "deployed_pct=%.1f%% cap=%.1f%%",
                token_address[:8], deployment_pct * 100, MAX_DEPLOYMENT_PCT * 100,
            )
            return {
                "event_type": "skipped",
                "status": "skipped",
                "reason": "deployment_cap_reached",
                "metadata": {"deployed_pct": round(deployment_pct * 100, 1)},
            }

        qualifying_usd = max(
            [float(trade.get("usd_value") or 0) for trade in signal.get("trades") or []] or [0.0]
        )
        if qualifying_usd < DEFAULT_MIN_ELITE_USD:
            return {"event_type": "skipped", "status": "skipped", "reason": "below_min_conviction"}

        snapshot = self._fetch_token_snapshot(token_address)
        if not snapshot:
            return {"event_type": "skipped", "status": "skipped", "reason": "snapshot_unavailable"}
        if not snapshot["safe"]:
            return {"event_type": "skipped", "status": "skipped", "reason": snapshot["reason"]}

        sizing = calculate_position_size(
            portfolio_total=portfolio["portfolio_total_usd"],
            wallet_count=int(signal.get("wallet_count") or 1),
            existing_position=0,
            total_exposure=total_exposure,
        )
        if sizing.recommended_usd <= 0:
            return {"event_type": "skipped", "status": "skipped", "reason": "no_capacity"}

        entry_price = float(snapshot["price"] or 0)
        if entry_price <= 0:
            return {"event_type": "skipped", "status": "skipped", "reason": "invalid_price"}

        normalized_signal = NormalizedTradeSignal(
            source=signal.get("source") or "elite15",
            side=signal.get("side") or "buy",
            token_address=token_address,
            token_ticker=signal.get("token_ticker") or snapshot["ticker"] or "UNKNOWN",
            signal_key=signal.get("signal_key") or token_address,
            wallet_count=int(signal.get("wallet_count") or 1),
            total_usd=float(signal.get("total_usd") or 0),
            qualifying_usd=qualifying_usd,
            trades=signal.get("trades") or [],
            wallets=signal.get("wallets") or [],
        )
        execution = self.execution_adapter.execute(
            signal=normalized_signal,
            requested_usd=sizing.recommended_usd,
            snapshot=snapshot,
            settings=self.runtime.get_settings(),
        )
        if execution.status != "filled":
            severity = "warning" if execution.stage in {"quote", "execute"} else "info"
            self.runtime.log(
                severity=severity,
                component="paper_trader",
                event_type="execution_rejected",
                status=execution.status,
                message=execution.message,
                signal_key=normalized_signal.signal_key,
                token_address=token_address,
                payload=execution.to_dict(),
            )
            return {
                "event_type": "skipped",
                "status": "skipped",
                "reason": execution.reason,
                "snapshot": snapshot,
                "sizing": sizing,
                "execution": execution.to_dict(),
            }

        entry_price = float(execution.effective_price_usd or entry_price)
        token_amount = float(execution.token_amount or 0)
        # Cluster co-entry positions trace back to <cluster_id>:<token> so we can later
        # attribute a position to the cluster + variant that opened it (§4A).
        source = signal.get("source") or "elite15"
        signal_type = "cluster" if source == "cluster" else sizing.signal_type
        position = PaperPosition(
            token_address=token_address,
            token_ticker=signal.get("token_ticker") or snapshot["ticker"] or "UNKNOWN",
            entry_price=entry_price,
            entry_size_usd=float(execution.executed_usd),
            token_amount=token_amount,
            wallet_count=int(signal.get("wallet_count") or 1),
            signal_type=signal_type,
            signal_key=signal.get("signal_key") or "",
            opened_at=time.time(),
        )
        return {
            "event_type": "signal",
            "status": "entered",
            "reason": "entered",
            "snapshot": snapshot,
            "sizing": sizing,
            "execution": execution.to_dict(),
            "position": position,
        }

    def _fetch_token_snapshot(self, token_address: str) -> Optional[Dict]:
        """Fetch token price + safety via shared ST client (rate limited + cached)."""
        try:
            from services.solana_tracker_client import get_st_client
            data = get_st_client().get_token_info(token_address)
            if not data:
                return None
            pools = data.get("pools") or []
            pool = max(pools, key=lambda row: row.get("liquidity", {}).get("usd", 0)) if pools else {}
            security = pool.get("security") or {}
            liquidity = float(pool.get("liquidity", {}).get("usd") or 0)
            price = float(pool.get("price", {}).get("usd") or 0)
            honeypot = bool(security.get("honeypot"))

            safe = True
            reason = "ok"
            if honeypot:
                safe = False
                reason = "honeypot"
            elif liquidity < 10_000:
                safe = False
                reason = "low_liquidity"
            else:
                # Token-level rug gate: mint/freeze revoked, not rugged, LP
                # burned (or pre-graduation pump.fun). Reuse the data we just
                # fetched so this adds no extra API call.
                from services.bot_security import check_token_safety
                token_safe, token_reason = check_token_safety(token_address, token_info=data)
                if not token_safe:
                    safe = False
                    reason = token_reason or "unsafe_token"

            return {
                "price": price,
                "liquidity": liquidity,
                "safe": safe,
                "reason": reason,
                "ticker": (data.get("token") or {}).get("symbol"),
            }
        except Exception:
            return None

    def _count_recent_entries(self, seconds: int) -> int:
        since = datetime.fromtimestamp(time.time() - seconds, tz=timezone.utc).isoformat()
        try:
            rows = (
                self._table("paper_trade_events")
                .select("id", count="exact")
                .eq("event_type", "entry")
                .gte("created_at", since)
                .execute()
            )
            return rows.count or 0
        except Exception:
            return 0

    def _portfolio_state(self) -> Dict:
        try:
            rows = self._table("paper_trade_positions").select("*").execute().data or []
        except Exception as exc:
            logger.error("[PORTFOLIO] action=fetch status=error error=%s", str(exc)[:200])
            rows = []

        realized = sum(float(row.get("realized_pnl_usd") or 0) for row in rows)

        deployed = 0.0
        for row in rows:
            if row.get("status") != "open":
                continue
            entry_size = float(row.get("entry_size_usd") or 0)
            token_amount = float(row.get("token_amount") or 0)
            remaining = float(row.get("remaining_amount") or 0)
            if token_amount > 0:
                deployed += entry_size * (remaining / token_amount)
            else:
                deployed += entry_size

        available = self.starting_balance_usd + realized - deployed
        portfolio_total = max(self.starting_balance_usd + realized, 0.0)
        deployment_pct = deployed / max(portfolio_total, 1.0)

        logger.info(
            "[PORTFOLIO] total_usd=%.2f deployed_usd=%.2f available_usd=%.2f "
            "realized_pnl=%.2f deployment_pct=%.1f%%",
            portfolio_total, deployed, available, realized, deployment_pct * 100,
        )

        return {
            "starting_balance_usd": round(self.starting_balance_usd, 2),
            "available_cash_usd": round(available, 2),
            "deployed_usd": round(deployed, 2),
            "realized_pnl_usd": round(realized, 2),
            "portfolio_total_usd": round(portfolio_total, 2),
            "deployment_pct": round(deployment_pct, 4),
            "change_pct": round(
                (((self.starting_balance_usd + realized) / self.starting_balance_usd) - 1) * 100, 2
            ) if self.starting_balance_usd else 0.0,
        }

    def _persist_new_position(self, position: PaperPosition, signal: Dict, outcome: Dict):
        self._table("paper_trade_positions").insert(
            {
                "token_address": position.token_address,
                "token_ticker": position.token_ticker,
                "entry_price_usd": position.entry_price,
                "entry_size_usd": position.entry_size_usd,
                "token_amount": position.token_amount,
                "remaining_amount": position.remaining_amount,
                "status": "open",
                "wallet_count": position.wallet_count,
                "signal_type": position.signal_type,
                "signal_key": position.signal_key,
                "signal_wallets": [wallet.get("wallet") for wallet in signal.get("wallets") or []],
                "metadata": {
                    "signal": signal,
                    "snapshot": outcome.get("snapshot"),
                    "recommended_usd": outcome["sizing"].recommended_usd,
                    "execution": outcome.get("execution"),
                },
                "opened_at": _utc_now_iso(),
                "last_checked_at": _utc_now_iso(),
                "realized_pnl_usd": 0,
                "peak_multiple": 1,
                "exits_taken": [],
            }
        ).execute()
        self._log_entry_event(position, signal, outcome)
        # Self-describing entry log (§5): cluster + triggering wallets + fill/chase, so the
        # live position's full provenance is reconstructable from logs alone.
        trigger_price = signal.get("trigger_price")
        fill_price = position.entry_price
        chase_ratio = (
            round(fill_price / trigger_price, 4)
            if trigger_price and float(trigger_price) > 0 and fill_price else None
        )
        entry_payload = {
            "variant_id": f"{signal.get('cluster_id')}|live" if signal.get("cluster_id") else None,
            "cluster_id": signal.get("cluster_id"),
            "source": signal.get("source"),
            "trigger_wallets": signal.get("trigger_wallets"),
            "wallet_tiers": signal.get("wallet_tiers"),
            "entry_style": signal.get("entry_style"),
            "trigger_price": trigger_price,
            "fill_price": fill_price,
            "chase_ratio": chase_ratio,
            "signal_strength": signal.get("signal_strength"),
            "raw_event_id": signal.get("raw_event_id"),
            "execution": outcome.get("execution"),
        }
        self.runtime.log(
            severity="info",
            component="paper_trader",
            event_type="entry_filled",
            status="filled",
            message="Paper entry filled",
            signal_key=position.signal_key,
            token_address=position.token_address,
            payload=entry_payload,
        )
        self.runtime.update_active_run_summary(self.get_summary())

    def _take_profit(self, position: PaperPosition, current_price: float, multiple: float, target: float):
        sell_fraction = EXIT_FRACTIONS[target]
        amount_to_sell = position.remaining_amount if target == 30.0 else position.remaining_amount * sell_fraction
        proceeds = amount_to_sell * current_price
        cost_basis = amount_to_sell * position.entry_price
        pnl = proceeds - cost_basis
        position.remaining_amount = max(0.0, position.remaining_amount - amount_to_sell)
        position.realized_pnl_usd += pnl
        position.exits_taken = tuple(sorted((*position.exits_taken, target)))

        logger.info(
            "[PAPER] action=tp status=ok token=%s target=%.0fx multiple=%.2f "
            "proceeds_usd=%.2f pnl_usd=%.2f remaining=%.6f",
            position.token_address[:8], target, multiple,
            round(proceeds, 2), round(pnl, 2), position.remaining_amount,
        )

        self._table("paper_trade_events").insert(
            {
                "token_address": position.token_address,
                "token_ticker": position.token_ticker,
                "event_type": "take_profit",
                "reason": f"tp_{int(target)}x",
                "signal_key": position.signal_key,
                "wallet_count": position.wallet_count,
                "usd_amount": round(proceeds, 2),
                "price_usd": current_price,
                "multiple": round(multiple, 4),
                "metadata": {
                    "target": target,
                    "amount_sold": amount_to_sell,
                    "pnl_usd": pnl,
                },
            }
        ).execute()

        self._table("paper_trade_positions").update(
            {
                "remaining_amount": position.remaining_amount,
                "realized_pnl_usd": round(position.realized_pnl_usd, 2),
                "last_checked_at": _utc_now_iso(),
                "peak_multiple": round(position.peak_multiple, 4),
                "exits_taken": list(position.exits_taken),
            }
        ).eq("signal_key", position.signal_key).eq("status", "open").execute()

        if position.remaining_amount <= 0:
            self._close_position(position, current_price, "tp_30x", multiple)

    def _close_position(self, position: PaperPosition, current_price: float, reason: str, multiple: float):
        if position.remaining_amount > 0:
            proceeds = position.remaining_amount * current_price
            cost_basis = position.remaining_amount * position.entry_price
            pnl = proceeds - cost_basis
            position.realized_pnl_usd += pnl

            logger.info(
                "[PAPER] action=close status=ok token=%s reason=%s multiple=%.2f "
                "pnl_usd=%.2f peak_multiple=%.2f",
                position.token_address[:8], reason, multiple,
                round(pnl, 2), position.peak_multiple,
            )

            self._table("paper_trade_events").insert(
                {
                    "token_address": position.token_address,
                    "token_ticker": position.token_ticker,
                    "event_type": "close",
                    "reason": reason,
                    "signal_key": position.signal_key,
                    "wallet_count": position.wallet_count,
                    "usd_amount": round(proceeds, 2),
                    "price_usd": current_price,
                    "multiple": round(multiple, 4),
                    "metadata": {
                        "remaining_amount": position.remaining_amount,
                        "pnl_usd": pnl,
                    },
                }
            ).execute()

        self._table("paper_trade_positions").update(
            {
                "status": "closed",
                "closed_at": _utc_now_iso(),
                "close_reason": reason,
                "remaining_amount": 0,
                "realized_pnl_usd": round(position.realized_pnl_usd, 2),
                "last_checked_at": _utc_now_iso(),
                "peak_multiple": round(position.peak_multiple, 4),
                "exits_taken": list(position.exits_taken),
            }
        ).eq("signal_key", position.signal_key).eq("status", "open").execute()

        self.closed_token_set.add(position.token_address)
        self.open_positions.pop(position.token_address, None)

    def _log_event(self, signal: Dict, outcome: Dict):
        self._table("paper_trade_events").insert(
            {
                "token_address": signal.get("token_address"),
                "token_ticker": signal.get("token_ticker", "UNKNOWN"),
                "event_type": outcome["event_type"],
                "reason": outcome["reason"],
                "signal_key": signal.get("signal_key"),
                "wallet_count": signal.get("wallet_count", 1),
                "usd_amount": signal.get("total_usd", 0),
                "price_usd": (outcome.get("snapshot") or {}).get("price", signal.get("price", 0)),
                "multiple": None,
                "metadata": {"signal": signal},
            }
        ).execute()

    def _log_entry_event(self, position: PaperPosition, signal: Dict, outcome: Dict):
        self._table("paper_trade_events").insert(
            {
                "token_address": position.token_address,
                "token_ticker": position.token_ticker,
                "event_type": "entry",
                "reason": position.signal_type,
                "signal_key": position.signal_key,
                "wallet_count": position.wallet_count,
                "usd_amount": position.entry_size_usd,
                "price_usd": position.entry_price,
                "multiple": 1,
                "metadata": {
                    "signal": signal,
                    "snapshot": outcome.get("snapshot"),
                    "token_amount": position.token_amount,
                    "execution": outcome.get("execution"),
                },
            }
        ).execute()


def _count_by(rows: List[Dict], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        value = row.get(key) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts
