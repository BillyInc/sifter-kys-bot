"""
Wallet Qualification Pipeline (Section 6.2)

Triggered by token_discovery for each new token. Runs two passes:
  - First-pass (looser): $100 spend, 3x ROI, outcome='open', qualifies=0
  - Second-pass (full):  $75 spend, 5x ROI, proper outcome, qualifies=0|1

SolanaTracker V2 endpoints (migrated from deprecated V1):
  GET /v2/pnl/tokens/{token}/traders      -> top traders per token
  GET /v2/pnl/tokens/{token}/first-buyers -> first buyers per token
  GET /v2/pnl/wallets/{wallet}/tokens/{token} -> wallet position on token
  GET /tokens/{token}/ath                 -> token ATH price
"""

import logging
import time
import uuid
from datetime import datetime, timezone

from celery_app import celery
from services.clickhouse_client import insert_token_scans, insert_wallet_token_stats
from services.redis_pool import get_redis_client
from services.solana_tracker_client import get_st_client

logger = logging.getLogger(__name__)

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


def _fetch_wallets_for_token(token_address: str) -> list[dict]:
    """Fetch token traders + first buyers via V2 endpoints.

    Each entry: {wallet, source, pnl_data}
    """
    st = get_st_client()
    wallets: dict[str, dict] = {}

    # -- V2: token traders (replaces /top-traders/{token}) --
    traders = st.get_token_traders(token_address, limit=50)
    for trader in traders:
        wallet = trader.get("wallet")
        if wallet:
            wallets[wallet] = {
                "wallet": wallet,
                "source": "top_traders",
                "pnl_data": trader,
            }
    if traders:
        logger.info("Fetched %d traders for %s", len(traders), token_address[:12])

    # -- V2: first buyers (replaces /first-buyers/{token}) --
    first_buyers = st.get_first_buyers(token_address, limit=100)
    for buyer in first_buyers:
        wallet = buyer.get("wallet")
        if wallet:
            if wallet in wallets:
                wallets[wallet]["pnl_data"].update(buyer)
                wallets[wallet]["source"] = "first_buyers"
            else:
                wallets[wallet] = {
                    "wallet": wallet,
                    "source": "first_buyers",
                    "pnl_data": buyer,
                }
    if first_buyers:
        logger.info("Fetched %d first buyers for %s", len(first_buyers), token_address[:12])

    # -- V2: enrich with per-wallet position data where missing --
    for addr, wdata in wallets.items():
        pnl = wdata["pnl_data"]
        # V2 traders/first-buyers embed pnl.token.realized + invested
        pnl_nested = pnl.get("pnl", {})
        has_realized = (pnl_nested.get("token", {}).get("realized") is not None
                        if isinstance(pnl_nested, dict) else False)
        has_invested = pnl.get("invested") is not None or pnl.get("buyUsd") is not None
        if has_realized and has_invested:
            continue
        # Fetch detailed position (replaces /pnl/{wallet}/{token})
        detail = st.get_wallet_token_position(addr, token_address)
        if detail:
            wdata["pnl_data"] = detail
        time.sleep(0.3)

    return list(wallets.values())


def _get_first_buyers_wallets(token_address: str) -> list[str]:
    """Return ordered list of first-buyer wallet addresses for a token."""
    st = get_st_client()
    buyers = st.get_first_buyers(token_address, limit=100)
    return [b["wallet"] for b in buyers if b.get("wallet")]


def _get_token_ath_mult(token_address: str) -> float:
    """Return ATH price for a token, or 0.0 on failure.

    Note: No launch_price available from any ST endpoint, so this
    returns the raw ATH price (not a multiplier). Used by
    build_wallet_token_stats_row to compute entry-to-ATH ratio.
    """
    st = get_st_client()
    ath_data = st.get_token_ath(token_address)
    if not ath_data:
        return 0.0
    return float(ath_data.get("highest_price", 0) or 0)


# ===================================================================
# Row builder
# ===================================================================

