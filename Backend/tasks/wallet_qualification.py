"""
Wallet Qualification Pipeline (Section 6.2)

Triggered by token_discovery for each new token. Runs two passes:
  - First-pass (looser): $100 spend, 3x ROI, outcome='open', qualifies=0
  - Second-pass (full):  $75 spend, 5x ROI, proper outcome, qualifies=0|1

SolanaTracker endpoints:
  GET /top-traders/{token}    -> list of top traders
  GET /first-buyers/{token}   -> list of first buyers
  GET /pnl/{wallet}/{token}   -> PnL data for wallet on token
  GET /tokens/{token}         -> token info including ATH
"""

import logging
import os
import time
import uuid
from datetime import datetime, timezone

import requests

from celery_app import celery
from services.clickhouse_client import insert_token_scans, insert_wallet_token_stats
from services.http_session import get_http_session
from services.redis_pool import get_redis_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SolanaTracker config
# ---------------------------------------------------------------------------
ST_BASE_URL = "https://data.solanatracker.io"
ST_API_KEY = os.environ.get("SOLANATRACKER_API_KEY", "")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# ---------------------------------------------------------------------------
# Qualification thresholds
# ---------------------------------------------------------------------------
TOKEN_MIN_PUMP_MULT = 10       # token must >= 10x from launch within 30 days

FIRST_PASS_MIN_SPEND = 100     # USD
FIRST_PASS_MIN_ROI = 3.0       # realized multiplier

SECOND_PASS_MIN_SPEND = 75     # USD
SECOND_PASS_MIN_ROI = 5.0      # realized multiplier

WIN_WALLET_MULT = 5.0          # wallet >5x
WIN_TOKEN_MULT = 30.0          # token >30x launch-to-ATH

# ---------------------------------------------------------------------------
# Redis keys
# ---------------------------------------------------------------------------
PENDING_TOKENS_KEY = "kys:pending_tokens"
QUALIFIED_TOKENS_KEY = "kys:qualified_tokens"


# ===================================================================
# Helpers
# ===================================================================

def _get_redis():
    return get_redis_client()


def _st_headers() -> dict:
    return {"x-api-key": ST_API_KEY, "Accept": "application/json"}


