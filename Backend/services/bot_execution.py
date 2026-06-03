"""Bot execution boundary — the single interface for every bot buy/sell.

Design goal: build and exercise the entire menu UI and trade flows now,
against a non-live execution path, then swap in real Jupiter execution +
platform fees later **without touching any UI/handler code**.

Execution modes (``Config.BOT_EXECUTION_MODE``):
    safe_noop  (default)  Record a position, no network / no key decryption /
                          no fee. Exercises the whole UI with zero funds.
    paper                 Delegate fill realism to the existing
                          ``PaperExecutionAdapter`` (slippage, partial fills).
                          Still writes only ``bot_live_positions``.
    devnet | live         Route to ``LiveJupiterExecutionAdapter``. ONLY these
                          modes decrypt the wallet key or attach platform-fee
                          params. ``live`` submission is implemented in a later
                          sprint; the adapter is currently a wired stub.

This module NEVER imports ``PaperTrader`` (the global strategy simulator) and
NEVER writes the ``paper_trade_*`` tables. Per-user positions live only in
``bot_live_positions`` (+ ClickHouse ``bot_trade_log``). Exit logic is reused
by importing the *constants* from ``trading_rules`` — never the simulator.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import Config
from services.execution_adapters import (
    ExecutionResult,
    LiveJupiterExecutionAdapter,
    NormalizedTradeSignal,
    PaperExecutionAdapter,
)
from services.supabase_client import SCHEMA_NAME, get_supabase_client

logger = logging.getLogger(__name__)

VALID_MODES = ("safe_noop", "paper", "devnet", "live")


@dataclass
class BotTradeRequest:
    """A request to buy or sell on behalf of a single user."""

    user_id: str
    token_address: str
    side: str = "buy"                      # 'buy' | 'sell'
    requested_usd: float = 0.0
    token_symbol: Optional[str] = None
    signal_key: Optional[str] = None
    wallet_count: int = 1
    signal_type: str = "single"            # single | double | mega | manual
    trigger_type: str = "auto_elite"       # auto_elite | manual | operator
    sell_pct: Optional[int] = None         # for sells: 1-100
    wallet_public_key: Optional[str] = None
    snapshot: Dict[str, Any] = field(default_factory=dict)   # {price, liquidity}
    settings: Dict[str, Any] = field(default_factory=dict)


class BotPositionStore:
    """Reads/writes per-user positions in ``bot_live_positions`` and mirrors
    trades into ClickHouse ``bot_trade_log``.

    Method *shape* intentionally mirrors ``PaperTradingManager`` so the menu
    can read positions through one accessor — but this is a SEPARATE class on
    SEPARATE tables and shares no state with the paper systems.
    """

    def __init__(self) -> None:
        self._supabase = get_supabase_client()

    def _table(self, name: str):
        return self._supabase.schema(SCHEMA_NAME).table(name)

    # -- position lifecycle ------------------------------------------------

    def record_buy(self, req: BotTradeRequest, result: ExecutionResult) -> Optional[int]:
        """Insert (or top-up) a bot_live_positions row from a filled buy.

        Returns the position id, or None on failure (never raises into the
        execution path)."""
        try:
            existing = (
                self._table("bot_live_positions")
                .select("id")
                .eq("user_id", req.user_id)
                .eq("token_address", req.token_address)
                .eq("status", "open")
                .limit(1)
                .execute()
            )
            if existing.data:
                position_id = existing.data[0].get("id")
                logger.info(
                    "[BOT_EXEC] duplicate open buy suppressed user=%s token=%s position=%s",
                    req.user_id[:8], req.token_address[:12], position_id,
                )
                return position_id

            executed = float(result.executed_usd or 0)
            price = float(result.effective_price_usd or 0)
            token_amount = float(result.token_amount or 0)

            row = {
                "user_id": req.user_id,
                "token_address": req.token_address,
                "token_symbol": req.token_symbol or "",
                "status": "open",
                "total_invested_usd": executed,
                "avg_entry_price": price,
                "token_amount": token_amount,
                "remaining_amount": token_amount,
                "current_value_usd": executed,
                "signal_key": req.signal_key,
                "wallet_count": req.wallet_count,
                "signal_type": req.signal_type,
                "execution_mode": result.payload.get("execution_mode", Config.BOT_EXECUTION_MODE),
                "trigger_type": req.trigger_type,
                "stop_loss_pct": req.settings.get("stop_loss_pct"),
                "take_profit_x": req.settings.get("take_profit_x"),
                "trailing_stop_pct": req.settings.get("trailing_stop_pct"),
                "entry_txid": result.txid,
                "opened_at": datetime.now(timezone.utc).isoformat(),
            }
            res = self._table("bot_live_positions").insert(row).execute()
            position_id = res.data[0]["id"] if res.data else None
            self._log_trade(req, result, status="open", position_id=position_id)
            return position_id
        except Exception as exc:
            logger.error("[BOT_EXEC] record_buy failed: %s", exc)
            return None

    def record_sell(self, req: BotTradeRequest, result: ExecutionResult) -> bool:
        """Apply a (partial or full) sell to the user's open position."""
        try:
            res = (
                self._table("bot_live_positions")
                .select("*")
                .eq("user_id", req.user_id)
                .eq("token_address", req.token_address)
                .eq("status", "open")
                .limit(1)
                .execute()
            )
            if not res.data:
                logger.warning(
                    "[BOT_EXEC] record_sell: no open position for %s / %s",
                    req.user_id[:8], req.token_address[:12],
                )
                return False

            pos = res.data[0]
            pct = max(1, min(100, int(req.sell_pct or 100)))
            remaining = float(pos.get("remaining_amount") or 0)
            sold_amount = remaining * (pct / 100.0)
            new_remaining = max(0.0, remaining - sold_amount)
            realized = float(pos.get("realized_pnl_usd") or 0) + float(result.executed_usd or 0)

            update = {
                "remaining_amount": new_remaining,
                "realized_pnl_usd": realized,
                "exit_txid": result.txid,
                "last_checked_at": datetime.now(timezone.utc).isoformat(),
            }
            if new_remaining <= 0 or pct >= 100:
                update["status"] = "closed"
                update["closed_at"] = datetime.now(timezone.utc).isoformat()
                update["close_reason"] = req.trigger_type
            self._table("bot_live_positions").update(update).eq("id", pos["id"]).execute()
            self._log_trade(
                req, result,
                status="closed" if update.get("status") == "closed" else "open",
                position_id=pos["id"],
            )
            return True
        except Exception as exc:
            logger.error("[BOT_EXEC] record_sell failed: %s", exc)
            return False

    # -- analytics ---------------------------------------------------------

    def _log_trade(
        self,
        req: BotTradeRequest,
        result: ExecutionResult,
        *,
        status: str,
        position_id: Optional[int],
    ) -> None:
        """Best-effort insert into ClickHouse bot_trade_log. Never raises."""
        try:
            from services.clickhouse_client import CH_DATABASE, get_clickhouse_client

            ch = get_clickhouse_client()
            if ch is None:
                return
            ch.insert(
                table="bot_trade_log",
                data=[[
                    str(uuid.uuid4()),
                    str(req.user_id),
                    req.signal_key or "",
                    req.token_address,
                    req.token_symbol or "",
                    req.side,
                    req.trigger_type,
                    req.signal_type,
                    int(req.wallet_count),
                    result.payload.get("execution_mode", Config.BOT_EXECUTION_MODE),
                    status,
                    result.stage or "",
                    result.reason or "",
                    float(result.requested_usd or 0),
                    float(result.executed_usd or 0),
                    float(result.effective_price_usd or 0),
                    int(result.price_impact_bps or 0),
                    int(result.slippage_bps or 0),
                    0.0,   # realized_pnl_usd (computed on close rollups)
                    0.0,   # roi_pct
                    result.txid or "",
                    datetime.now(timezone.utc).replace(tzinfo=None),
                ]],
                database=CH_DATABASE,
                column_names=[
                    "trade_id", "user_id", "signal_key", "token_address",
                    "token_symbol", "side", "trigger_type", "signal_type",
                    "wallet_count", "execution_mode", "status", "stage",
                    "reason", "requested_usd", "executed_usd",
                    "effective_price_usd", "price_impact_bps", "slippage_bps",
                    "realized_pnl_usd", "roi_pct", "txid", "created_at",
                ],
            )
        except Exception as exc:
            logger.debug("[BOT_EXEC] bot_trade_log insert skipped: %s", exc)