def _extract_v2_fields(pnl_data: dict) -> dict:
    """Extract normalized fields from V2 response data.

    Handles both V2 positions shape (flat pnl.realized) and
    V2 traders shape (nested pnl.token.realized).
    """
    pnl_nested = pnl_data.get("pnl", {})
    if isinstance(pnl_nested, dict):
        # V2 traders/first-buyers: pnl.token.realized
        token_pnl = pnl_nested.get("token", pnl_nested)
        realized = float(token_pnl.get("realized", 0) or 0)
        unrealized = float(token_pnl.get("unrealized", 0) or 0)
    else:
        realized = float(pnl_data.get("realized", 0) or 0)
        unrealized = float(pnl_data.get("unrealized", 0) or 0)

    # invested: top-level on positions, or buyUsd on traders, or fallback V1
    total_invested = float(
        pnl_data.get("invested")
        or pnl_data.get("buyUsd")
        or pnl_data.get("total_invested")
        or pnl_data.get("totalInvested")
        or 0
    )

    # V2 averages
    averages = pnl_data.get("averages", {})
    avg_buy = float(averages.get("buy", 0) if isinstance(averages, dict)
                    else pnl_data.get("entry_price", 0) or 0)

    # V2 timing (ms epoch or None)
    timing = pnl_data.get("timing", {})
    first_buy_ms = timing.get("firstBuy") if isinstance(timing, dict) else pnl_data.get("first_buy_time")

    # V2 counts
    counts = pnl_data.get("counts", {})
    buy_count = int(counts.get("buys", 1) if isinstance(counts, dict) else 1)
    sell_count = int(counts.get("sells", 0) if isinstance(counts, dict) else 0)

    # V2 ROI (direct %, not used for threshold — we compute our own mult)
    roi_pct = float(pnl_data.get("roi", 0) or 0)

    return {
        "realized": realized,
        "unrealized": unrealized,
        "total_invested": total_invested,
        "avg_buy": avg_buy,
        "first_buy_ms": first_buy_ms,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "roi_pct": roi_pct,
    }


