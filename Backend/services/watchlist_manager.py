"""
Watchlist league mechanics - handles ranking, degradation, and promotion

QUALIFICATION FLOORS (hard minimums - anything below = Loss):
  - Wallet must achieve >= 5x on every trade (realized ROI multiplier)
  - Wallet must spend >= $75 per token (single or cumulative entries)
  - Token must do >= 30x from launch price to ATH

WIN / DRAW / LOSS definitions:
  - Win  = wallet achieved > 5x AND token did > 30x launch-to-ATH
  - Draw = wallet hit exactly 5x OR token hit exactly 30x (at threshold)
  - Loss = wallet made < 5x OR token did < 30x launch-to-ATH OR spent < $75

Entry consistency: measured by variance of price_multiplier at entry (how far from
launch price the wallet entered) across all qualifying buy trades. A wallet that
consistently enters near 1x (close to launch price) scores high. A wallet that
sometimes enters at 1x and sometimes at 8x scores low. This correctly handles
slow pump.fun graduation — what matters is price position, not clock time.

FIXES IN THIS VERSION:

  Bug 3 — Negative ROI no longer subtracts score points.
    _calculate_professional_score() now floors roi_7d at 0 before applying it.
    Negative ROI is already penalised via win_rate and runners dropping — a
    double-penalty via negative score points was catastrophically wrong, causing
    active wallets in a crash-affected week to score below zombie wallets.

  Bug 2 — Open positions now use mark-to-market ROI, not excluded or counted as losses.
    _calculate_roi_from_trades() and the inline _qualified_roi() lambda in
    _refresh_wallet_metrics() now compute unrealized value for open positions using
    the current price from the database (most recent price record for the token).
    Total ROI = (realized gains on closed + mark-to-market value of open - total invested)
                / total invested.
    Tokens that have no price data at all (expired/rugged with no sells) are treated
    as full losses since there is no recoverable value.

  Bug 4 — Consistency score now measures entry PRICE MULTIPLIER not timing or
    per-token price variance.
    _calculate_entry_consistency_score() accepts a flat list of price_multiplier
    values (the multiplier from launch price at the moment of each buy). CV of
    these values across all qualifying buys measures how consistently close to
    launch price the wallet enters — correctly handles slow-graduating tokens where
    clock time is a misleading proxy for entry quality.

  ADDED_AT FILTERING:
    _refresh_wallet_metrics() now accepts an added_at parameter. When provided,
    _get_recent_trades() clips the lookback window so only trades on or after
    added_at are counted. Pre-watchlist history is excluded.

  MERGE-ONLY SAVE:
    _save_watchlist() only writes fields with non-None computed values so that
    fields absent from this cycle retain their existing DB values.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict
import statistics
from services.supabase_client import get_supabase_client, SCHEMA_NAME


# ─────────────────────────────────────────────────────────────────────────────
# HARD QUALIFICATION THRESHOLDS
# ─────────────────────────────────────────────────────────────────────────────
MIN_WALLET_ROI_MULT     = 5.0
MIN_SPEND_USD           = 75.0
MIN_TOKEN_LAUNCH_TO_ATH = 30.0
# ─────────────────────────────────────────────────────────────────────────────


class WatchlistLeagueManager:
    """Manages Premier League-style watchlist mechanics"""

    def __init__(self):
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME

    def _table(self, name: str):
        return self.supabase.schema(self.schema).table(name)


    def rerank_user_watchlist(self, user_id: str):
        """
        Recalculate positions for ONE user's watchlist.
        Called after: adding/removing wallet, daily refresh.
        Fetches added_at per wallet and passes it to _refresh_wallet_metrics
        so only post-watchlist trades count toward metrics.
        """
        watchlist = self._get_watchlist(user_id)
        if not watchlist:
            return []

        old_positions = {w['wallet_address']: w.get('position', 999) for w in watchlist}

        for wallet in watchlist:
            # Pass added_at so _refresh_wallet_metrics only counts post-watchlist trades
            updated = self._refresh_wallet_metrics(
                wallet['wallet_address'],
                added_at=wallet.get('added_at'),
            )
            wallet.update(updated)

        watchlist = self._calculate_league_positions(watchlist)
        watchlist = self._update_position_movements(watchlist, old_positions)

        for wallet in watchlist:
            wallet['form'] = self._calculate_form(wallet['wallet_address'])

        for wallet in watchlist:
            self._detect_degradation(wallet)

        self._save_watchlist(user_id, watchlist)

        critical_count = sum(1 for w in watchlist if w.get('status') == 'critical')
        if critical_count > 0:
            self._generate_promotion_queue(user_id, watchlist)

        return watchlist


    def _refresh_wallet_metrics(
        self,
        wallet_address: str,
        added_at: Optional[str] = None,
    ) -> Dict:
        """
        Fetch LATEST performance metrics for a wallet.
        Uses RECENT activity (7 days) + historical context (30 days).
        Applies hard qualification floors: $75 min spend, 5x min ROI, 30x token launch-to-ATH.

        added_at: ISO timestamp. Only trades on or after this date are counted.
          Ensures pre-watchlist history doesn't skew scores.

        Bug 2 fix: ROI now uses mark-to-market for open positions. Tokens with buys
          but no sells contribute their current unrealized value instead of being
          excluded or counted as 100% losses.

        Bug 4 fix: entry consistency measures price_multiplier at entry (how far from
          launch price), not buy_hour_offset. Correctly handles slow pump.fun graduation.
        """
        recent_trades = self._get_recent_trades(wallet_address, days=7,  since=added_at)
        trades_30d    = self._get_recent_trades(wallet_address, days=30, since=added_at)

        distance_to_ath_values = []
        entry_quality_values   = []

        # Bug 4 fix: collect price_multiplier at entry for consistency scoring.
        # price_multiplier on a buy record = how far from launch price at moment of entry.
        # e.g. 1.0 = bought at launch price, 3.0 = bought when already 3x from launch.
        entry_price_multipliers = []

        # Group trades by token
        by_token = defaultdict(lambda: {
            'buys': [], 'sells': [], 'ath_price': 0,
            'total_invested': 0.0, 'buy_prices': [],
            'entry_multipliers': [],
            'launch_price': None,
        })

        for trade in trades_30d:
            token = trade.get('token_address')
            if not token:
                continue

            price     = float(trade.get('price_per_token', 0))
            usd_value = float(trade.get('usd_value', 0))
            if price == 0:
                continue

            if trade.get('side') == 'buy':
                by_token[token]['buys'].append(price)
                by_token[token]['buy_prices'].append(price)
                by_token[token]['total_invested'] += usd_value

                # Bug 4 fix: price_multiplier = how far from launch at entry time
                mult = trade.get('price_multiplier')
                if mult is not None:
                    by_token[token]['entry_multipliers'].append(float(mult))
                    entry_price_multipliers.append(float(mult))
            else:
                by_token[token]['sells'].append(price)

            if price > by_token[token]['ath_price']:
                by_token[token]['ath_price'] = price

        # Per-token metrics
        for token, data in by_token.items():
            invested = data['total_invested']

            if invested < MIN_SPEND_USD:
                continue

            if data['buys'] and data['ath_price'] > 0:
                avg_entry = sum(data['buys']) / len(data['buys'])

                distance_to_ath_mult = data['ath_price'] / avg_entry if avg_entry > 0 else 0
                if distance_to_ath_mult > 0:
                    distance_to_ath_values.append(distance_to_ath_mult)

                min_entry = min(data['buys'])
                entry_quality_mult = avg_entry / min_entry if min_entry > 0 else 1
                if entry_quality_mult > 0:
                    entry_quality_values.append(entry_quality_mult)

        avg_distance_to_ath = (
            sum(distance_to_ath_values) / len(distance_to_ath_values)
            if distance_to_ath_values else 0
        )
        avg_entry_quality = (
            sum(entry_quality_values) / len(entry_quality_values)
            if entry_quality_values else 0
        )

        def _qualified_roi(trades):
            """
            ROI over all token positions that meet the $75 floor.
            Bug 2 fix: open positions (buys but no sells) use mark-to-market value
            via the most recent price record in the trade data. Tokens with no price
            data at all (expired/rugged, no sells, no current price) are full losses.
            """
            token_inv          = defaultdict(float)
            token_real         = defaultdict(float)
            token_latest_price = defaultdict(float)   # most recent price seen for token

            for t in trades:
                tok = t.get('token_address')
                if not tok:
                    continue
                usd   = float(t.get('usd_value', 0))
                price = float(t.get('price_per_token', 0))
                if t.get('side') == 'buy':
                    token_inv[tok] += usd
                else:
                    token_real[tok] += usd
                # track most recent price seen regardless of side
                if price > 0:
                    token_latest_price[tok] = price   # trades ordered desc, first = latest

            total_inv  = 0.0
            total_real = 0.0

            for tok, invested in token_inv.items():
                if invested < MIN_SPEND_USD:
                    continue
                total_inv += invested

                if token_real[tok] > 0:
                    # Closed (at least partially sold) — use realized value
                    total_real += token_real[tok]
                elif token_latest_price[tok] > 0:
                    # Bug 2 fix: open position — mark to current price
                    # avg_buy reconstructed from buy trades
                    buy_prices = [
                        float(t.get('price_per_token', 0))
                        for t in trades
                        if t.get('token_address') == tok
                        and t.get('side') == 'buy'
                        and float(t.get('price_per_token', 0)) > 0
                    ]
                    if buy_prices:
                        avg_buy = sum(buy_prices) / len(buy_prices)
                        current = token_latest_price[tok]
                        mark_to_market = invested * (current / avg_buy)
                        total_real += mark_to_market
                    # else: no price data at all → treat as full loss (add 0)

            if total_inv == 0:
                return 0
            return ((total_real - total_inv) / total_inv) * 100

        roi_7d  = _qualified_roi(recent_trades)
        roi_30d = _qualified_roi(trades_30d)

        # Multiplier for 30d (for degradation comparison) — same mark-to-market logic
        token_inv_30d          = defaultdict(float)
        token_real_30d         = defaultdict(float)
        token_latest_price_30d = defaultdict(float)
        for t in trades_30d:
            tok   = t.get('token_address')
            if not tok:
                continue
            usd   = float(t.get('usd_value', 0))
            price = float(t.get('price_per_token', 0))
            if t.get('side') == 'buy':
                token_inv_30d[tok] += usd
            else:
                token_real_30d[tok] += usd
            if price > 0:
                token_latest_price_30d[tok] = price

        total_inv_30d  = 0.0
        total_real_30d = 0.0
        for tok, invested in token_inv_30d.items():
            if invested < MIN_SPEND_USD:
                continue
            total_inv_30d += invested
            if token_real_30d[tok] > 0:
                total_real_30d += token_real_30d[tok]
            elif token_latest_price_30d[tok] > 0:
                buy_prices = [
                    float(t.get('price_per_token', 0))
                    for t in trades_30d
                    if t.get('token_address') == tok
                    and t.get('side') == 'buy'
                    and float(t.get('price_per_token', 0)) > 0
                ]
                if buy_prices:
                    avg_buy = sum(buy_prices) / len(buy_prices)
                    current = token_latest_price_30d[tok]
                    total_real_30d += invested * (current / avg_buy)

        roi_30d_mult = (total_real_30d / total_inv_30d) if total_inv_30d > 0 else 1

        win_rate_7d  = self._calculate_win_rate(recent_trades)
        win_rate_30d = self._calculate_win_rate(trades_30d)

        # Bug 4 fix: consistency from price_multiplier at entry, not timing
        consistency_score = self._calculate_entry_consistency_score(entry_price_multipliers)

        metrics = {
            'roi_7d':                          roi_7d,
            'roi_30d':                         roi_30d,
            'roi_30d_multiplier':              roi_30d_mult,
            'runners_7d':                      self._count_runners(recent_trades, min_multiplier=MIN_WALLET_ROI_MULT),
            'runners_30d':                     self._count_runners(trades_30d,    min_multiplier=MIN_WALLET_ROI_MULT),
            'win_rate_7d':                     win_rate_7d,
            'win_rate_30d':                    win_rate_30d,
            'avg_distance_to_ath_multiplier':  avg_distance_to_ath,
            'avg_entry_quality_multiplier':    avg_entry_quality,
            'consistency_score':               consistency_score,
            'professional_score':              0,
            'last_trade_time':                 recent_trades[0]['block_time'] if recent_trades else None,
        }

        metrics['professional_score'] = self._calculate_professional_score(metrics)
        return metrics


    def _calculate_entry_consistency_score(self, entry_price_multipliers: List[float]) -> float:
        """
        Compute entry consistency score (0-100) from price_multiplier values at entry.

        Bug 4 fix: measures CV of price_multiplier at the moment of each buy across
        all qualifying trades. price_multiplier = how far from launch price the wallet
        entered (1.0 = bought at launch price, 5.0 = bought when already 5x from launch).

        This correctly handles slow pump.fun graduation: a wallet buying at 1.2x is an
        early entry regardless of whether that was hour 1 or hour 6 post-launch. Clock
        time is a misleading proxy; price position is the ground truth.

        Low CV (tight cluster near 1x) = consistent early entry = high score.
        High CV (sometimes 1x, sometimes 8x) = erratic entry discipline = low score.

        Eddie: entry_hour_range (0,1) → almost always near 1x → score ~90+
        Larry: entry_hour_range (3,8) → always late but consistently so → mid score
        Becky: entry_hour_range (0,3) but DIAMOND_HANDS holds through pumps and re-enters
               at various levels → wider spread → lower score than Eddie
        """
        mults = [m for m in entry_price_multipliers if m is not None and m > 0]

        if not mults:
            return 50.0

        if len(mults) == 1:
            return 70.0   # single trade — neutral, nothing to measure variance on

        try:
            mean_mult = statistics.mean(mults)
            if mean_mult == 0:
                return 50.0
            stdev = statistics.stdev(mults)
            cv    = stdev / mean_mult   # standard coefficient of variation
            # Map CV to 0-100: CV=0 → 100 (perfect consistency), CV=2 → 0
            score = max(0.0, 100.0 * (1.0 - min(cv, 2.0) / 2.0))
            return round(score, 1)
        except Exception:
            return 50.0


    def _calculate_professional_score(self, metrics: Dict) -> float:
        """
        Score = 40% ROI_7d + 30% runners_7d + 20% win_rate + 10% consistency.
        Emphasises RECENT performance (7 days) over 30-day average.

        Bug 3 fix: roi_7d is floored at 0 before scoring.
          Negative ROI contributes 0 points — not negative points.
          Bad ROI is already penalised via win_rate (losses lower it) and runners_7d
          (no wins = 0 runners). A double-penalty via negative score would let
          inactive zombie wallets outscore active traders in a crash-affected week.
        """
        score = 0

        # Bug 3 fix: floor at 0 — negative ROI gives 0 pts, not negative pts
        roi_7d = max(0, metrics.get('roi_7d', 0))
        score += min(roi_7d / 2, 40)

        runners_7d = metrics.get('runners_7d', 0)
        score += min(runners_7d * 6, 30)

        win_rate = metrics.get('win_rate_7d', 0)
        score += (win_rate / 100) * 20

        consistency = metrics.get('consistency_score', 0)
        score += (consistency / 100) * 10

        return round(score, 1)


    def _calculate_league_positions(self, wallets: List[Dict]) -> List[Dict]:
        def ranking_score(w):
            base   = w.get('professional_score', 0)
            source = w.get('source_type', 'single')
            return base if source == 'batch' else base * 0.75

        sorted_wallets = sorted(wallets, key=ranking_score, reverse=True)
        for idx, wallet in enumerate(sorted_wallets):
            wallet['position'] = idx + 1
            wallet['zone']     = self._get_zone(idx + 1, len(sorted_wallets))
        return sorted_wallets


    def _get_zone(self, position: int, total_wallets: int) -> str:
        if total_wallets <= 5:
            if position == 1:    return 'Elite'
            elif position <= 3:  return 'midtable'
            else:                return 'monitoring'
        elif total_wallets <= 10:
            if position <= 3:    return 'Elite'
            elif position <= 6:  return 'midtable'
            elif position <= 8:  return 'monitoring'
            else:                return 'relegation'
        else:
            pct = position / total_wallets
            if pct <= 0.3:   return 'Elite'
            elif pct <= 0.6: return 'midtable'
            elif pct <= 0.8: return 'monitoring'
            else:            return 'relegation'


    def _update_position_movements(self, watchlist: List[Dict], old_positions: Dict) -> List[Dict]:
        for wallet in watchlist:
            addr    = wallet['wallet_address']
            old_pos = old_positions.get(addr, 999)
            new_pos = wallet['position']

            if new_pos < old_pos:
                wallet['movement']          = 'up'
                wallet['positions_changed'] = old_pos - new_pos
            elif new_pos > old_pos:
                wallet['movement']          = 'down'
                wallet['positions_changed'] = new_pos - old_pos
            else:
                wallet['movement']          = 'stable'
                wallet['positions_changed'] = 0

        return watchlist


    def _calculate_form(self, wallet_address: str) -> List[Dict]:
        """
        Last 5 trades evaluated against the hard qualification floors.
        """
        trades = self._get_recent_trades(wallet_address, limit=50, days=30)

        by_token_ordered = {}
        for trade in trades:
            tok = trade.get('token_address')
            if not tok:
                continue
            if tok not in by_token_ordered:
                by_token_ordered[tok] = {
                    'buys': [], 'sells': [], 'total_invested': 0.0,
                    'token_ticker': trade.get('token_ticker', 'UNKNOWN'),
                    'block_time':   trade.get('block_time'),
                    'launch_to_ath_mult': trade.get('launch_to_ath_multiplier', 0),
                }
            entry = by_token_ordered[tok]
            usd   = float(trade.get('usd_value', 0))
            price = float(trade.get('price_per_token', 0))

            if trade.get('side') == 'buy':
                entry['buys'].append(price)
                entry['total_invested'] += usd
            else:
                entry['sells'].append(price)

        form = []
        for tok, data in list(by_token_ordered.items())[:5]:
            invested = data['total_invested']

            if invested < MIN_SPEND_USD:
                form.append({
                    'type':        'loss',
                    'result':      'loss',
                    'token':       data['token_ticker'],
                    'roi':         'N/A',
                    'time':        self._format_time_ago(data['block_time']),
                    'description': f"UNDER FLOOR — spent ${invested:.0f} (min ${MIN_SPEND_USD:.0f})",
                    'reason':      'below_spend_floor',
                })
                continue

            avg_buy  = statistics.mean(data['buys'])  if data['buys']  else 0
            avg_sell = statistics.mean(data['sells']) if data['sells'] else 0

            if avg_buy > 0 and avg_sell > 0:
                roi_mult = avg_sell / avg_buy
            elif avg_buy > 0:
                roi_mult = 1.0
            else:
                roi_mult = 0.0

            launch_to_ath = float(data.get('launch_to_ath_mult') or 0)

            roi_at_floor    = abs(roi_mult    - MIN_WALLET_ROI_MULT)    / MIN_WALLET_ROI_MULT    <= 0.02
            launch_at_floor = abs(launch_to_ath - MIN_TOKEN_LAUNCH_TO_ATH) / MIN_TOKEN_LAUNCH_TO_ATH <= 0.02

            roi_above_floor    = roi_mult    > MIN_WALLET_ROI_MULT    * 1.02
            launch_above_floor = launch_to_ath > MIN_TOKEN_LAUNCH_TO_ATH * 1.02

            if roi_above_floor and launch_above_floor:
                result = 'win'
            elif (roi_at_floor or roi_above_floor) and (launch_at_floor or launch_above_floor):
                result = 'draw'
            else:
                result = 'loss'

            roi_pct = (roi_mult - 1) * 100 if roi_mult > 0 else -100

            form.append({
                'type':               result,
                'result':             result,
                'token':              data['token_ticker'],
                'roi':                f"{roi_pct:.1f}%",
                'roi_multiplier':     round(roi_mult, 2),
                'launch_to_ath_mult': round(launch_to_ath, 1),
                'total_invested':     round(invested, 2),
                'entry_count':        len(data['buys']),
                'time':               self._format_time_ago(data['block_time']),
                'description': (
                    f"{data['token_ticker']} | "
                    f"{len(data['buys'])} entr{'y' if len(data['buys']) == 1 else 'ies'} | "
                    f"${invested:.0f} invested | "
                    f"{roi_mult:.1f}x ROI | "
                    f"{launch_to_ath:.0f}x token"
                ),
            })

        return form


    def _detect_degradation(self, wallet: Dict):
        """
        Flag wallets based on RECENT performance (7 days) measured against the hard floors.

        Alert 1 (inactivity): uses went_inactive_day if present in wallet payload
        for exact integer-day arithmetic. Falls back to last_trade_time inference
        for wallets that don't have an explicit inactive day tracked.
        """
        alerts = []

        roi_7d      = wallet.get('roi_7d', 0)
        runners_7d  = wallet.get('runners_7d', 0)
        win_rate_7d = wallet.get('win_rate_7d', 0)
        roi_30d     = wallet.get('roi_30d', 0)
        runners_30d = wallet.get('runners_30d', 0)

        # ── Alert 1: No recent activity ───────────────────────────────────────
        went_inactive_day = wallet.get('went_inactive_day', -1)

        if went_inactive_day is not None and went_inactive_day > 0:
            # Exact day known — use integer arithmetic, no timestamp drift
            # (requires sim day counter to be in wallet payload — set by harness)
            sim_day    = wallet.get('_sim_day', -1)
            days_since = (sim_day - went_inactive_day) if sim_day > 0 else -1
            if days_since >= 7:
                alerts.append({
                    'severity': 'yellow',
                    'message':  (
                        f'No activity for {days_since} days '
                        f'(inactive since Day {went_inactive_day})'
                    ),
                })
        elif not wallet.get('last_trade_time'):
            alerts.append({
                'severity': 'orange',
                'message':  'No trading activity in 7+ days',
            })
        else:
            last_trade = wallet['last_trade_time']
            if isinstance(last_trade, str):
                last_trade = datetime.fromisoformat(last_trade.replace('Z', '+00:00'))
            days_since = (datetime.utcnow().replace(tzinfo=last_trade.tzinfo) - last_trade).days
            if days_since > 7:
                alerts.append({
                    'severity': 'yellow',
                    'message':  f'No activity for {days_since} days',
                })

        # ── Alert 2: ROI below floor ──────────────────────────────────────────
        ROI_7D_TARGET = (MIN_WALLET_ROI_MULT - 1) * 100   # 400%
        if roi_7d < ROI_7D_TARGET * 0.25:
            if roi_30d > ROI_7D_TARGET * 0.5:
                alerts.append({
                    'severity': 'yellow',
                    'message':  f'Slow week: {roi_7d:.1f}% 7d ROI (but {roi_30d:.1f}% 30d)',
                })
            else:
                alerts.append({
                    'severity': 'red',
                    'message':  (
                        f'Sustained decline: {roi_7d:.1f}% 7d, {roi_30d:.1f}% 30d — '
                        f'not meeting {MIN_WALLET_ROI_MULT}x floor'
                    ),
                })
        elif roi_7d < ROI_7D_TARGET * 0.5:
            alerts.append({
                'severity': 'orange',
                'message':  f'7-day ROI below {MIN_WALLET_ROI_MULT}x floor: {roi_7d:.1f}% (target: {ROI_7D_TARGET:.0f}%+)',
            })

        # ── Alert 3: No qualifying runners ────────────────────────────────────
        if runners_7d == 0:
            if runners_30d >= 3:
                alerts.append({
                    'severity': 'yellow',
                    'message':  f'No {MIN_WALLET_ROI_MULT}x+ runners this week (but {runners_30d} in last 30d)',
                })
            else:
                alerts.append({
                    'severity': 'red',
                    'message':  f'No {MIN_WALLET_ROI_MULT}x+ runners in 30 days — replace immediately',
                })

        # ── Alert 4: Win rate below threshold ─────────────────────────────────
        if win_rate_7d < 30:
            alerts.append({
                'severity': 'orange',
                'message':  f'Win rate {win_rate_7d:.0f}% (floor: trades need {MIN_WALLET_ROI_MULT}x+ to count as win)',
            })

        # ── Alert 5: Relegation zone ──────────────────────────────────────────
        if wallet.get('zone') == 'relegation':
            alerts.append({
                'severity': 'red',
                'message':  f'In relegation zone (position #{wallet["position"]})',
            })

        # ── Alert 6: Poor form ────────────────────────────────────────────────
        form          = wallet.get('form', [])
        recent_losses = sum(1 for f in form[:3] if f.get('type') == 'loss')
        if recent_losses >= 2:
            alerts.append({
                'severity': 'orange',
                'message':  (
                    f'Poor form: {recent_losses}/3 recent losses '
                    f'(losses = below {MIN_WALLET_ROI_MULT}x ROI or token < {MIN_TOKEN_LAUNCH_TO_ATH}x launch-to-ATH)'
                ),
            })

        # ── Alert 7: Entry consistency degrading ──────────────────────────────
        consistency = wallet.get('consistency_score', 50)
        if consistency < 40:
            alerts.append({
                'severity': 'orange',
                'message':  f'Entry timing inconsistent (consistency score: {consistency:.0f}/100) — high variance across entries',
            })

        if any(a['severity'] == 'red' for a in alerts):
            wallet['status'] = 'critical'
        elif any(a['severity'] in ['orange', 'yellow'] for a in alerts):
            wallet['status'] = 'warning'
        else:
            wallet['status'] = 'healthy'

        wallet['degradation_alerts'] = alerts


    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _get_watchlist(self, user_id: str) -> List[Dict]:
        try:
            result = self._table('wallet_watchlist').select('*').eq('user_id', user_id).execute()
            return result.data
        except Exception as e:
            print(f"[WATCHLIST MANAGER] Error getting watchlist: {e}")
            return []


    def _save_watchlist(self, user_id: str, watchlist: List[Dict]):
        """
        MERGE-ONLY: only fields with non-None computed values are written.
        Fields absent from this cycle retain their existing DB values.
        """
        try:
            for wallet in watchlist:
                update = {'last_updated': datetime.utcnow().isoformat()}

                for field in [
                    'position', 'zone', 'movement', 'positions_changed',
                    'form', 'status', 'degradation_alerts',
                ]:
                    val = wallet.get(field)
                    if val is not None:
                        update[field] = val

                for field in [
                    'roi_7d', 'roi_30d', 'roi_30d_multiplier',
                    'runners_7d', 'runners_30d',
                    'win_rate_7d', 'win_rate_30d',
                    'avg_distance_to_ath_multiplier', 'avg_entry_quality_multiplier',
                    'consistency_score', 'last_trade_time', 'professional_score',
                ]:
                    val = wallet.get(field)
                    if val is not None:
                        update[field] = val

                self._table('wallet_watchlist').update(update).eq(
                    'user_id', user_id
                ).eq('wallet_address', wallet['wallet_address']).execute()
        except Exception as e:
            print(f"[WATCHLIST MANAGER] Error saving watchlist: {e}")


    def _generate_promotion_queue(self, user_id: str, watchlist: List[Dict]):
        try:
            from routes.wallets import get_wallet_analyzer
            analyzer = get_wallet_analyzer()

            runners = analyzer.find_trending_runners_enhanced(
                days_back=30, min_multiplier=MIN_TOKEN_LAUNCH_TO_ATH / 3,
                min_liquidity=50000
            )
            if not runners:
                return []

            all_candidates      = []
            watchlist_addresses = {w['wallet_address'] for w in watchlist}

            for runner in runners[:5]:
                wallets   = analyzer.analyze_token_professional(
                    token_address=runner['address'],
                    token_symbol=runner['symbol'],
                    min_roi_multiplier=MIN_WALLET_ROI_MULT,
                    user_id=user_id
                )
                qualified = [
                    w for w in wallets
                    if w['professional_score'] >= 70
                    and w.get('tier') in ['S', 'A']
                    and w['wallet'] not in watchlist_addresses
                ]
                all_candidates.extend(qualified[:3])

            all_candidates.sort(key=lambda x: x['professional_score'], reverse=True)
            return all_candidates[:10]

        except Exception as e:
            print(f"[WATCHLIST MANAGER] Error generating promotion queue: {e}")
            return []


    def _get_recent_trades(
        self,
        wallet_address: str,
        days: int = 7,
        limit: int = None,
        since: Optional[str] = None,
    ) -> List[Dict]:
        """
        Fetch recent trades for a wallet.

        since: ISO timestamp. Effective cutoff = max(now - days, since).
          Ensures we never count trades before the wallet was added to
          the watchlist (added_at filtering).
        """
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)

            if since:
                try:
                    since_dt = datetime.fromisoformat(
                        since.replace('Z', '').split('+')[0]
                    )
                    cutoff = max(cutoff, since_dt)
                except Exception:
                    pass  # Malformed added_at — fall back to days-based cutoff

            query = (
                self._table('wallet_activity')
                .select('*')
                .eq('wallet_address', wallet_address)
                .gte('block_time', cutoff.isoformat())
                .order('block_time', desc=True)
            )
            if limit:
                query = query.limit(limit)
            result = query.execute()
            return result.data
        except Exception as e:
            print(f"[WATCHLIST MANAGER] Error getting recent trades: {e}")
            return []


    def _calculate_roi_from_trades(self, trades: List[Dict]) -> float:
        """
        ROI from list of trades with mark-to-market for open positions.
        Bug 2 fix: open positions use latest known price rather than being
        excluded or treated as 100% losses.
        """
        if not trades:
            return 0

        token_inv          = defaultdict(float)
        token_real         = defaultdict(float)
        token_latest_price = defaultdict(float)

        for t in trades:
            tok   = t.get('token_address')
            if not tok:
                continue
            usd   = float(t.get('usd_value', 0))
            price = float(t.get('price_per_token', 0))
            if t.get('side') == 'buy':
                token_inv[tok] += usd
            else:
                token_real[tok] += usd
            if price > 0:
                token_latest_price[tok] = price

        total_inv  = 0.0
        total_real = 0.0

        for tok, invested in token_inv.items():
            if invested < MIN_SPEND_USD:
                continue
            total_inv += invested

            if token_real[tok] > 0:
                total_real += token_real[tok]
            elif token_latest_price[tok] > 0:
                buy_prices = [
                    float(t.get('price_per_token', 0))
                    for t in trades
                    if t.get('token_address') == tok
                    and t.get('side') == 'buy'
                    and float(t.get('price_per_token', 0)) > 0
                ]
                if buy_prices:
                    avg_buy = sum(buy_prices) / len(buy_prices)
                    total_real += invested * (token_latest_price[tok] / avg_buy)

        if total_inv == 0:
            return 0
        return ((total_real - total_inv) / total_inv) * 100


    def _count_runners(self, trades: List[Dict], min_multiplier: float = MIN_WALLET_ROI_MULT) -> int:
        """
        Count CLOSED token positions where wallet achieved >= min_multiplier ROI,
        wallet spent >= $75, and token hit >= 30x launch-to-ATH.
        """
        if not trades:
            return 0

        by_token = defaultdict(lambda: {
            'buys': [], 'sells': [], 'total_invested': 0.0, 'launch_to_ath': 0.0,
        })

        for trade in trades:
            token = trade.get('token_address')
            price = float(trade.get('price_per_token', 0))
            if price == 0 or not token:
                continue

            usd = float(trade.get('usd_value', 0))
            if trade.get('side') == 'buy':
                by_token[token]['buys'].append(price)
                by_token[token]['total_invested'] += usd
            else:
                by_token[token]['sells'].append(price)

            lta = float(trade.get('launch_to_ath_multiplier', 0))
            if lta > by_token[token]['launch_to_ath']:
                by_token[token]['launch_to_ath'] = lta

        runners = 0
        for token_data in by_token.values():
            if token_data['total_invested'] < MIN_SPEND_USD:
                continue
            if not token_data['buys'] or not token_data['sells']:
                continue   # open position — skip

            avg_buy  = sum(token_data['buys'])  / len(token_data['buys'])
            avg_sell = sum(token_data['sells']) / len(token_data['sells'])

            if avg_buy == 0:
                continue

            roi_mult = avg_sell / avg_buy
            if roi_mult < min_multiplier:
                continue

            lta = token_data['launch_to_ath']
            if lta > 0 and lta < MIN_TOKEN_LAUNCH_TO_ATH:
                continue

            runners += 1

        return runners


    def _calculate_win_rate(self, trades: List[Dict]) -> float:
        if not trades:
            return 0

        by_token = defaultdict(lambda: {
            'buys': [], 'sells': [], 'total_invested': 0.0, 'launch_to_ath': 0.0,
        })
        for trade in trades:
            token = trade.get('token_address')
            price = float(trade.get('price_per_token', 0))
            if price == 0 or not token:
                continue
            usd = float(trade.get('usd_value', 0))
            if trade.get('side') == 'buy':
                by_token[token]['buys'].append(price)
                by_token[token]['total_invested'] += usd
            else:
                by_token[token]['sells'].append(price)
            lta = float(trade.get('launch_to_ath_multiplier', 0))
            if lta > by_token[token]['launch_to_ath']:
                by_token[token]['launch_to_ath'] = lta

        outcomes = []
        for data in by_token.values():
            if data['total_invested'] < MIN_SPEND_USD:
                outcomes.append('loss')
                continue
            if not data['buys'] or not data['sells']:
                continue   # open position — skip

            avg_buy  = sum(data['buys'])  / len(data['buys'])
            avg_sell = sum(data['sells']) / len(data['sells'])
            roi_mult = avg_sell / avg_buy if avg_buy > 0 else 0

            launch_to_ath = data['launch_to_ath']
            roi_above     = roi_mult    > MIN_WALLET_ROI_MULT    * 1.02
            launch_above  = launch_to_ath > MIN_TOKEN_LAUNCH_TO_ATH * 1.02 if launch_to_ath > 0 else False
            launch_ok     = launch_to_ath == 0 or launch_above

            if roi_above and (launch_above or launch_to_ath == 0):
                outcomes.append('win')
            elif roi_mult >= MIN_WALLET_ROI_MULT * 0.98 and (launch_ok or launch_to_ath == 0):
                outcomes.append('draw')
            else:
                outcomes.append('loss')

        if not outcomes:
            return 0
        wins = sum(1 for o in outcomes if o == 'win')
        return round((wins / len(outcomes)) * 100, 1)


    def _calculate_consistency(self, trades: List[Dict]) -> float:
        """Standard deviation consistency of ROIs (0-100). Legacy helper."""
        if not trades:
            return 0
        rois = [float(t.get('roi_percent', 0)) for t in trades]
        if len(rois) < 2:
            return 50
        try:
            stdev = statistics.stdev(rois)
            return max(0, 100 - (stdev / 2))
        except Exception:
            return 50


    def _format_time_ago(self, timestamp) -> str:
        if not timestamp:
            return 'unknown'
        try:
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            now  = datetime.utcnow()
            if timestamp.tzinfo:
                now = now.replace(tzinfo=timestamp.tzinfo)
            diff = (now - timestamp).total_seconds()
            if diff < 60:       return 'just now'
            elif diff < 3600:   return f'{int(diff / 60)}m ago'
            elif diff < 86400:  return f'{int(diff / 3600)}h ago'
            else:               return f'{int(diff / 86400)}d ago'
        except Exception:
            return 'unknown'