class BotExecutionRouter:
    """Selects an execution adapter by mode and returns a normalized
    ``ExecutionResult``. The UI always calls ``execute()`` — going live is a
    config flip, not a code change."""

    def __init__(self) -> None:
        self._paper = PaperExecutionAdapter()
        self._store = BotPositionStore()

    # -- public API --------------------------------------------------------

    def execute(self, req: BotTradeRequest) -> ExecutionResult:
        mode = self._resolve_mode()

        # Kill switch is honored for any real-money path.
        if mode in ("devnet", "live") and self._kill_switch_active():
            return self._rejected(req, "kill_switch", "Kill switch is active")

        if mode == "safe_noop":
            result = self._execute_safe_noop(req)
        elif mode == "paper":
            result = self._execute_paper(req)
        else:  # devnet | live
            result = self._execute_live(req, mode)

        # Persist the position on a successful fill.
        if result.status == "filled":
            if req.side == "sell":
                self._store.record_sell(req, result)
            else:
                self._store.record_buy(req, result)
        return result

    # -- mode resolution ---------------------------------------------------

    def _resolve_mode(self) -> str:
        mode = (Config.BOT_EXECUTION_MODE or "safe_noop").lower()
        return mode if mode in VALID_MODES else "safe_noop"

    def _kill_switch_active(self) -> bool:
        try:
            from services.redis_pool import get_redis_client

            return bool(get_redis_client().get("sifter:kill_switch"))
        except Exception:
            # Fail closed: if we can't check, assume the kill switch is on.
            return True

    # -- adapters ----------------------------------------------------------

    def _execute_safe_noop(self, req: BotTradeRequest) -> ExecutionResult:
        """Record-only fill: no network, no wallet decryption, no fee.

        Uses the snapshot price when present (so PnL math is sensible during
        UI testing), otherwise a nominal $1 so token math stays finite."""
        price = float(req.snapshot.get("price") or 0) or 1.0
        executed = float(req.requested_usd or 0)
        token_amount = round(executed / price, 8) if price > 0 else 0.0
        txid = "NOOP" + hashlib.sha256(
            f"{req.user_id}:{req.token_address}:{req.side}:{executed}:{time.time()}".encode()
        ).hexdigest()[:56]
        return ExecutionResult(
            status="filled",
            stage="confirm",
            reason="safe_noop",
            message="Recorded without on-chain execution (safe_noop mode)",
            requested_usd=executed,
            executed_usd=executed,
            effective_price_usd=price,
            token_amount=token_amount,
            route="bot:safe_noop",
            txid=txid,
            payload={"execution_mode": "safe_noop"},
        )

    def _execute_paper(self, req: BotTradeRequest) -> ExecutionResult:
        """Realistic fills via the existing PaperExecutionAdapter."""
        signal = NormalizedTradeSignal(
            source="bot",
            side=req.side,
            token_address=req.token_address,
            token_ticker=req.token_symbol or "",
            signal_key=req.signal_key or f"bot:{req.token_address}",
            wallet_count=req.wallet_count,
            total_usd=req.requested_usd,
            qualifying_usd=req.requested_usd,
        )
        result = self._paper.execute(
            signal=signal,
            requested_usd=req.requested_usd,
            snapshot=req.snapshot or {},
            settings=req.settings or {},
        )
        result.payload = {**(result.payload or {}), "execution_mode": "paper"}
        return result

    def _execute_live(self, req: BotTradeRequest, mode: str) -> ExecutionResult:
        """Route to the live Jupiter adapter. Only here are fee params and
        wallet-key decryption ever reached. Today the adapter is a wired stub;
        signed-swap submission + fee wiring land in later sprints."""
        result = LiveJupiterExecutionAdapter().execute(
            user_id=req.user_id,
            token_address=req.token_address,
            side=req.side,
            usd_amount=req.requested_usd,
            wallet_public_key=req.wallet_public_key,
        )
        result.payload = {**(result.payload or {}), "execution_mode": mode}
        return result

    def _rejected(self, req: BotTradeRequest, reason: str, message: str) -> ExecutionResult:
        return ExecutionResult(
            status="rejected",
            stage="pretrade_checks",
            reason=reason,
            message=message,
            requested_usd=float(req.requested_usd or 0),
            executed_usd=0,
            payload={"execution_mode": self._resolve_mode()},
        )


_router: Optional[BotExecutionRouter] = None


def get_bot_executor() -> BotExecutionRouter:
    """Return the module-level singleton execution router."""
    global _router
    if _router is None:
        _router = BotExecutionRouter()
    return _router