def _parse_timestamp(ts) -> datetime:
    """Parse a V2 timestamp (ms epoch int, ISO string, or None) to datetime."""
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, (int, float)) and ts > 0:
        # ms epoch
        if ts > 1e15:
            ts = ts / 1e6
        elif ts > 1e12:
            ts = ts / 1e3
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def build_wallet_token_stats_row(
    wallet_data: dict,
    token_address: str,
    pass_type: str,
    token_ath_mult: float = 0.0,
    first_buyers_wallets: list[str] | None = None,
) -> dict | None:
    """Build a wallet_token_stats row dict from V2 SolanaTracker data.

    Args:
        wallet_data: merged dict with keys {wallet, source, pnl_data}
        token_address: the token mint address
        pass_type: 'first' or 'second'
        token_ath_mult: ATH price for the token (used for entry-to-ATH calc)
        first_buyers_wallets: ordered list of wallet addresses from first-buyers

    Returns:
        Row dict ready for ClickHouse insert, or None if below floors.
    """
    pnl_data = wallet_data.get("pnl_data", {})
    wallet_address = wallet_data["wallet"]
    fields = _extract_v2_fields(pnl_data)

    realized = fields["realized"]
    unrealized = fields["unrealized"]
    total_invested = fields["total_invested"]

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
            wallet_address, token_address, pass_type, pnl_data,
            total_invested, realized, unrealized,
            reason=f"spend_below_{min_spend}",
        )

    if total_invested <= 0:
        return None

    realized_mult = (realized + total_invested) / total_invested
    total_mult = (realized + unrealized + total_invested) / total_invested

    # ROI floor check
    if realized_mult < min_roi:
        return _disqualified_row(
            wallet_address, token_address, pass_type, pnl_data,
            total_invested, realized, unrealized,
            reason=f"roi_below_{min_roi}x",
        )

    # --- Outcome ---
    if pass_type == "first":
        outcome = "open"
        qualifies = 0
    else:
        outcome, qualifies = _compute_outcome(realized_mult, token_ath_mult, total_invested)

    # --- Early entry (entry_price_to_launch_mult) ---
    entry_price_to_launch_mult = 0.0
    if first_buyers_wallets:
        if wallet_address in first_buyers_wallets:
            position = first_buyers_wallets.index(wallet_address)
            percentile = position / max(len(first_buyers_wallets), 1)
            entry_price_to_launch_mult = round(1.0 / max(0.01, percentile), 4)

    # --- Entry-to-ATH multiplier ---
    avg_buy = fields["avg_buy"]
    entry_to_ath_mult = 0.0
    if avg_buy > 0 and token_ath_mult > 0:
        entry_to_ath_mult = token_ath_mult / avg_buy

    now = datetime.now(timezone.utc)

    return {
        "wallet_address": wallet_address,
        "token_address": token_address,
        "scan_id": str(uuid.uuid4()),
        "first_entry_price": avg_buy,
        "first_entry_usd": round(total_invested, 2),
        "first_entry_timestamp": _parse_timestamp(fields["first_buy_ms"]),
        "entry_price_to_launch_mult": entry_price_to_launch_mult,
        "avg_entry_price": avg_buy,
        "avg_entry_to_ath_mult": round(entry_to_ath_mult, 4),
        "all_buys": "[]",
        "all_sells": "[]",
        "buy_count": fields["buy_count"],
        "sell_count": fields["sell_count"],
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

    Win:  wallet >5x realized ROI AND spend >= $75
    Draw: wallet within 0.5x of the 5x threshold
    Loss: everything else

    Note: token_ath_mult is accepted for interface compatibility but no longer
    used as a hard gate — SolanaTracker rarely provides launch prices, so
    requiring token >30x ATH caused 100% of rows to be marked as losses.
    """
    if total_invested < SECOND_PASS_MIN_SPEND:
        return "loss", 0

    wallet_wins = realized_mult > WIN_WALLET_MULT  # >5x

    if wallet_wins:
        return "win", 1

    wallet_near = abs(realized_mult - WIN_WALLET_MULT) < 0.5
    if wallet_near:
        return "draw", 0

    return "loss", 0


def _disqualified_row(
    wallet_address: str,
    token_address: str,
    pass_type: str,
    pnl_data: dict,
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

    fields = _extract_v2_fields(pnl_data)

    return {
        "wallet_address": wallet_address,
        "token_address": token_address,
        "scan_id": str(uuid.uuid4()),
        "first_entry_price": fields["avg_buy"],
        "first_entry_usd": round(total_invested, 2),
        "first_entry_timestamp": _parse_timestamp(fields["first_buy_ms"]),
        "entry_price_to_launch_mult": 0.0,
        "avg_entry_price": fields["avg_buy"],
        "avg_entry_to_ath_mult": 0.0,
        "all_buys": "[]",
        "all_sells": "[]",
        "buy_count": fields["buy_count"],
        "sell_count": fields["sell_count"],
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

        # 2. Get token ATH price and first-buyers list
        token_ath_price = _get_token_ath_mult(token_address)
        first_buyers_wallets = _get_first_buyers_wallets(token_address)

        # 3. Build rows
        rows = []
        for wdata in wallet_list:
            row = build_wallet_token_stats_row(
                wdata, token_address, pass_type, token_ath_price,
                first_buyers_wallets=first_buyers_wallets,
            )
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
        # 1. Get ATH price for entry-to-ATH computation.
        # V2 has no launch price, so the 10x ATH gate is not enforced —
        # qualification is wallet-ROI based via _compute_outcome.
        token_ath_price = _get_token_ath_mult(token_address)
        token_ath_mult = token_ath_price  # raw ATH price, used in build_row
        if False:  # ATH gate disabled — no launch price from V2
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
        first_buyers_wallets = _get_first_buyers_wallets(token_address)
        rows = []
        for wdata in wallet_list:
            row = build_wallet_token_stats_row(
                wdata, token_address, "second", token_ath_price,
                first_buyers_wallets=first_buyers_wallets,
            )
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


# ===================================================================
# One-time requalification task
# ===================================================================

@celery.task(name='tasks.requalify_existing_data', bind=True, max_retries=0,
             time_limit=7200, soft_time_limit=6600)
def requalify_existing_data(self, batch_size=5000):
    """Re-insert all wallet_token_stats with corrected qualifies/outcome.

    Triggered on-demand:
        celery -A celery_app call tasks.requalify_existing_data
    """
    from services.clickhouse_client import get_clickhouse_client, CH_DATABASE

    ch = get_clickhouse_client()
    if ch is None:
        return {"status": "error", "error": "ClickHouse unavailable"}

    count_result = ch.query("SELECT count() FROM wallet_token_stats FINAL")
    total_rows = count_result.first_row[0]
    logger.info("[REQUALIFY] Total rows: %d", total_rows)

    columns = [
        'wallet_address', 'token_address', 'scan_id',
        'first_entry_price', 'first_entry_usd', 'first_entry_timestamp',
        'entry_price_to_launch_mult', 'avg_entry_price', 'avg_entry_to_ath_mult',
        'all_buys', 'all_sells', 'buy_count', 'sell_count',
        'total_spent_usd', 'realized_pnl_usd', 'unrealized_pnl_usd',
        'total_pnl_usd', 'realized_roi_mult', 'total_roi_mult',
        'qualifies', 'outcome', 'disqualify_reason', 'wallet_source',
    ]

    stats = {'wins': 0, 'draws': 0, 'losses': 0, 'total': 0, 'changed': 0}
    offset = 0

    while offset < total_rows:
        result = ch.query(
            f"SELECT {', '.join(columns)} FROM wallet_token_stats FINAL "
            f"ORDER BY wallet_address, token_address LIMIT {batch_size} OFFSET {offset}"
        )
        rows = list(result.named_results())
        if not rows:
            break

        insert_data = []
        insert_columns = columns + ['updated_at']

        for row in rows:
            new_outcome, new_qualifies = _compute_outcome(
                row['realized_roi_mult'], 0.0, row['total_spent_usd']
            )

            disqualify_reason = row['disqualify_reason']
            if new_qualifies == 1:
                disqualify_reason = ''

            stats['total'] += 1
            if new_outcome == 'win':
                stats['wins'] += 1
            elif new_outcome == 'draw':
                stats['draws'] += 1
            else:
                stats['losses'] += 1
            if new_outcome != row['outcome'] or new_qualifies != row['qualifies']:
                stats['changed'] += 1

            insert_data.append([
                row['wallet_address'], row['token_address'], row['scan_id'],
                row['first_entry_price'], row['first_entry_usd'], row['first_entry_timestamp'],
                row['entry_price_to_launch_mult'], row['avg_entry_price'], row['avg_entry_to_ath_mult'],
                row['all_buys'], row['all_sells'], row['buy_count'], row['sell_count'],
                row['total_spent_usd'], row['realized_pnl_usd'], row['unrealized_pnl_usd'],
                row['total_pnl_usd'], row['realized_roi_mult'], row['total_roi_mult'],
                new_qualifies, new_outcome, disqualify_reason, row['wallet_source'],
                datetime.now(timezone.utc),
            ])

        ch.insert(table='wallet_token_stats', data=insert_data,
                  database=CH_DATABASE, column_names=insert_columns)
        offset += len(rows)
        logger.info(
            "[REQUALIFY] %d/%d — %d wins, %d draws, %d losses, %d changed",
            stats['total'], total_rows,
            stats['wins'], stats['draws'], stats['losses'], stats['changed'],
        )

    logger.info("[REQUALIFY] Complete: %s", stats)
    return {"status": "success", **stats}
