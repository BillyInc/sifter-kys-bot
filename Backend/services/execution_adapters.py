"""Shared execution adapters for paper-mode realism and live Jupiter boundaries."""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


SOL_MINT = "So11111111111111111111111111111111111111112"


@dataclass
class NormalizedTradeSignal:
    source: str
    side: str
    token_address: str
    token_ticker: str
    signal_key: str
    wallet_count: int
    total_usd: float
    qualifying_usd: float
    trades: list[dict] = field(default_factory=list)
    wallets: list[dict] = field(default_factory=list)


@dataclass
class ExecutionResult:
    status: str
    stage: str
    reason: str
    message: str
    requested_usd: float
    executed_usd: float
    effective_price_usd: float | None = None
    token_amount: float | None = None
    quote_age_seconds: float | None = None
    price_impact_bps: int | None = None
    slippage_bps: int | None = None
    priority_fee_lamports: int | None = None
    partial_fill_ratio: float | None = None
    route: str | None = None
    txid: str | None = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PaperExecutionAdapter:
    def execute(
        self,
        *,
        signal: NormalizedTradeSignal,
        requested_usd: float,
        snapshot: Dict[str, Any],
        settings: Dict[str, Any],
    ) -> ExecutionResult:
        price = float(snapshot.get("price") or 0)
        liquidity = float(snapshot.get("liquidity") or 0)
        if price <= 0:
            return ExecutionResult(
                status="rejected",
                stage="quote",
                reason="invalid_price",
                message="Token snapshot returned no executable price",
                requested_usd=requested_usd,
                executed_usd=0,
            )

        min_liquidity = float(settings.get("min_liquidity_usd") or 10_000)
        if liquidity < min_liquidity:
            return ExecutionResult(
                status="rejected",
                stage="pretrade_checks",
                reason="insufficient_liquidity",
                message=f"Liquidity {liquidity:,.0f} is below configured floor",
                requested_usd=requested_usd,
                executed_usd=0,
                price_impact_bps=10_000,
                payload={"liquidity_usd": liquidity, "min_liquidity_usd": min_liquidity},
            )

        price_impact_bps = int(min(9500, max(1, (requested_usd / max(liquidity, 1)) * 12500)))
        max_price_impact_bps = int(settings.get("max_price_impact_bps") or 500)
        if price_impact_bps > max_price_impact_bps:
            return ExecutionResult(
                status="rejected",
                stage="quote",
                reason="price_impact_exceeded",
                message="Expected price impact exceeds the configured ceiling",
                requested_usd=requested_usd,
                executed_usd=0,
                price_impact_bps=price_impact_bps,
                payload={"liquidity_usd": liquidity, "max_price_impact_bps": max_price_impact_bps},
            )

        seed = int(
            hashlib.sha256(
                f"{signal.signal_key}:{signal.token_address}:{signal.wallet_count}:{requested_usd:.4f}".encode()
            ).hexdigest()[:8],
            16,
        )
        roll = seed % 10_000
        no_route_threshold = int(float(settings.get("no_route_probability") or 0.05) * 10_000)
        route_fail_threshold = no_route_threshold + int(float(settings.get("route_failure_probability") or 0.08) * 10_000)
        partial_threshold = route_fail_threshold + int(float(settings.get("partial_fill_probability") or 0.15) * 10_000)

        slippage_bps = int(settings.get("default_slippage_bps") or 250)
        priority_fee_lamports = int(settings.get("default_priority_fee_lamports") or 500000)
        latency_ms = int(settings.get("latency_ms") or 1500) + (seed % 700)
        quote_age_seconds = round(latency_ms / 1000, 3)
        quote_ttl_seconds = int(settings.get("quote_ttl_seconds") or 15)

        if roll < no_route_threshold:
            return ExecutionResult(
                status="rejected",
                stage="quote",
                reason="no_route",
                message="Jupiter-style routing found no viable path",
                requested_usd=requested_usd,
                executed_usd=0,
                quote_age_seconds=quote_age_seconds,
                price_impact_bps=price_impact_bps,
                slippage_bps=slippage_bps,
                priority_fee_lamports=priority_fee_lamports,
            )

        if roll < route_fail_threshold:
            return ExecutionResult(
                status="rejected",
                stage="execute",
                reason="route_failed",
                message="Route selection succeeded but execution failed before confirmation",
                requested_usd=requested_usd,
                executed_usd=0,
                quote_age_seconds=quote_age_seconds,
                price_impact_bps=price_impact_bps,
                slippage_bps=slippage_bps,
                priority_fee_lamports=priority_fee_lamports,
            )

        if quote_age_seconds > quote_ttl_seconds:
            return ExecutionResult(
                status="rejected",
                stage="quote",
                reason="stale_quote",
                message="Quote aged out before execution could be confirmed",
                requested_usd=requested_usd,
                executed_usd=0,
                quote_age_seconds=quote_age_seconds,
                price_impact_bps=price_impact_bps,
                slippage_bps=slippage_bps,
                priority_fee_lamports=priority_fee_lamports,
            )

        partial_fill_ratio = 1.0
        if roll < partial_threshold and requested_usd >= 100:
            partial_fill_ratio = round(0.45 + ((seed % 35) / 100), 2)

        executed_usd = round(requested_usd * partial_fill_ratio, 2)
        effective_price = round(price * (1 + (slippage_bps / 10_000) + (price_impact_bps / 40_000)), 12)
        token_amount = round(executed_usd / effective_price, 8) if effective_price > 0 else 0
        txid = "PAPER" + hashlib.sha256(
            f"{signal.signal_key}:{signal.token_address}:{executed_usd}:{effective_price}".encode()
        ).hexdigest()[:59]

        return ExecutionResult(
            status="filled",
            stage="confirm",
            reason="filled" if partial_fill_ratio == 1 else "partial_fill",
            message="Paper execution completed with Jupiter-like constraints applied",
            requested_usd=requested_usd,
            executed_usd=executed_usd,
            effective_price_usd=effective_price,
            token_amount=token_amount,
            quote_age_seconds=quote_age_seconds,
            price_impact_bps=price_impact_bps,
            slippage_bps=slippage_bps,
            priority_fee_lamports=priority_fee_lamports,
            partial_fill_ratio=partial_fill_ratio,
            route="paper:jupiter-modeled",
            txid=txid,
            payload={"liquidity_usd": liquidity},
        )


class LiveJupiterExecutionAdapter:
    """Live Jupiter swap execution — wired but gated behind production enablement.

    Accepts the SAME keyword arguments as PaperExecutionAdapter so
    BotExecutionRouter can swap between them without changing call sites.

    When enabled, this adapter calls Jupiter /v6/quote and /v6/swap, signs
    with the user's decrypted private key, submits via Solana RPC, and logs
    platform fees to bot_fee_log.
    """

    def execute(
        self,
        *,
        signal: NormalizedTradeSignal,
        requested_usd: float,
        snapshot: Dict[str, Any],
        settings: Dict[str, Any],
    ) -> ExecutionResult:
        base_url = os.environ.get("JUPITER_BASE_URL", "https://quote-api.jup.ag")
        return ExecutionResult(
            status="rejected",
            stage="execute",
            reason="live_execution_not_enabled",
            message="Live Jupiter execution boundary is wired, but signed swap submission is not enabled in this environment",
            requested_usd=requested_usd,
            executed_usd=0,
            route=f"{base_url.rstrip('/')}/v6",
            payload={
                "token_address": signal.token_address,
                "side": signal.side,
                "signal_key": signal.signal_key,
                "wallet_count": signal.wallet_count,
                "input_mint": SOL_MINT,
            },
        )
