"""
Leaderboard Discovery Pipeline — V3

Discovers Elite wallets from SolanaTracker's V2 leaderboard, fetches their
paginated positions, enrichment data (first-buyers, ATH, token info, individual
trades), and inserts full V3 rows into ClickHouse wallet_token_stats.

Flow:
  1. Fetch leaderboard candidates across 3 sort criteria (tokens, roi, volume)
  2. Rank by tokensTraded, take top 150, filter out recently processed wallets
  3. Paginated positions per wallet + conviction filter
  4. Per-token fetches: first-buyers, ATH, token info, individual trades
  5. Build full V3 wallet_token_stats rows
  6. Bulk insert to ClickHouse (MV auto-fires)
  7. Enrich top 15 for display cache in Redis
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from celery_app import celery
from services.clickhouse_client import get_clickhouse_client, insert_wallet_token_stats
from services.redis_pool import get_redis_client
from services.solana_tracker_client import get_st_client

logger = logging.getLogger(__name__)

LEADERBOARD_SEEN_KEY = "kys:leaderboard_seen_wallets"
LEADERBOARD_SEEN_TTL = 86400 * 7  # 7 days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_timestamp(ts) -> datetime:
    """Parse a timestamp value into a datetime.

    Handles:
      - None -> now()
      - Millisecond epoch int (> 1e12) -> datetime
      - Seconds epoch int -> datetime
      - ISO 8601 string -> datetime
    """
    if ts is None:
        return datetime.now(timezone.utc)

    if isinstance(ts, (int, float)):
        if ts > 1e12:
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    if isinstance(ts, str):
        try:
            cleaned = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned)
        except (ValueError, TypeError):
            pass

    return datetime.now(timezone.utc)


def _is_conviction(pos: dict) -> bool:
    """Return True if position shows conviction (real commitment + 4x return)."""
    invested = float(pos.get("invested") or 0)
    if invested < 100:
        return False
    buys = int((pos.get("counts") or {}).get("buys", 0))
    if not (buys >= 2 or invested >= 250):
        return False
    pnl = pos.get("pnl") or {}
    realized = float(pnl.get("realized") or 0)
    unrealized = float(pnl.get("unrealized") or 0)
    threshold = invested * 3
    return realized >= threshold or unrealized >= threshold


def _extract_token_mint(pos: dict) -> str:
    """Extract the token mint address from a position dict."""
    raw_token = pos.get("token", "")
    if isinstance(raw_token, dict):
        return raw_token.get("mint", "")
    return str(raw_token or pos.get("tokenAddress") or "")


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery.task(
    name="tasks.leaderboard_discovery_scan",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    acks_late=True,
    time_limit=1800,
)
def leaderboard_discovery_scan(self):
    """Discover top wallets from the SolanaTracker V2 leaderboard, fetch their
    positions and enrichment data, and populate ClickHouse wallet_token_stats rows."""

    try:
        st = get_st_client()
        r = get_redis_client()
        ch = get_clickhouse_client()

        if ch is None:
            logger.error("[LEADERBOARD] ClickHouse unavailable, aborting")
            return {"status": "error", "error": "ClickHouse unavailable"}

        # =================================================================
        # Step 1: Fetch leaderboard candidates (3 sweeps)
        # =================================================================
        logger.info("[LEADERBOARD] Fetching leaderboard candidates...")

        tokens_candidates = st.get_leaderboard_top(
            sort="tokens", min_invested=100, min_trades=10, limit=200,
        )
        time.sleep(2)

        roi_candidates = st.get_leaderboard_top(
            sort="roi", min_roi=500, min_invested=100, min_trades=10, limit=200,
        )
        time.sleep(2)

        volume_candidates = st.get_leaderboard_top(
            sort="volume", min_invested=200, min_trades=10, limit=200,
        )

        # Merge and deduplicate by wallet address
        all_candidates: dict[str, dict] = {}
        for candidate in tokens_candidates + roi_candidates + volume_candidates:
            wallet = candidate.get("wallet") or candidate.get("walletAddress") or ""
            if wallet and wallet not in all_candidates:
                all_candidates[wallet] = candidate

        logger.info(
            "[LEADERBOARD] Fetched %d unique candidates from 3 leaderboard queries",
            len(all_candidates),
        )

        # =================================================================
        # Step 2: Rank by tokensTraded, take top 150, recency filter
        # =================================================================
        ranked = sorted(
            all_candidates.values(),
            key=lambda c: int((c.get("counts") or {}).get("tokensTraded", 0)),
            reverse=True,
        )
        top_150_wallets = [
            c.get("wallet") or c.get("walletAddress") or ""
            for c in ranked[:150]
            if c.get("wallet") or c.get("walletAddress")
        ]

        wallets_to_process: list[str] = []
        for wallet_addr in top_150_wallets:
            if r.sismember(LEADERBOARD_SEEN_KEY, wallet_addr):
                continue

            # Check ClickHouse recency — skip if updated within 24 hours
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
            except Exception:
                pass

            wallets_to_process.append(wallet_addr)

        logger.info(
            "[LEADERBOARD] %d wallets to process after filtering (from %d top-150)",
            len(wallets_to_process),
            len(top_150_wallets),
        )

        # =================================================================
        # Step 3: Paginated positions per wallet + conviction filter
        # =================================================================
        wallet_positions: dict[str, list[dict]] = {}
        unique_tokens: set[str] = set()
        token_meta_cache: dict[str, dict] = {}

        for i, wallet_addr in enumerate(wallets_to_process):
            time.sleep(0.5)

            try:
                positions = st.get_wallet_positions_paginated(
                    wallet_addr,
                    roi_min=300,
                    invested_min=100,
                )
            except Exception as exc:
                logger.warning("[LEADERBOARD] Failed to fetch positions for %s: %s", wallet_addr[:12], exc)
                continue

            qualifying = [pos for pos in positions if _is_conviction(pos)]

            # Discard wallets with 0 qualifying positions (permissive: let data accumulate)
            if len(qualifying) == 0:
                continue

            wallet_positions[wallet_addr] = qualifying

            # Collect unique tokens and cache metadata from position `meta` field
            for pos in qualifying:
                token = _extract_token_mint(pos)
                if token:
                    unique_tokens.add(token)
                    meta = pos.get("meta") or {}
                    if meta and token not in token_meta_cache:
                        token_meta_cache[token] = meta

            # NOTE: wallet is NOT marked as "seen" here — only after successful
            # CH insert in Step 6, to prevent data loss on task failure.

            if (i + 1) % 25 == 0:
                logger.info(
                    "[LEADERBOARD] Processed %d/%d wallets, %d qualified so far",
                    i + 1, len(wallets_to_process), len(wallet_positions),
                )

        processed_wallet_set = set(wallet_positions.keys())

        # Pre-build token → wallets mapping (avoids O(wallets*tokens) in Step 4)
        token_to_wallets: dict[str, list[str]] = {}
        for w_addr, positions in wallet_positions.items():
            for pos in positions:
                t = _extract_token_mint(pos)
                if t:
                    token_to_wallets.setdefault(t, []).append(w_addr)

        logger.info(
            "[LEADERBOARD] %d wallets qualified with >= 1 position, %d unique tokens",
            len(wallet_positions),
            len(unique_tokens),
        )

        # =================================================================
        # Step 4: Per-token fetches (first-buyers, ATH, token info, trades)
        # =================================================================
        first_buyers_list_by_token: dict[str, list[str]] = {}
        first_buyer_rank_by_token: dict[str, dict[str, int]] = {}
        ath_by_token: dict[str, float] = {}
        launch_price_by_token: dict[str, float] = {}
        creation_time_by_token: dict[str, datetime] = {}
        trades_by_token_wallet: dict[str, dict[str, list[dict]]] = {}

        for token in unique_tokens:
            time.sleep(0.5)

            # --- First buyers ---
            try:
                buyers = st.get_first_buyers(token, limit=100)
                buyer_wallets = [b.get("wallet") for b in buyers if b.get("wallet")]
                first_buyers_list_by_token[token] = buyer_wallets
                first_buyer_rank_by_token[token] = {
                    w: idx + 1 for idx, w in enumerate(buyer_wallets) if w in processed_wallet_set
                }
            except Exception as exc:
                logger.debug("[LEADERBOARD] first_buyers failed for %s: %s", token[:12], exc)
                first_buyers_list_by_token[token] = []
                first_buyer_rank_by_token[token] = {}

            # --- ATH ---
            try:
                ath_data = st.get_token_ath(token)
                ath_by_token[token] = float(
                    (ath_data or {}).get("highest_price")
                    or (ath_data or {}).get("highestPrice")
                    or 0
                )
            except Exception as exc:
                logger.debug("[LEADERBOARD] token ATH failed for %s: %s", token[:12], exc)
                ath_by_token[token] = 0.0

            # --- Token info (launch price + creation time) ---
            launch_price = 0.0
            creation_time = datetime(1970, 1, 1, tzinfo=timezone.utc)
            try:
                token_info = st.get_token_info(token)
                if token_info:
                    created_ts = (token_info.get("token") or {}).get("creation", {}).get("created_time")
                    if created_ts:
                        creation_time = datetime.fromtimestamp(float(created_ts), tz=timezone.utc)
                    pools = token_info.get("pools") or []
                    if pools:
                        pools_with_ts = [p for p in pools if p.get("createdAt")]
                        if pools_with_ts:
                            earliest = min(pools_with_ts, key=lambda p: p["createdAt"])
                        else:
                            earliest = max(pools, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))
                        launch_price = float((earliest.get("price") or {}).get("usd", 0) or 0)
            except Exception as exc:
                logger.debug("[LEADERBOARD] token_info failed for %s: %s", token[:12], exc)
            launch_price_by_token[token] = launch_price
            creation_time_by_token[token] = creation_time

            # --- Individual trades per wallet that traded this token ---
            trades_by_token_wallet[token] = {}
            wallets_for_token = token_to_wallets.get(token, [])
            for wallet_addr in wallets_for_token:
                time.sleep(0.4)
                try:
                    trades = st.get_wallet_token_trades(token, wallet_addr)
                    trades_by_token_wallet[token][wallet_addr] = trades
                except Exception as exc:
                    logger.debug("[LEADERBOARD] trades failed for %s/%s: %s", token[:12], wallet_addr[:12], exc)
                    trades_by_token_wallet[token][wallet_addr] = []

        logger.info(
            "[LEADERBOARD] Fetched enrichment data for %d tokens",
            len(unique_tokens),
        )

        # =================================================================
        # Step 5: Build full V3 rows
        # =================================================================
        rows: list[dict] = []

        for wallet_address, positions in wallet_positions.items():
            for pos in positions:
                token = _extract_token_mint(pos)
                if not token:
                    continue

                # --- Timing fields ---
                timing = pos.get("timing") or {}
                first_entry_timestamp = _parse_timestamp(timing.get("firstBuy"))
                last_buy_timestamp = _parse_timestamp(timing.get("lastBuy"))
                first_sell_timestamp = _parse_timestamp(timing.get("firstSell"))
                sell_time = _parse_timestamp(timing.get("lastSell"))

                hold_time_secs = int(timing.get("holdTimeSecs") or 0)

                # --- Price fields ---
                averages = pos.get("averages") or {}
                avg_buy = float(averages.get("buy", 0))
                first_entry_price = avg_buy

                ath_price = ath_by_token.get(token, 0.0)
                launch_price = launch_price_by_token.get(token, 0.0)
                token_creation_time = creation_time_by_token.get(token, datetime(1970, 1, 1, tzinfo=timezone.utc))

                # --- Entry signal computations ---
                avg_entry_to_ath_mult = ath_price / avg_buy if avg_buy > 0 and ath_price > 0 else 0.0
                entry_vs_launch_mult = launch_price / avg_buy if avg_buy > 0 and launch_price > 0 else 0.0

                # Combined entry_price_to_launch_mult
                fb_list = first_buyers_list_by_token.get(token, [])
                fb_rank_map = first_buyer_rank_by_token.get(token, {})
                fb_rank = fb_rank_map.get(wallet_address, 0)

                if fb_rank > 0 and len(fb_list) > 0 and launch_price > 0:
                    fb_score = 1.0 / max(0.01, fb_rank / len(fb_list))
                    price_score = entry_vs_launch_mult
                    entry_price_to_launch_mult = max(fb_score, price_score)
                elif entry_vs_launch_mult > 0:
                    entry_price_to_launch_mult = entry_vs_launch_mult
                else:
                    entry_price_to_launch_mult = 1.0  # neutral

                # --- Volume / counts ---
                counts = pos.get("counts") or {}
                buy_count = int(counts.get("buys", 0))
                sell_count = int(counts.get("sells", 0))
                trade_count = int(counts.get("total", buy_count + sell_count))

                volume = pos.get("volume") or {}
                tokens_bought_native = float(volume.get("tokensBought") or 0)
                tokens_sold_native = float(volume.get("tokensSold") or 0)

                current = pos.get("current") or {}
                current_balance = float(current.get("balance") or 0)
                current_value_usd = float(current.get("value") or 0)
                current_price_usd = float(current.get("price") or 0)
                avg_cost_per_token = float(current.get("avgCost") or 0)

                invested = float(pos.get("invested") or 0)

                sell_proceeds_usd = float(pos.get("proceeds") or 0)
                avg_sell_size_usd = float(averages.get("sell") or 0)

                # --- PnL fields ---
                pnl = pos.get("pnl") or {}
                realized_pnl = float(pnl.get("realized") or 0)
                unrealized_pnl = float(pnl.get("unrealized") or 0)
                total_pnl = float(pnl.get("total") or 0)

                roi_pct = float(pos.get("roi") or 0)
                realized_roi_mult = (roi_pct / 100) + 1
                total_roi_mult = (roi_pct / 100) + 1

                # --- Outcome based on 4x realized OR unrealized ---
                threshold_4x = invested * 3  # 4x total = 3x profit
                threshold_draw = invested * 2.5  # 3.5x total = 2.5x profit
                if realized_pnl >= threshold_4x or unrealized_pnl >= threshold_4x:
                    outcome = "win"
                elif max(realized_pnl, unrealized_pnl) >= threshold_draw:
                    outcome = "draw"
                else:
                    outcome = "loss"

                # --- Individual trades as JSON ---
                token_trades = trades_by_token_wallet.get(token, {}).get(wallet_address, [])
                all_buys_json = json.dumps(
                    [t for t in token_trades if t.get("type") == "buy"],
                    default=str,
                )
                all_sells_json = json.dumps(
                    [t for t in token_trades if t.get("type") == "sell"],
                    default=str,
                )

                # --- Token metadata ---
                meta = token_meta_cache.get(token, {})
                token_name = str(meta.get("name") or meta.get("tokenName") or "")
                token_symbol = str(meta.get("symbol") or meta.get("tokenSymbol") or "")
                token_image = str(meta.get("image") or meta.get("logo") or "")
                token_decimals = int(meta.get("decimals") or 0)
                market_cap_usd = float(meta.get("marketCap") or meta.get("market_cap") or 0)
                liquidity_usd = float(meta.get("liquidity") or 0)
                primary_market = str(meta.get("primaryMarket") or meta.get("market") or meta.get("dex") or "")

                # --- First buyer rank ---
                first_buyer_rank = fb_rank_map.get(wallet_address, 0)

                row = {
                    "wallet_address": wallet_address,
                    "token_address": token,
                    "scan_id": str(uuid.uuid4()),
                    "first_entry_price": first_entry_price,
                    "first_entry_usd": round(invested, 2),
                    "first_entry_timestamp": first_entry_timestamp,
                    "last_buy_timestamp": last_buy_timestamp,
                    "first_sell_timestamp": first_sell_timestamp,
                    "sell_time": sell_time,
                    "hold_time_secs": hold_time_secs,
                    "avg_entry_price": avg_buy,
                    "avg_entry_to_ath_mult": round(avg_entry_to_ath_mult, 4),
                    "entry_price_to_launch_mult": round(entry_price_to_launch_mult, 4),
                    "entry_vs_launch_mult": round(entry_vs_launch_mult, 4),
                    "ath_price_raw": ath_price,
                    "launch_price_raw": launch_price,
                    "token_creation_time": token_creation_time,
                    "current_price_usd": current_price_usd,
                    "tokens_bought_native": tokens_bought_native,
                    "tokens_sold_native": tokens_sold_native,
                    "current_balance": current_balance,
                    "current_value_usd": round(current_value_usd, 2),
                    "avg_cost_per_token": avg_cost_per_token,
                    "avg_sell_size_usd": round(avg_sell_size_usd, 2),
                    "buy_count": buy_count,
                    "sell_count": sell_count,
                    "trade_count": trade_count,
                    "total_spent_usd": round(invested, 2),
                    "sell_proceeds_usd": round(sell_proceeds_usd, 2),
                    "realized_pnl_usd": round(realized_pnl, 2),
                    "unrealized_pnl_usd": round(unrealized_pnl, 2),
                    "total_pnl_usd": round(total_pnl, 2),
                    "roi_pct": round(roi_pct, 2),
                    "realized_roi_mult": round(realized_roi_mult, 4),
                    "total_roi_mult": round(total_roi_mult, 4),
                    "all_buys": all_buys_json,
                    "all_sells": all_sells_json,
                    "token_name": token_name,
                    "token_symbol": token_symbol,
                    "token_image": token_image,
                    "token_decimals": token_decimals,
                    "market_cap_usd": market_cap_usd,
                    "liquidity_usd": liquidity_usd,
                    "primary_market": primary_market,
                    "first_buyer_rank": first_buyer_rank,
                    "qualifies": 1,
                    "outcome": outcome,
                    "disqualify_reason": "",
                    "wallet_source": "leaderboard",
                    "updated_at": datetime.now(timezone.utc),
                }
                rows.append(row)

        logger.info("[LEADERBOARD] Built %d rows from %d wallets", len(rows), len(wallet_positions))

        # =================================================================
        # Step 6: Bulk insert to ClickHouse
        # =================================================================
        if rows:
            insert_wallet_token_stats(rows)
            logger.info("[LEADERBOARD] Inserted %d wallet_token_stats rows", len(rows))

            # Mark wallets as "seen" AFTER successful CH insert (not before)
            for wallet_addr in wallet_positions:
                r.sadd(LEADERBOARD_SEEN_KEY, wallet_addr)
            r.expire(LEADERBOARD_SEEN_KEY, LEADERBOARD_SEEN_TTL)

        # =================================================================
        # Step 7: Elite 15 from CH with tokens_traded_30d >= 10 filter
        # =================================================================
        try:
            top_15 = ch.query("""
                SELECT wallet_address FROM wallet_aggregate_stats FINAL
                WHERE tokens_traded_30d >= 10
                ORDER BY professional_score DESC LIMIT 15
            """)
            top_15_addrs = [row[0] for row in top_15.result_rows]

            # Fallback: if fewer than 15, relax to tokens_qualified >= 1
            if len(top_15_addrs) < 15:
                fallback = ch.query("""
                    SELECT wallet_address FROM wallet_aggregate_stats FINAL
                    WHERE tokens_qualified >= 1
                    ORDER BY professional_score DESC LIMIT 15
                """)
                fallback_addrs = [row[0] for row in fallback.result_rows]
                existing = set(top_15_addrs)
                for addr in fallback_addrs:
                    if addr not in existing:
                        top_15_addrs.append(addr)
                        existing.add(addr)
                    if len(top_15_addrs) >= 15:
                        break

            if top_15_addrs:
                # Enrich via batch wallet data
                enriched_wallets = st.get_wallets_batch(top_15_addrs)

                # Build enriched payload with per-wallet token positions from CH
                enriched_payload: list[dict[str, Any]] = []
                for ew in enriched_wallets:
                    w_addr = ew.get("wallet") or ew.get("walletAddress") or ""
                    if not w_addr:
                        continue

                    # Query full token positions from CH for this wallet
                    try:
                        positions_result = ch.query(
                            """SELECT
                                token_address, token_name, token_symbol, token_image,
                                token_decimals, primary_market,
                                avg_entry_price, avg_cost_per_token,
                                first_entry_timestamp, last_buy_timestamp,
                                first_sell_timestamp, sell_time, hold_time_secs,
                                ath_price_raw, launch_price_raw, token_creation_time,
                                current_price_usd, current_balance, current_value_usd,
                                market_cap_usd, liquidity_usd,
                                avg_entry_to_ath_mult, entry_price_to_launch_mult, entry_vs_launch_mult,
                                realized_pnl_usd, unrealized_pnl_usd, total_pnl_usd,
                                roi_pct, total_roi_mult,
                                buy_count, sell_count, trade_count,
                                total_spent_usd, sell_proceeds_usd,
                                first_buyer_rank, all_buys, all_sells,
                                outcome
                            FROM wallet_token_stats FINAL
                            WHERE wallet_address = {addr:String} AND qualifies = 1
                            ORDER BY total_pnl_usd DESC
                            LIMIT 50""",
                            parameters={"addr": w_addr},
                        )
                        token_rows = []
                        for pr in positions_result.result_rows:
                            token_rows.append({
                                "token_address": pr[0],
                                "token_name": pr[1],
                                "token_symbol": pr[2],
                                "token_image": pr[3],
                                "token_decimals": int(pr[4]),
                                "primary_market": pr[5],
                                "avg_entry_price": float(pr[6]),
                                "avg_cost_per_token": float(pr[7]),
                                "first_entry_timestamp": pr[8].isoformat() if hasattr(pr[8], "isoformat") else str(pr[8]),
                                "last_buy_timestamp": pr[9].isoformat() if hasattr(pr[9], "isoformat") else str(pr[9]),
                                "first_sell_timestamp": pr[10].isoformat() if hasattr(pr[10], "isoformat") else str(pr[10]),
                                "sell_time": pr[11].isoformat() if hasattr(pr[11], "isoformat") else str(pr[11]),
                                "hold_time_secs": int(pr[12]),
                                "ath_price_raw": float(pr[13]),
                                "launch_price_raw": float(pr[14]),
                                "token_creation_time": pr[15].isoformat() if hasattr(pr[15], "isoformat") else str(pr[15]),
                                "current_price_usd": float(pr[16]),
                                "current_balance": float(pr[17]),
                                "current_value_usd": float(pr[18]),
                                "market_cap_usd": float(pr[19]),
                                "liquidity_usd": float(pr[20]),
                                "avg_entry_to_ath_mult": float(pr[21]),
                                "entry_price_to_launch_mult": float(pr[22]),
                                "entry_vs_launch_mult": float(pr[23]),
                                "realized_pnl_usd": float(pr[24]),
                                "unrealized_pnl_usd": float(pr[25]),
                                "total_pnl_usd": float(pr[26]),
                                "roi_pct": float(pr[27]),
                                "total_roi_mult": float(pr[28]),
                                "buy_count": int(pr[29]),
                                "sell_count": int(pr[30]),
                                "trade_count": int(pr[31]),
                                "total_spent_usd": float(pr[32]),
                                "sell_proceeds_usd": float(pr[33]),
                                "first_buyer_rank": int(pr[34]),
                                "all_buys": json.loads(pr[35] or "[]"),
                                "all_sells": json.loads(pr[36] or "[]"),
                                "outcome": pr[37],
                            })
                    except Exception:
                        token_rows = []

                    enriched_payload.append({
                        **ew,
                        "positions": token_rows,
                    })

                r.setex(
                    "kys:elite15_enriched",
                    86400 * 7,
                    json.dumps(enriched_payload, default=str),
                )
                logger.info("[LEADERBOARD] Cached enriched top 15 wallets (%d)", len(enriched_payload))
        except Exception as exc:
            logger.warning("[LEADERBOARD] Failed to enrich top 15: %s", exc)

        # =================================================================
        # Return summary
        # =================================================================
        return {
            "status": "success",
            "candidates": len(all_candidates),
            "top_150": len(top_150_wallets),
            "processed": len(wallet_positions),
            "rows_inserted": len(rows),
            "tokens_fetched": len(unique_tokens),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        logger.exception("[LEADERBOARD] leaderboard_discovery_scan FAILED")
        raise self.retry(exc=exc)