def _st_get(path: str, retries: int = 3, backoff: float = 1.0):
    """GET from SolanaTracker with retries and back-off."""
    url = f"{ST_BASE_URL}{path}"
    for attempt in range(retries):
        try:
            resp = get_http_session().get(url, headers=_st_headers(), timeout=30)
            if resp.status_code == 429:
                wait = backoff * (2 ** attempt)
                logger.warning("SolanaTracker rate-limited, sleeping %.1fs", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
                continue
            logger.error("SolanaTracker request failed: %s %s", path, exc)
            return None
    return None


def _fetch_wallets_for_token(token_address: str) -> list[dict]:
    """Fetch top_traders + first_buyers and return merged wallet list.

    Each entry: {wallet, source, pnl_data}
    """
    wallets: dict[str, dict] = {}

    # -- top traders --
    top_traders = _st_get(f"/top-traders/{token_address}")
    if top_traders and isinstance(top_traders, list):
        for trader in top_traders:
            wallet = trader.get("wallet")
            if wallet:
                wallets[wallet] = {
                    "wallet": wallet,
                    "source": "top_traders",
                    "pnl_data": trader,
                }
        logger.info("Fetched %d top traders for %s", len(top_traders), token_address[:12])

    # -- first buyers --
    first_buyers_resp = _st_get(f"/first-buyers/{token_address}")
    if first_buyers_resp:
        buyers = (
            first_buyers_resp
            if isinstance(first_buyers_resp, list)
            else first_buyers_resp.get("buyers", [])
        )
        for buyer in buyers:
            wallet = buyer.get("wallet")
            if wallet:
                if wallet in wallets:
                    # Merge: first-buyer data takes precedence for entry timing
                    wallets[wallet]["pnl_data"].update(buyer)
                    wallets[wallet]["source"] = "first_buyers"
                else:
                    wallets[wallet] = {
                        "wallet": wallet,
                        "source": "first_buyers",
                        "pnl_data": buyer,
                    }
        logger.info("Fetched %d first buyers for %s", len(buyers), token_address[:12])

    # -- enrich with per-wallet PnL where missing --
    for addr, wdata in wallets.items():
        pnl = wdata["pnl_data"]
        # If the top-traders / first-buyers response already embeds realized/totalInvested
        # we can skip the extra call.
        if pnl.get("realized") is not None and (
            pnl.get("total_invested") is not None or pnl.get("totalInvested") is not None
        ):
            continue
        detailed_pnl = _st_get(f"/pnl/{addr}/{token_address}")
        if detailed_pnl:
            wdata["pnl_data"] = detailed_pnl
        time.sleep(0.3)  # respect rate limits

    return list(wallets.values())


def _get_token_ath_mult(token_address: str) -> float:
    """Return launch-to-ATH multiplier for a token, or 0.0 on failure."""
    data = _st_get(f"/tokens/{token_address}")
    if not data:
        return 0.0

    # SolanaTracker token response may nest under "pools" or directly
    try:
        events = data.get("events", {})
        pools = data.get("pools", [{}])
        pool = pools[0] if pools else {}

        ath_price = (
            data.get("highest_price")
            or pool.get("price", {}).get("ath")
            or 0
        )
        launch_price = (
            data.get("launch_price")
            or pool.get("price", {}).get("launch")
            or pool.get("launchPrice")
            or 0
        )

        if launch_price and launch_price > 0 and ath_price and ath_price > 0:
            return ath_price / launch_price
    except Exception as exc:
        logger.warning("Could not parse ATH mult for %s: %s", token_address[:12], exc)

    return 0.0


# ===================================================================
# Row builder
# ===================================================================

def build_wallet_token_stats_row(
    wallet_data: dict,
    token_address: str,
    pass_type: str,
    token_ath_mult: float = 0.0,
) -> dict | None:
    """Build a wallet_token_stats row dict from SolanaTracker wallet data.

    Args:
        wallet_data: merged dict with keys {wallet, source, pnl_data}
        token_address: the token mint address
        pass_type: 'first' or 'second'
        token_ath_mult: launch-to-ATH multiplier for the token

    Returns:
        Row dict ready for ClickHouse insert, or None if below floors.
    """
    pnl = wallet_data.get("pnl_data", {})
    wallet_address = wallet_data["wallet"]

    realized = float(pnl.get("realized", 0))
    unrealized = float(pnl.get("unrealized", 0))
    total_invested = float(
        pnl.get("total_invested") or pnl.get("totalInvested") or 0
    )

    # Determine thresholds based on pass type
    if pass_type == "first":
        min_spend = FIRST_PASS_MIN_SPEND
        min_roi = FIRST_PASS_MIN_ROI
    else:
        min_spend = SECOND_PASS_MIN_SPEND
        min_roi = SECOND_PASS_MIN_ROI

    # Spend floor check
    if total_invested < min_spend:
        return _disqualified_row(
            wallet_address,
            token_address,
            pass_type,
            pnl,
            total_invested,
            realized,
            unrealized,
            reason=f"spend_below_{min_spend}",
        )

    # ROI calculation
    if total_invested <= 0:
        return None

    realized_mult = (realized + total_invested) / total_invested
    total_mult = (realized + unrealized + total_invested) / total_invested

    # ROI floor check
    if realized_mult < min_roi:
        return _disqualified_row(
            wallet_address,
            token_address,
            pass_type,
            pnl,
            total_invested,
            realized,
            unrealized,
            reason=f"roi_below_{min_roi}x",
        )

    # --- Outcome ---
    if pass_type == "first":
        outcome = "open"
        qualifies = 0
    else:
        # Second pass: compute win/draw/loss
        outcome, qualifies = _compute_outcome(realized_mult, token_ath_mult, total_invested)

    # Entry price / timing
    entry_price = float(pnl.get("entry_price", 0) or 0)
    first_buy_time = int(pnl.get("first_buy_time", 0) or 0)

    # Entry-to-ATH multiplier (if entry_price known)
    entry_to_ath_mult = 0.0
    if entry_price and entry_price > 0:
        ath_price = float(pnl.get("highest_price", 0) or 0)
        if ath_price > 0:
            entry_to_ath_mult = ath_price / entry_price

    now = datetime.now(timezone.utc)

    return {
        "wallet_address": wallet_address,
        "token_address": token_address,
        "scan_id": str(uuid.uuid4()),
        "first_entry_price": entry_price,
        "first_entry_usd": round(total_invested, 2),
        "first_entry_timestamp": datetime.fromtimestamp(first_buy_time / 1e6 if first_buy_time > 1e15 else first_buy_time / 1000 if first_buy_time > 1e12 else first_buy_time, tz=timezone.utc) if first_buy_time and first_buy_time > 0 else now,
        "entry_price_to_launch_mult": 0.0,  # computed downstream if launch price known
        "avg_entry_price": entry_price,
        "avg_entry_to_ath_mult": round(entry_to_ath_mult, 4),
        "all_buys": "[]",
        "all_sells": "[]",
        "buy_count": 1,
        "sell_count": 0,
        "total_spent_usd": round(total_invested, 2),
        "realized_pnl_usd": round(realized, 2),
        "unrealized_pnl_usd": round(unrealized, 2),
        "total_pnl_usd": round(realized + unrealized, 2),
        "realized_roi_mult": round(realized_mult, 4),
        "total_roi_mult": round(total_mult, 4),
        "qualifies": qualifies,
        "outcome": outcome,
        "disqualify_reason": "",
        "wallet_source": wallet_data.get("source", "unknown"),
        "updated_at": now,
    }


def _compute_outcome(
    realized_mult: float,
    token_ath_mult: float,
    total_invested: float,
) -> tuple[str, int]:
    """Determine outcome and qualifies flag for second-pass.

    Win:  wallet >5x AND token >30x launch-to-ATH
    Draw: wallet exactly 5x OR token exactly 30x
    Loss: wallet <5x OR token <30x OR spend <$75
    """
    wallet_wins = realized_mult > WIN_WALLET_MULT
    token_wins = token_ath_mult > WIN_TOKEN_MULT

    wallet_exact = abs(realized_mult - WIN_WALLET_MULT) < 0.01
    token_exact = abs(token_ath_mult - WIN_TOKEN_MULT) < 0.5

    if total_invested < SECOND_PASS_MIN_SPEND:
        return "loss", 0

    if wallet_exact or token_exact:
        return "draw", 0

    if wallet_wins and token_wins:
        return "win", 1

    return "loss", 0


def _disqualified_row(
    wallet_address: str,
    token_address: str,
    pass_type: str,
    pnl: dict,
    total_invested: float,
    realized: float,
    unrealized: float,
    reason: str,
) -> dict:
    """Return a row that records the wallet but marks it disqualified."""
    now = datetime.now(timezone.utc)
    total_mult = 0.0
    realized_mult = 0.0
    if total_invested > 0:
        realized_mult = (realized + total_invested) / total_invested
        total_mult = (realized + unrealized + total_invested) / total_invested

    entry_price = float(pnl.get("entry_price", 0) or 0)
    first_buy_time = int(pnl.get("first_buy_time", 0) or 0)

    return {
        "wallet_address": wallet_address,
        "token_address": token_address,
        "scan_id": str(uuid.uuid4()),
        "first_entry_price": entry_price,
        "first_entry_usd": round(total_invested, 2),
        "first_entry_timestamp": datetime.fromtimestamp(first_buy_time / 1e6 if first_buy_time > 1e15 else first_buy_time / 1000 if first_buy_time > 1e12 else first_buy_time, tz=timezone.utc) if first_buy_time and first_buy_time > 0 else now,
        "entry_price_to_launch_mult": 0.0,
        "avg_entry_price": entry_price,
        "avg_entry_to_ath_mult": 0.0,
        "all_buys": "[]",
        "all_sells": "[]",
        "buy_count": 1,
        "sell_count": 0,
        "total_spent_usd": round(total_invested, 2),
        "realized_pnl_usd": round(realized, 2),
        "unrealized_pnl_usd": round(unrealized, 2),
        "total_pnl_usd": round(realized + unrealized, 2),
        "realized_roi_mult": round(realized_mult, 4),
        "total_roi_mult": round(total_mult, 4),
        "qualifies": 0,
        "outcome": "open" if pass_type == "first" else "loss",
        "disqualify_reason": reason,
        "wallet_source": "disqualified",
        "updated_at": now,
    }


# ===================================================================
# Celery tasks
# ===================================================================

@celery.task(
    name="tasks.wallet_qualification_scan",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def wallet_qualification_scan(self, token_address: str, pass_type: str = "first"):
    """Scan a token's wallets and qualify them.

    First-pass  (looser: $100 spend, 3x ROI): saves raw stats, outcome='open', qualifies=0.
    Second-pass (full:   $75 spend, 5x ROI):  saves full stats with proper outcome.

    Triggered by token_discovery for each new token.
    """
    logger.info(
        "wallet_qualification_scan START token=%s pass=%s",
        token_address[:12],
        pass_type,
    )

    try:
        # 1. Fetch wallets (top traders + first buyers)
        wallet_list = _fetch_wallets_for_token(token_address)
        if not wallet_list:
            logger.warning("No wallets found for token %s", token_address[:12])
            return {"token": token_address, "pass": pass_type, "wallets_found": 0, "rows_inserted": 0}

        # 2. Get token ATH multiplier (needed for outcome on second pass)
        token_ath_mult = 0.0
        if pass_type == "second":
            token_ath_mult = _get_token_ath_mult(token_address)

        # 3. Build rows
        rows = []
        for wdata in wallet_list:
            row = build_wallet_token_stats_row(wdata, token_address, pass_type, token_ath_mult)
            if row is not None:
                rows.append(row)

        # 4. Bulk insert into ClickHouse (materialized view auto-fires)
        if rows:
            insert_wallet_token_stats(rows)
            logger.info(
                "Inserted %d wallet_token_stats rows for token=%s pass=%s",
                len(rows),
                token_address[:12],
                pass_type,
            )

        # 5. Record the token scan
        now = datetime.now(timezone.utc)
        scan_row = {
            "token_address": token_address,
            "scan_id": str(uuid.uuid4()),
            "discovered_via": pass_type,
            "scan_timestamp": now,
            "launch_price": 0.0,
            "current_price": 0.0,
            "ath_price": 0.0,
            "launch_to_ath_mult": 0.0,
            "launch_to_current_mult": 0.0,
            "qualified_10x": 1 if pass_type == "second" else 0,
            "qualified_30x": 0,
            "market_cap_usd": 0.0,
            "volume_24h_usd": 0.0,
            "liquidity_usd": 0.0,
            "holder_count": 0,
            "scan_window_days": 30,
            "token_symbol": "",
            "token_name": "",
            "updated_at": now,
        }
        insert_token_scans([scan_row])

        # 6. On first-pass: add token to Redis pending set
        if pass_type == "first":
            r = _get_redis()
            r.sadd(PENDING_TOKENS_KEY, token_address)
            logger.info("Added %s to %s", token_address[:12], PENDING_TOKENS_KEY)

        return {
            "token": token_address,
            "pass": pass_type,
            "wallets_found": len(wallet_list),
            "rows_inserted": len(rows),
            "qualified": sum(1 for r in rows if r.get("qualifies") == 1),
        }

    except Exception as exc:
        logger.exception(
            "wallet_qualification_scan FAILED token=%s pass=%s",
            token_address[:12],
            pass_type,
        )
        raise self.retry(exc=exc)


@celery.task(
    name="tasks.second_pass_patch",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    acks_late=True,
)
def second_pass_patch(self, token_address: str, token_data: dict | None = None):
    """Second-pass qualification when a pending token appears on trending_runners.

    Steps:
      1. Verify token has pumped >= 10x within 30 days.
      2. Re-fetch wallets with full qualification floors ($75 spend, 5x ROI).
      3. INSERT new rows (ReplacingMergeTree deduplicates by wallet+token).
      4. Update token_scans: set qualified_10x=1.
      5. Move from kys:pending_tokens -> kys:qualified_tokens in Redis.
    """
    logger.info("second_pass_patch START token=%s", token_address[:12])

    try:
        # 1. Verify 10x pump
        token_ath_mult = _get_token_ath_mult(token_address)
        if token_ath_mult < TOKEN_MIN_PUMP_MULT:
            logger.info(
                "Token %s ATH mult %.1fx < %dx threshold, skipping second pass",
                token_address[:12],
                token_ath_mult,
                TOKEN_MIN_PUMP_MULT,
            )
            return {
                "token": token_address,
                "status": "skipped",
                "reason": f"ath_mult_{token_ath_mult:.1f}x_below_{TOKEN_MIN_PUMP_MULT}x",
            }

        # 2. Re-fetch wallets with full qualification
        wallet_list = _fetch_wallets_for_token(token_address)
        if not wallet_list:
            logger.warning("No wallets found for token %s on second pass", token_address[:12])
            return {"token": token_address, "status": "no_wallets"}

        # 3. Build rows with second-pass thresholds
        rows = []
        for wdata in wallet_list:
            row = build_wallet_token_stats_row(wdata, token_address, "second", token_ath_mult)
            if row is not None:
                rows.append(row)

        # 4. Bulk insert (ReplacingMergeTree deduplicates)
        if rows:
            insert_wallet_token_stats(rows)
            logger.info(
                "Inserted %d second-pass rows for token=%s",
                len(rows),
                token_address[:12],
            )

        # 5. Update token_scans
        qualified_count = sum(1 for r in rows if r.get("qualifies") == 1)
        now = datetime.now(timezone.utc)
        scan_row = {
            "token_address": token_address,
            "scan_id": str(uuid.uuid4()),
            "discovered_via": "second",
            "scan_timestamp": now,
            "launch_price": 0.0,
            "current_price": 0.0,
            "ath_price": 0.0,
            "launch_to_ath_mult": round(token_ath_mult, 4),
            "launch_to_current_mult": 0.0,
            "qualified_10x": 1,
            "qualified_30x": 1 if token_ath_mult > WIN_TOKEN_MULT else 0,
            "market_cap_usd": 0.0,
            "volume_24h_usd": 0.0,
            "liquidity_usd": 0.0,
            "holder_count": 0,
            "scan_window_days": 30,
            "token_symbol": "",
            "token_name": "",
            "updated_at": now,
        }
        insert_token_scans([scan_row])

        # 6. Move token between Redis sets
        r = _get_redis()
        r.srem(PENDING_TOKENS_KEY, token_address)
        r.sadd(QUALIFIED_TOKENS_KEY, token_address)
        logger.info(
            "Moved %s from %s -> %s (%d qualified wallets)",
            token_address[:12],
            PENDING_TOKENS_KEY,
            QUALIFIED_TOKENS_KEY,
            qualified_count,
        )

        return {
            "token": token_address,
            "status": "completed",
            "ath_mult": round(token_ath_mult, 2),
            "wallets_found": len(wallet_list),
            "rows_inserted": len(rows),
            "qualified": qualified_count,
        }

    except Exception as exc:
        logger.exception("second_pass_patch FAILED token=%s", token_address[:12])
        raise self.retry(exc=exc)
