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
    """Live Jupiter swap execution (devnet + mainnet).

    Accepts the SAME keyword arguments as PaperExecutionAdapter so
    BotExecutionRouter can swap between them without changing call sites.

    Flow:
      1. GET  {JUPITER_BASE_URL}/v6/quote   — inputMint, outputMint, amount,
         slippageBps, platformFeeBps
      2. POST {JUPITER_BASE_URL}/v6/swap    — serialized tx with feeAccount,
         prioritizationFeeLamports (gas/MEV), dynamicComputeUnitLimit
      3. Sign with the user's decrypted keypair (solders)
      4. Submit + confirm via Solana RPC (solana)
      5. Return real txid, executed_usd, price_impact_bps, slippage_bps, fee

    On ANY failure → status="rejected" and NO position is written by the caller
    (data-integrity rule). solders/solana are imported lazily so paper/safe_noop
    modes work without them installed.
    """

    def execute(
        self,
        *,
        signal: NormalizedTradeSignal,
        requested_usd: float,
        snapshot: Dict[str, Any],
        settings: Dict[str, Any],
    ) -> ExecutionResult:
        import time as _time
        base_url = os.environ.get("JUPITER_BASE_URL", "https://quote-api.jup.ag").rstrip("/")
        rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")

        def _reject(stage: str, reason: str, msg: str) -> ExecutionResult:
            return ExecutionResult(
                status="rejected", stage=stage, reason=reason, message=msg,
                requested_usd=requested_usd, executed_usd=0,
                route=f"{base_url}/v6",
                payload={"token_address": signal.token_address, "side": signal.side,
                         "signal_key": signal.signal_key},
            )

        # --- Lazy imports (only needed for real execution) ---
        try:
            import requests as _requests
            from solders.keypair import Keypair
            from solders.transaction import VersionedTransaction
            from solders.signature import Signature  # noqa: F401
            from solana.rpc.api import Client as RpcClient
        except ImportError as exc:
            return _reject("init", "missing_solana_libs",
                           f"solders/solana not installed: {exc}")

        # --- Resolve the user's keypair (decrypted) ---
        keypair = settings.get("_keypair")  # BotExecutionRouter injects this
        if keypair is None:
            return _reject("wallet", "no_wallet_key",
                           "No decrypted wallet key supplied to live adapter")
        try:
            kp = Keypair.from_bytes(bytes(keypair)) if not isinstance(keypair, Keypair) else keypair
        except Exception as exc:
            return _reject("wallet", "bad_keypair", f"Could not load keypair: {exc}")

        # --- Mints / amounts ---
        is_buy = signal.side in ("buy", "swap")
        input_mint = SOL_MINT if is_buy else signal.token_address
        output_mint = signal.token_address if is_buy else SOL_MINT
        sol_price = float(snapshot.get("sol_price_usd") or 0)
        if is_buy:
            if sol_price <= 0:
                return _reject("quote", "no_sol_price", "SOL/USD price unavailable for sizing")
            amount_lamports = int((requested_usd / sol_price) * 1e9)
        else:
            # Selling: amount is in token base units, from the position snapshot.
            amount_lamports = int(snapshot.get("sell_token_amount") or 0)
        if amount_lamports <= 0:
            return _reject("quote", "zero_amount", "Computed swap amount is zero")

        slippage_bps = int(settings.get("slippage_bps") or 100)
        platform_fee_bps = int(settings.get("platform_fee_bps") or 0)
        mev_protection = bool(settings.get("mev_protection", True))

        # --- 1. Quote ---
        try:
            q = _requests.get(f"{base_url}/v6/quote", params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": amount_lamports,
                "slippageBps": slippage_bps,
                **({"platformFeeBps": platform_fee_bps} if platform_fee_bps else {}),
            }, timeout=10)
            if q.status_code != 200:
                return _reject("quote", "quote_failed", f"Jupiter quote HTTP {q.status_code}: {q.text[:120]}")
            quote = q.json()
            if not quote or quote.get("error"):
                return _reject("quote", "no_route", f"No route: {quote.get('error') if quote else 'empty'}")
        except Exception as exc:
            return _reject("quote", "quote_error", str(exc))

        price_impact_bps = int(float(quote.get("priceImpactPct") or 0) * 10000)

        # --- 2. Swap transaction ---
        try:
            swap_body: Dict[str, Any] = {
                "quoteResponse": quote,
                "userPublicKey": str(kp.pubkey()),
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
            }
            # MEV protection / priority: higher priority fee = faster + harder to sandwich.
            # An explicit priority_fee_lamports overrides "auto" — the router ramps
            # this on network congestion / retries so fills land under load.
            explicit_priority = settings.get("priority_fee_lamports")
            if explicit_priority is not None and int(explicit_priority) > 0:
                swap_body["prioritizationFeeLamports"] = int(explicit_priority)
                swap_body["asLegacyTransaction"] = False
            elif mev_protection:
                swap_body["prioritizationFeeLamports"] = "auto"
                swap_body["asLegacyTransaction"] = False
            else:
                swap_body["prioritizationFeeLamports"] = 0
            # Platform fee account (treasury) — only when a fee is configured.
            fee_account = settings.get("fee_account")
            if platform_fee_bps and fee_account:
                swap_body["feeAccount"] = fee_account

            s = _requests.post(f"{base_url}/v6/swap", json=swap_body, timeout=15)
            if s.status_code != 200:
                return _reject("swap", "swap_failed", f"Jupiter swap HTTP {s.status_code}: {s.text[:120]}")
            swap_tx_b64 = s.json().get("swapTransaction")
            prioritization = int(s.json().get("prioritizationFeeLamports") or 0)
            if not swap_tx_b64:
                return _reject("swap", "no_swap_tx", "Jupiter returned no swapTransaction")
        except Exception as exc:
            return _reject("swap", "swap_error", str(exc))

        # --- 3. Sign ---
        try:
            import base64 as _b64
            raw = _b64.b64decode(swap_tx_b64)
            unsigned = VersionedTransaction.from_bytes(raw)
            signed = VersionedTransaction(unsigned.message, [kp])
        except Exception as exc:
            return _reject("sign", "sign_error", str(exc))

        # --- 4. Submit + confirm ---
        try:
            client = RpcClient(rpc_url)
            raw_send = client.send_raw_transaction(bytes(signed))
            txid = str(raw_send.value)
            # Confirm (poll up to ~30s)
            confirmed = False
            for _ in range(30):
                st = client.get_signature_statuses([raw_send.value])
                info = st.value[0] if st and st.value else None
                if info and (info.confirmation_status is not None) and info.err is None:
                    confirmed = True
                    break
                if info and info.err:
                    return _reject("confirm", "tx_failed", f"On-chain error: {info.err}")
                _time.sleep(1)
            if not confirmed:
                return _reject("confirm", "not_confirmed", f"Tx {txid} not confirmed in time")
        except Exception as exc:
            return _reject("submit", "submit_error", str(exc))

        # --- 5. Result ---
        out_amount = int(quote.get("outAmount") or 0)
        in_amount = int(quote.get("inAmount") or amount_lamports)
        if is_buy:
            token_amount = out_amount  # base units of the token received
            effective_price = (requested_usd / token_amount) if token_amount else None
        else:
            token_amount = in_amount
            effective_price = None
        fee_lamports = int((in_amount * platform_fee_bps) / 10000) if platform_fee_bps else 0

        return ExecutionResult(
            status="filled",
            stage="confirm",
            reason="live_fill",
            message=f"Live {'buy' if is_buy else 'sell'} confirmed on {rpc_url.split('//')[-1]}",
            requested_usd=requested_usd,
            executed_usd=requested_usd,
            effective_price_usd=effective_price,
            token_amount=token_amount,
            price_impact_bps=price_impact_bps,
            slippage_bps=slippage_bps,
            priority_fee_lamports=prioritization,
            route=f"{base_url}/v6",
            txid=txid,
            payload={
                "input_mint": input_mint,
                "output_mint": output_mint,
                "in_amount": in_amount,
                "out_amount": out_amount,
                "platform_fee_bps": platform_fee_bps,
                "platform_fee_lamports": fee_lamports,
                "mev_protection": mev_protection,
            },
        )
