"""
Leaderboard Discovery Pipeline

Discovers top wallets directly from SolanaTracker's V2 leaderboard endpoint,
then fetches their closed positions to populate ClickHouse wallet_token_stats rows.
Complements (does not replace) token_discovery.py.

Flow:
  1. Fetch leaderboard candidates across 3 sort criteria (roi, winRate, pnl)
  2. Filter out recently processed wallets (Redis + ClickHouse checks)
  3. Fetch closed positions per wallet, discard wallets with < 3 qualifying positions
  4. Fetch first-buyers + ATH for each unique token
  5. Build ClickHouse wallet_token_stats rows inline
  6. Bulk insert to ClickHouse (MV auto-fires)
  7. Enrich top 15 for display cache in Redis
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from celery_app import celery
from services.clickhouse_client import get_clickhouse_client, insert_wallet_token_stats
from services.redis_pool import get_redis_client
from services.solana_tracker_client import get_st_client

logger = logging.getLogger(__name__)

# Redis key for tracking recently seen leaderboard wallets
LEADERBOARD_SEEN_KEY = "kys:leaderboard_seen_wallets"
LEADERBOARD_SEEN_TTL = 86400 * 7  # 7 days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_timestamp(ts) -> datetime:
    """Parse a timestamp value into a datetime.

    Handles:
      - None -> now()
      - Millisecond epoch int -> datetime
      - ISO 8601 string -> datetime
    """
    if ts is None:
        return datetime.now(timezone.utc)

    if isinstance(ts, (int, float)):
        # Millisecond epoch (> 1e12) vs second epoch
        if ts > 1e12:
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    if isinstance(ts, str):
        # Try ISO 8601 parsing
        try:
            # Handle trailing Z
            cleaned = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned)
        except (ValueError, TypeError):
            pass

    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery.task(
    name="tasks.leaderboard_discovery_scan",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    acks_late=True,
    time_limit=1800,  # 30 min max
)
def leaderboard_discovery_scan(self):
    """Discover top wallets from the SolanaTracker V2 leaderboard, fetch their
    closed positions, and populate ClickHouse wallet_token_stats rows."""

    try:
        st = get_st_client()
        r = get_redis_client()
        ch = get_clickhouse_client()

        if ch is None:
            logger.error("[LEADERBOARD] ClickHouse unavailable, aborting")
            return {"status": "error", "error": "ClickHouse unavailable"}

        # =================================================================
        # Step 1: Fetch leaderboard candidates
        # =================================================================
        logger.info("[LEADERBOARD] Fetching leaderboard candidates...")

        roi_candidates = st.get_leaderboard_top(
            sort="roi", min_roi=500, min_invested=100, min_trades=10, limit=200,
        )
        time.sleep(2)

        tokens_candidates = st.get_leaderboard_top(
            sort="tokens", min_roi=300, min_invested=75, min_trades=15, limit=200,
        )
        time.sleep(2)

        volume_candidates = st.get_leaderboard_top(
            sort="volume", min_roi=200, min_invested=200, min_trades=10, limit=200,
        )

        # Merge and deduplicate by wallet address
        all_candidates: dict[str, dict] = {}
        for candidate in roi_candidates + tokens_candidates + volume_candidates:
            wallet = candidate.get("wallet") or candidate.get("walletAddress") or ""
            if wallet and wallet not in all_candidates:
                all_candidates[wallet] = candidate

        logger.info(
            "[LEADERBOARD] Fetched %d unique candidates from 3 leaderboard queries",
            len(all_candidates),
        )

        # =================================================================
        # Step 2: Filter — skip recently processed wallets
        # =================================================================
        wallets_to_process: list[str] = []

        for wallet_addr in all_candidates:
            # Check Redis set
            if r.sismember(LEADERBOARD_SEEN_KEY, wallet_addr):
                continue

            # Check ClickHouse — skip if updated within 24 hours
            try:
                result = ch.query(
                    "SELECT max(updated_at) FROM wallet_token_stats FINAL "
                    "WHERE wallet_address = {addr:String}",
                    parameters={"addr": wallet_addr},
                )
                if result.result_rows and result.result_rows[0][0]:
                    last_updated = result.result_rows[0][0]
                    if isinstance(last_updated, datetime):
                        age_hours = (
                            datetime.now(timezone.utc) - last_updated.replace(tzinfo=timezone.utc)
                        ).total_seconds() / 3600
                        if age_hours < 24:
                            continue
            except Exception as exc:
                logger.debug("[LEADERBOARD] CH check failed for %s: %s", wallet_addr[:12], exc)

            wallets_to_process.append(wallet_addr)

        logger.info(
            "[LEADERBOARD] %d wallets after filtering (from %d candidates)",
            len(wallets_to_process),
            len(all_candidates),
        )

        # =================================================================
        # Step 3: Fetch closed positions per wallet
        # =================================================================
        # wallet_addr -> list of qualifying positions
        wallet_positions: dict[str, list[dict]] = {}
        unique_tokens: set[str] = set()
        processed_wallets: list[str] = []

        for i, wallet_addr in enumerate(wallets_to_process):
            time.sleep(0.5)

            try:
                positions = st.get_wallet_positions(
                    wallet_addr,
                    holding_state="closed",
                    sort="roi",
                    limit=100,
                    roi_min=300,
                    invested_min=100,
                )
            except Exception as exc:
                logger.warning("[LEADERBOARD] Failed to fetch positions for %s: %s", wallet_addr[:12], exc)
                continue

            # Filter qualifying positions: roi >= 300 (4x) AND invested >= 100
            qualifying = [
                pos for pos in positions
                if float(pos.get("roi", 0)) >= 300
                and float(pos.get("invested", 0)) >= 100
            ]

            # Discard wallets with < 3 qualifying positions
            if len(qualifying) < 3:
                continue

            wallet_positions[wallet_addr] = qualifying
            processed_wallets.append(wallet_addr)

            # Collect token mints
            for pos in qualifying:
                token = pos.get("token", {}).get("mint") or pos.get("tokenAddress") or ""
                if token:
                    unique_tokens.add(token)

            # Mark as seen in Redis
            r.sadd(LEADERBOARD_SEEN_KEY, wallet_addr)
            r.expire(LEADERBOARD_SEEN_KEY, LEADERBOARD_SEEN_TTL)

            if (i + 1) % 25 == 0:
                logger.info(
                    "[LEADERBOARD] Processed %d/%d wallets, %d qualified so far",
                    i + 1, len(wallets_to_process), len(processed_wallets),
                )

        logger.info(
            "[LEADERBOARD] %d wallets qualified with >= 3 positions, %d unique tokens",
            len(processed_wallets),
            len(unique_tokens),
        )

        # =================================================================
        # Step 4: Fetch first-buyers + ATH for each unique token
        # =================================================================
        first_buyers_by_token: dict[str, list[str]] = {}
        ath_by_token: dict[str, float] = {}

        for token in unique_tokens:
            time.sleep(0.5)

            # First buyers (cached 1hr in the client)
            try:
                buyers = st.get_first_buyers(token, limit=100)
                first_buyers_by_token[token] = [
                    b.get("wallet") or b.get("walletAddress") or ""
                    for b in buyers
                    if b.get("wallet") or b.get("walletAddress")
                ]
            except Exception as exc:
                logger.debug("[LEADERBOARD] first_buyers failed for %s: %s", token[:12], exc)
                first_buyers_by_token[token] = []

            time.sleep(0.5)

            # ATH price (cached 1hr in the client)
            try:
                ath_data = st.get_token_ath(token)
                if ath_data and isinstance(ath_data, dict):
                    ath_by_token[token] = float(
                        ath_data.get("highest_price")
                        or ath_data.get("highestPrice")
                        or ath_data.get("price", 0)
                    )
                else:
                    ath_by_token[token] = 0.0
            except Exception as exc:
                logger.debug("[LEADERBOARD] token ATH failed for %s: %s", token[:12], exc)
                ath_by_token[token] = 0.0

        logger.info(
            "[LEADERBOARD] Fetched first-buyers for %d tokens, ATH for %d tokens",
            len(first_buyers_by_token),
            len(ath_by_token),
        )

        # =================================================================
        # Step 5: Build ClickHouse rows
        # =================================================================
        rows: list[dict] = []

        for wallet_address, positions in wallet_positions.items():
            for pos in positions:
                token = pos.get("token", {}).get("mint") or pos.get("tokenAddress") or ""
                if not token:
                    continue

                # entry_price_to_launch_mult
                fb_wallets = first_buyers_by_token.get(token, [])
                if wallet_address in fb_wallets:
                    position_idx = fb_wallets.index(wallet_address)
                    percentile = position_idx / max(len(fb_wallets), 1)
                    entry_price_to_launch_mult = 1.0 / max(0.01, percentile)
                else:
                    entry_price_to_launch_mult = 0.0

                # avg_entry_to_ath_mult
                avg_buy = float(pos.get("averages", {}).get("buy", 0))
                ath_price = ath_by_token.get(token, 0)
                avg_entry_to_ath_mult = (
                    ath_price / avg_buy if avg_buy > 0 and ath_price > 0 else 0.0
                )

                roi_pct = float(pos.get("roi", 0))

                row = {
                    "wallet_address": wallet_address,
                    "token_address": token,
                    "scan_id": str(uuid.uuid4()),
                    "first_entry_price": float(pos.get("averages", {}).get("buy", 0)),
                    "first_entry_usd": float(pos.get("invested", 0)),
                    "first_entry_timestamp": _parse_timestamp(
                        pos.get("timing", {}).get("firstBuy")
                    ),
                    "entry_price_to_launch_mult": entry_price_to_launch_mult,
                    "avg_entry_price": float(pos.get("averages", {}).get("buy", 0)),
                    "avg_entry_to_ath_mult": round(avg_entry_to_ath_mult, 4),
                    "all_buys": "[]",
                    "all_sells": "[]",
                    "buy_count": int(pos.get("counts", {}).get("buys", 0)),
                    "sell_count": int(pos.get("counts", {}).get("sells", 0)),
                    "total_spent_usd": round(float(pos.get("invested", 0)), 2),
                    "realized_pnl_usd": round(
                        float(pos.get("pnl", {}).get("realized", 0)), 2
                    ),
                    "unrealized_pnl_usd": round(
                        float(pos.get("pnl", {}).get("unrealized", 0)), 2
                    ),
                    "total_pnl_usd": round(
                        float(pos.get("pnl", {}).get("total", 0)), 2
                    ),
                    "realized_roi_mult": (roi_pct / 100) + 1,  # roi% to multiplier
                    "total_roi_mult": (roi_pct / 100) + 1,
                    "qualifies": 1,
                    "outcome": (
                        "win" if roi_pct >= 400
                        else ("draw" if roi_pct >= 350 else "loss")
                    ),
                    "disqualify_reason": "",
                    "wallet_source": "leaderboard",
                    "updated_at": datetime.now(timezone.utc),
                }
                rows.append(row)

        logger.info("[LEADERBOARD] Built %d rows from %d wallets", len(rows), len(processed_wallets))

        # =================================================================
        # Step 6: Bulk insert to ClickHouse
        # =================================================================
        if rows:
            insert_wallet_token_stats(rows)
            logger.info("[LEADERBOARD] Inserted %d wallet_token_stats rows", len(rows))

        # =================================================================
        # Step 7: Enrich top 15 for display cache
        # =================================================================
        try:
            top_15 = ch.query(
                """SELECT wallet_address FROM wallet_aggregate_stats FINAL
                   WHERE tokens_qualified >= 1
                   ORDER BY professional_score DESC LIMIT 15"""
            )
            top_15_addrs = [row[0] for row in top_15.result_rows]
            if top_15_addrs:
                enriched = st.get_wallets_batch(top_15_addrs)
                r.setex(
                    "kys:elite15_enriched",
                    86400 * 7,
                    json.dumps(enriched, default=str),
                )
                logger.info("[LEADERBOARD] Cached enriched top 15 wallets")
        except Exception as exc:
            logger.warning("[LEADERBOARD] Failed to enrich top 15: %s", exc)

        # =================================================================
        # Return summary
        # =================================================================
        return {
            "status": "success",
            "candidates": len(all_candidates),
            "processed": len(processed_wallets),
            "rows_inserted": len(rows),
            "tokens_fetched": len(unique_tokens),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        logger.exception("[LEADERBOARD] leaderboard_discovery_scan FAILED")
        raise self.retry(exc=exc)
