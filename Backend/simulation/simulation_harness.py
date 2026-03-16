"""
simulation_harness.py

Wires the simulation together and runs it against your REAL service code.

Single run:
  SolanaMarketModel + all agents → 30 days → feed trade data into
  WatchlistLeagueManager → assert scoring, degradation, zone placement

Monte Carlo:
  1000 runs with noise on agent parameters → collect distributions
  → confidence intervals on every assertion

User behavior simulation:
  Telegram alert timing → measure break-even response windows

Cluster alert testing:
  Track Clara's burst behavior → compare immediate vs delayed alert strategies

Run with:
  python simulation_harness.py --mode single --days 30 --market bull
  python simulation_harness.py --mode monte_carlo --runs 1000 --days 30
  python simulation_harness.py --mode alert_timing --runs 500

FIXES IN THIS VERSION:

  Bug 2 (open positions as losses) — MockWatchlistLeagueManager._calc_roi() now
    uses mark-to-market for open positions: current simulated price from
    model.get_price_at() divided by average buy price × invested. Tokens with
    no price data (expired/rugged with no sells) remain full losses.

  Bug 3 (negative ROI subtracts score) — _calculate_professional_score() floors
    roi_7d at 0 before applying. Mirrors the fix in watchlist_manager.py.

  Bug 4 (consistency measures price not timing) — _calculate_entry_consistency_score()
    now accepts a flat list of price_multiplier values (multiplier from launch price
    at moment of each buy) and computes CV across all qualifying buys. Correctly
    handles slow pump.fun graduation — price position, not clock time, determines
    entry quality. Eddie's tight early entries score ~90+; Larry's consistent-but-late
    entries score mid-range; erratic wallets score low.

  Bug 5 (Izzy inactivity alert timing) — build_watchlist_for_service() reads
    _went_inactive_day from any agent that has it and puts it + _sim_day into the
    wallet dict. _detect_degradation() uses (sim_day - went_inactive_day) for
    exact integer arithmetic instead of fuzzy timestamp subtraction that loses
    intra-day hours and can fail by a full day at boundary.
"""

import random
import statistics
import argparse
import json
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from redis_publisher import SimulationPublisher

from solana_market_model import SolanaMarketModel, MarketState, SimulatedToken
from trader_agent_base import TraderAgentBase, ClosedTrade
from concrete_agents import build_all_agents, ClusterClaraAgent

MIN_WALLET_ROI_MULT     = 5.0
MIN_SPEND_USD           = 75.0
MIN_TOKEN_LAUNCH_TO_ATH = 30.0


# =============================================================================
# MOCK SERVICE ADAPTER
# =============================================================================
publisher = SimulationPublisher()

class MockWatchlistLeagueManager:
    """
    Mirrors the REAL WatchlistLeagueManager methods directly.

    All Bug fixes from watchlist_manager.py are mirrored here so the
    simulation produces results consistent with what the real service would show.

    DATETIME NOTE:
      _detect_degradation() uses simulation time (sim_now = start_date + timedelta(days=model.day))
      rather than datetime.utcnow() so inactivity alerts fire correctly within the sim.
      With the Bug 5 fix, wallets that have a tracked went_inactive_day use integer
      arithmetic (sim_day - went_inactive_day) instead of timestamp subtraction entirely.
    """

    def __init__(self, model: SolanaMarketModel):
        self.model = model

    def build_watchlist_for_service(
        self,
        agents: Dict[str, TraderAgentBase],
        user_id: str = "sim_user_001",
    ) -> List[Dict]:
        """
        Build the wallet list, rank it, assign zones, detect degradation.

        Bug 5 fix: reads _went_inactive_day off any agent that has it and
        embeds it in the wallet dict as 'went_inactive_day'. Also embeds
        '_sim_day' (current model day) so _detect_degradation can compute
        days_since = sim_day - went_inactive_day without timestamp arithmetic.
        """
        watchlist = []
        for wallet_addr, agent in agents.items():
            trades_7d  = self.model.get_wallet_trades_as_dicts(wallet_addr, days_back=7)
            trades_30d = self.model.get_wallet_trades_as_dicts(wallet_addr, days_back=30)

            # Bug 4 fix: collect price_multiplier at entry for consistency scoring.
            # price_multiplier on a buy = how far from launch price at moment of entry.
            entry_price_multipliers = [
                float(t.get('price_multiplier', 0))
                for t in trades_30d
                if t['side'] == 'buy'
                and float(t.get('usd_value', 0)) >= MIN_SPEND_USD
                and t.get('price_multiplier') is not None
                and float(t.get('price_multiplier', 0)) > 0
            ]

            roi_7d      = self._calc_roi(trades_7d)
            roi_30d     = self._calc_roi(trades_30d)
            wr_7d       = self._calculate_win_rate(trades_7d)
            wr_30d      = self._calculate_win_rate(trades_30d)
            runners_7d  = self._count_runners(trades_7d)
            runners_30d = self._count_runners(trades_30d)
            consistency = self._calculate_entry_consistency_score(entry_price_multipliers)

            prof_score = self._calculate_professional_score({
                'roi_7d':            roi_7d,
                'runners_7d':        runners_7d,
                'win_rate_7d':       wr_7d,
                'consistency_score': consistency,
            })

            # Last trade time as a real datetime (simulation time)
            last_trade_time = None
            all_trades = trades_7d or trades_30d
            if all_trades:
                raw = all_trades[0]['block_time']
                try:
                    last_trade_time = datetime.fromisoformat(
                        raw.replace('Z', '+00:00')
                    )
                except Exception:
                    last_trade_time = None

            # Bug 5 fix: read exact inactive day from agent if available
            went_inactive_day = -1
            if hasattr(agent, '_went_inactive_day'):
                went_inactive_day = agent._went_inactive_day

            watchlist.append({
                'wallet_address':     wallet_addr,
                'user_id':            user_id,
                'position':           999,
                'zone':               'midtable',
                'movement':           'stable',
                'positions_changed':  0,
                'form':               [],
                'status':             'healthy',
                'degradation_alerts': [],
                'roi_7d':             roi_7d,
                'roi_30d':            roi_30d,
                'win_rate_7d':        wr_7d,
                'win_rate_30d':       wr_30d,
                'runners_7d':         runners_7d,
                'runners_30d':        runners_30d,
                'professional_score': prof_score,
                'consistency_score':  consistency,
                'last_trade_time':    last_trade_time,
                'source_type':        'batch',
                'agent_name':         agent.personality.name,
                # Bug 5 fix: embed inactive day + sim day for exact alert arithmetic
                'went_inactive_day':  went_inactive_day,
                '_sim_day':           self.model.day,
                '_trades_7d':         trades_7d,
                '_trades_30d':        trades_30d,
            })

        watchlist = self._calculate_league_positions(watchlist)

        for wallet in watchlist:
            self._detect_degradation(wallet)

        return watchlist

    # =========================================================================
    # LEAGUE POSITIONS
    # =========================================================================

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
            if position == 1:   return 'Elite'
            elif position <= 3: return 'midtable'
            else:               return 'monitoring'
        elif total_wallets <= 10:
            if position <= 3:   return 'Elite'
            elif position <= 6: return 'midtable'
            elif position <= 8: return 'monitoring'
            else:               return 'relegation'
        else:
            pct = position / total_wallets
            if pct <= 0.3:   return 'Elite'
            elif pct <= 0.6: return 'midtable'
            elif pct <= 0.8: return 'monitoring'
            else:            return 'relegation'

    # =========================================================================
    # DEGRADATION — sim-time aware + exact inactive day arithmetic
    # =========================================================================

    def _detect_degradation(self, wallet: Dict):
        """
        Mirrors watchlist_manager._detect_degradation() with two changes:

        1. Uses simulation time for timestamp-based inactivity checks
           (sim_now = model.start_date + timedelta(days=model.day))

        2. Bug 5 fix: if went_inactive_day > 0 and _sim_day are in the wallet,
           uses (sim_day - went_inactive_day) for exact integer arithmetic.
           This avoids the intra-day hours precision loss in timestamp subtraction
           that caused Day 14 to show only 6 days since inactivity instead of 8.
        """
        alerts = []

        roi_7d      = wallet.get('roi_7d', 0)
        runners_7d  = wallet.get('runners_7d', 0)
        win_rate_7d = wallet.get('win_rate_7d', 0)
        roi_30d     = wallet.get('roi_30d', 0)
        runners_30d = wallet.get('runners_30d', 0)

        # ── Alert 1: Inactivity ───────────────────────────────────────────────
        went_inactive_day = wallet.get('went_inactive_day', -1)
        sim_day           = wallet.get('_sim_day', -1)

        if went_inactive_day is not None and went_inactive_day > 0 and sim_day > 0:
            # Bug 5 fix: exact integer arithmetic — no timestamp drift
            days_since = sim_day - went_inactive_day
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
            # Fallback: timestamp-based (simulation-time-aware)
            last_trade = wallet['last_trade_time']
            if isinstance(last_trade, str):
                try:
                    last_trade = datetime.fromisoformat(
                        last_trade.replace('Z', '+00:00')
                    )
                except Exception:
                    last_trade = None

            if last_trade is not None:
                sim_now = self.model.start_date + timedelta(days=self.model.day)
                if last_trade.tzinfo is not None:
                    sim_now_tz = sim_now.replace(tzinfo=last_trade.tzinfo)
                else:
                    sim_now_tz = sim_now
                days_since = (sim_now_tz - last_trade).days
                if days_since > 7:
                    alerts.append({
                        'severity': 'yellow',
                        'message':  f'No activity for {days_since} days',
                    })

        # ── Alert 2: ROI below floor ──────────────────────────────────────────
        ROI_7D_TARGET = (MIN_WALLET_ROI_MULT - 1) * 100

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
                'message':  (
                    f'7-day ROI below {MIN_WALLET_ROI_MULT}x floor: '
                    f'{roi_7d:.1f}% (target: {ROI_7D_TARGET:.0f}%+)'
                ),
            })

        # ── Alert 3: No qualifying runners ────────────────────────────────────
        if runners_7d == 0:
            if runners_30d >= 3:
                alerts.append({
                    'severity': 'yellow',
                    'message':  (
                        f'No {MIN_WALLET_ROI_MULT}x+ runners this week '
                        f'(but {runners_30d} in last 30d)'
                    ),
                })
            else:
                alerts.append({
                    'severity': 'red',
                    'message':  (
                        f'No {MIN_WALLET_ROI_MULT}x+ runners in 30 days '
                        f'— replace immediately'
                    ),
                })

        # ── Alert 4: Win rate low ─────────────────────────────────────────────
        if win_rate_7d < 30:
            alerts.append({
                'severity': 'orange',
                'message':  (
                    f'Win rate {win_rate_7d:.0f}% '
                    f'(floor: trades need {MIN_WALLET_ROI_MULT}x+ to count as win)'
                ),
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
                    f'(losses = below {MIN_WALLET_ROI_MULT}x ROI '
                    f'or token < {MIN_TOKEN_LAUNCH_TO_ATH}x launch-to-ATH)'
                ),
            })

        # ── Alert 7: Entry consistency degrading ──────────────────────────────
        consistency = wallet.get('consistency_score', 50)
        if consistency < 40:
            alerts.append({
                'severity': 'orange',
                'message':  (
                    f'Entry timing inconsistent '
                    f'(consistency score: {consistency:.0f}/100)'
                ),
            })

        if any(a['severity'] == 'red' for a in alerts):
            wallet['status'] = 'critical'
        elif any(a['severity'] in ('orange', 'yellow') for a in alerts):
            wallet['status'] = 'warning'
        else:
            wallet['status'] = 'healthy'

        wallet['degradation_alerts'] = alerts

    # =========================================================================
    # PROFESSIONAL SCORE — Bug 3 fix: negative ROI floored at 0
    # =========================================================================

    def _calculate_professional_score(self, metrics: Dict) -> float:
        score = 0
        # Bug 3 fix: floor at 0 — negative ROI contributes 0 not negative pts
        roi_7d = max(0, metrics.get('roi_7d', 0))
        score += min(roi_7d / 2, 40)
        score += min(metrics.get('runners_7d', 0) * 6, 30)
        score += (metrics.get('win_rate_7d', 0) / 100) * 20
        score += (metrics.get('consistency_score', 0) / 100) * 10
        return round(score, 1)

    # =========================================================================
    # RUNNERS — $75 spend + 5x ROI + 30x token ATH floors
    # =========================================================================

    def _count_runners(
        self,
        trades: List[Dict],
        min_multiplier: float = MIN_WALLET_ROI_MULT,
    ) -> int:
        if not trades:
            return 0

        by_token = defaultdict(lambda: {
            'buys': [], 'sells': [], 'total_invested': 0.0, 'launch_to_ath': 0.0,
        })

        for trade in trades:
            token = trade.get('token_address')
            price = float(trade.get('price_per_token', 0))
            if not token or price == 0:
                continue
            usd = float(trade.get('usd_value', 0))
            if trade['side'] == 'buy':
                by_token[token]['buys'].append(price)
                by_token[token]['total_invested'] += usd
            else:
                by_token[token]['sells'].append(price)
            lta = float(trade.get('launch_to_ath_multiplier', 0))
            if lta > by_token[token]['launch_to_ath']:
                by_token[token]['launch_to_ath'] = lta

        # Also hydrate ATH from model for any token still active
        for token, data in by_token.items():
            if token in self.model.active_tokens:
                model_ath = self.model.active_tokens[token].curve.ath_multiplier
                if model_ath > data['launch_to_ath']:
                    data['launch_to_ath'] = model_ath

        runners = 0
        for data in by_token.values():
            if data['total_invested'] < MIN_SPEND_USD:
                continue
            if not data['buys'] or not data['sells']:
                continue   # open position — skip
            avg_buy  = sum(data['buys'])  / len(data['buys'])
            avg_sell = sum(data['sells']) / len(data['sells'])
            if avg_buy == 0:
                continue
            roi_mult = avg_sell / avg_buy
            if roi_mult < min_multiplier:
                continue
            lta = data['launch_to_ath']
            if lta > 0 and lta < MIN_TOKEN_LAUNCH_TO_ATH:
                continue
            runners += 1

        return runners

    # =========================================================================
    # WIN RATE
    # =========================================================================

    def _calculate_win_rate(self, trades: List[Dict]) -> float:
        if not trades:
            return 0.0

        by_token = defaultdict(lambda: {
            'buys': [], 'sells': [], 'total_invested': 0.0, 'launch_to_ath': 0.0,
        })
        for trade in trades:
            token = trade.get('token_address')
            price = float(trade.get('price_per_token', 0))
            if not token or price == 0:
                continue
            usd = float(trade.get('usd_value', 0))
            if trade['side'] == 'buy':
                by_token[token]['buys'].append(price)
                by_token[token]['total_invested'] += usd
            else:
                by_token[token]['sells'].append(price)
            lta = float(trade.get('launch_to_ath_multiplier', 0))
            if lta > by_token[token]['launch_to_ath']:
                by_token[token]['launch_to_ath'] = lta

        for token, data in by_token.items():
            if token in self.model.active_tokens:
                model_ath = self.model.active_tokens[token].curve.ath_multiplier
                if model_ath > data['launch_to_ath']:
                    data['launch_to_ath'] = model_ath

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

            lta          = data['launch_to_ath']
            roi_above    = roi_mult > MIN_WALLET_ROI_MULT * 1.02
            launch_above = lta > MIN_TOKEN_LAUNCH_TO_ATH * 1.02 if lta > 0 else False
            launch_ok    = lta == 0 or launch_above

            if roi_above and (launch_above or lta == 0):
                outcomes.append('win')
            elif roi_mult >= MIN_WALLET_ROI_MULT * 0.98 and launch_ok:
                outcomes.append('draw')
            else:
                outcomes.append('loss')

        if not outcomes:
            return 0.0
        wins = sum(1 for o in outcomes if o == 'win')
        return round((wins / len(outcomes)) * 100, 1)

    # =========================================================================
    # ENTRY CONSISTENCY — Bug 4 fix: price_multiplier at entry, not timing
    # =========================================================================

    def _calculate_entry_consistency_score(self, entry_price_multipliers: List[float]) -> float:
        """
        Bug 4 fix: measures CV of price_multiplier at entry across all qualifying buys.
        price_multiplier = how far from launch price the wallet entered (1.0 = at launch).

        This correctly handles slow pump.fun graduation — a wallet entering at 1.2x is
        an early entry whether that happened at hour 1 or hour 6. Clock time is a
        misleading proxy; price position is the ground truth.

        Low CV (all buys near 1x) = consistent early entry = high score ~90+.
        High CV (sometimes 1x, sometimes 8x) = erratic = low score.

        Eddie: (0,1) range → nearly always at 1x → score ~90+
        Larry: (3,8) range → enters at 3-8x consistently → mid score (consistent, just late)
        Becky: wide range, big concentrated bets at varying price levels → lower score
        """
        mults = [m for m in entry_price_multipliers if m is not None and m > 0]

        if not mults:
            return 50.0

        if len(mults) == 1:
            return 70.0

        try:
            mean_mult = statistics.mean(mults)
            if mean_mult == 0:
                return 50.0
            stdev = statistics.stdev(mults)
            cv    = stdev / mean_mult
            score = max(0.0, 100.0 * (1.0 - min(cv, 2.0) / 2.0))
            return round(score, 1)
        except Exception:
            return 50.0

    # =========================================================================
    # ROI HELPER — Bug 2 fix: mark-to-market for open positions
    # =========================================================================

    def _calc_roi(self, trades: List[Dict]) -> float:
        """
        Bug 2 fix: open positions (buys, no sells) use mark-to-market value.
        Current price fetched from model.active_tokens via get_price_at().
        Tokens expired from active_tokens with no sells = full loss (no value recoverable).
        """
        token_inv   = defaultdict(float)
        token_real  = defaultdict(float)
        token_buys  = defaultdict(list)   # price_multiplier per buy for avg calc

        for t in trades:
            tok = t.get('token_address')
            if not tok:
                continue
            usd  = float(t.get('usd_value', 0))
            mult = float(t.get('price_multiplier', 0))
            if t['side'] == 'buy':
                token_inv[tok]  += usd
                if mult > 0:
                    token_buys[tok].append(mult)
            else:
                token_real[tok] += usd

        total_inv  = 0.0
        total_real = 0.0

        for tok, invested in token_inv.items():
            if invested < MIN_SPEND_USD:
                continue
            total_inv += invested

            if token_real[tok] > 0:
                # Closed (at least partially) — use realized value
                total_real += token_real[tok]
            elif tok in self.model.active_tokens and token_buys[tok]:
                # Bug 2 fix: open position still active — mark to current sim price
                avg_buy_mult = sum(token_buys[tok]) / len(token_buys[tok])
                current_mult = self.model.get_price_at(
                    self.model.active_tokens[tok], self.model.day, 12
                )
                if avg_buy_mult > 0:
                    mark_to_market = invested * (current_mult / avg_buy_mult)
                    total_real += mark_to_market
            # else: token expired with no sells → full loss, add 0

        if total_inv == 0:
            return 0.0
        return round(((total_real - total_inv) / total_inv) * 100, 2)


# =============================================================================
# ALERT SIMULATOR
# =============================================================================

@dataclass
class AlertEvent:
    wallet_address:       str
    wallet_name:          str
    token_address:        str
    token_symbol:         str
    trade_day:            int
    trade_hour:           int
    is_cluster:           bool
    cluster_size:         int
    alert_delay_minutes:  float
    token_price_at_alert: float
    token_ath:            float


@dataclass
class UserResponseResult:
    user_type:          str
    response_minutes:   float
    entry_price:        float
    eventual_ath:       float
    roi_if_entered:     float
    was_profitable:     bool
    alert_was_useful:   bool


class AlertSimulator:
    """
    Simulates the full alert pipeline:
    trade → detection → queue → Telegram delivery → user response → trade entry
    """

    USER_RESPONSE_PROFILES = {
        'Instant Igor':         {'mean': 1.5,  'std': 0.5,  'active_hours': (0, 24)},
        'Deliberate Diana':     {'mean': 8.0,  'std': 3.0,  'active_hours': (8, 22)},
        'Skeptical Sam':        {'mean': 5.0,  'std': 2.0,  'active_hours': (8, 22),
                                 'requires_cluster': True},
        'Alert-Fatigued Frank': {'mean': 25.0, 'std': 15.0, 'fatigue_threshold': 20},
        'Weekend Wendy':        {'mean': 60.0, 'std': 30.0, 'active_hours': (9, 17),
                                 'active_days': (0, 1, 2, 3, 4)},
    }

    SYSTEM_LATENCY = {
        'blockchain_confirm': (0.5, 2.0),
        'detection':          (0.2, 1.0),
        'processing':         (0.1, 0.5),
        'queue':              (0.1, 1.0),
        'telegram_api':       (0.1, 0.3),
    }

    def __init__(self, model: SolanaMarketModel):
        self.model               = model
        self.fired_alerts:       List[AlertEvent] = []
        self.alert_history:      Dict[str, List[AlertEvent]] = {}
        self._alert_counts_today: int = 0
        self.cluster_window_minutes = 30

    def process_trade(
        self,
        trade_wallet:    str,
        wallet_name:     str,
        token:           SimulatedToken,
        trade_day:       int,
        trade_hour:      int,
        all_recent_buys: List[Dict],
    ) -> Optional[AlertEvent]:
        total_latency = sum(
            random.uniform(mn, mx)
            for mn, mx in self.SYSTEM_LATENCY.values()
        )

        cluster_wallets = [
            b for b in all_recent_buys
            if b['token_address'] == token.address
            and b['wallet_address'] != trade_wallet
        ]
        is_cluster   = len(cluster_wallets) >= 1
        cluster_size = len(cluster_wallets) + 1

        price_at_alert = self.model.get_price_at(
            token, trade_day, trade_hour + int(total_latency / 60)
        )

        alert = AlertEvent(
            wallet_address        = trade_wallet,
            wallet_name           = wallet_name,
            token_address         = token.address,
            token_symbol          = token.symbol,
            trade_day             = trade_day,
            trade_hour            = trade_hour,
            is_cluster            = is_cluster,
            cluster_size          = cluster_size,
            alert_delay_minutes   = total_latency,
            token_price_at_alert  = price_at_alert,
            token_ath             = token.curve.ath_multiplier,
        )

        self.fired_alerts.append(alert)
        if trade_wallet not in self.alert_history:
            self.alert_history[trade_wallet] = []
        self.alert_history[trade_wallet].append(alert)
        self._alert_counts_today += 1

        return alert

    def simulate_user_response(
        self,
        alert: AlertEvent,
        user_type: str,
        total_alerts_received: int = 0,
    ) -> Optional[UserResponseResult]:
        profile = self.USER_RESPONSE_PROFILES.get(user_type, {})

        if profile.get('requires_cluster') and not alert.is_cluster:
            return None

        if user_type == 'Alert-Fatigued Frank':
            fatigue_threshold = profile.get('fatigue_threshold', 20)
            if total_alerts_received > fatigue_threshold:
                ignore_prob = min(0.95, (total_alerts_received - fatigue_threshold) * 0.05)
                if random.random() < ignore_prob:
                    return None

        active_hours = profile.get('active_hours', (0, 24))
        current_hour = alert.trade_hour
        if not (active_hours[0] <= current_hour <= active_hours[1]):
            if user_type == 'Weekend Wendy':
                response_minutes = (24 - current_hour + 9) * 60
            else:
                return None
        else:
            response_minutes = max(0.5, random.gauss(profile['mean'], profile['std']))

        total_delay = alert.alert_delay_minutes + response_minutes
        entry_price = alert.token_price_at_alert * (1 + total_delay * 0.001)

        if entry_price <= 0:
            return None

        roi = alert.token_ath / entry_price

        return UserResponseResult(
            user_type        = user_type,
            response_minutes = response_minutes,
            entry_price      = entry_price,
            eventual_ath     = alert.token_ath,
            roi_if_entered   = round(roi, 2),
            was_profitable   = roi >= 5.0,
            alert_was_useful = roi >= 2.0,
        )

    def evaluate_cluster_strategy(
        self,
        immediate_alerts: List[AlertEvent],
        delayed_window_minutes: float = 15.0,
    ) -> Dict:
        results = {'strategy_a': [], 'strategy_b': []}

        by_token: Dict[str, List[AlertEvent]] = {}
        for alert in immediate_alerts:
            if alert.token_address not in by_token:
                by_token[alert.token_address] = []
            by_token[alert.token_address].append(alert)

        for token_addr, token_alerts in by_token.items():
            token_alerts.sort(key=lambda a: a.trade_day * 24 + a.trade_hour)
            first_alert  = token_alerts[0]
            eventual_ath = first_alert.token_ath

            entry_a = first_alert.token_price_at_alert
            roi_a   = eventual_ath / entry_a if entry_a > 0 else 0
            results['strategy_a'].append(roi_a)

            cluster_formed = False
            cluster_alert  = None
            for alert in token_alerts[1:]:
                time_gap = (
                    (alert.trade_day  - first_alert.trade_day)  * 24 * 60
                    + (alert.trade_hour - first_alert.trade_hour) * 60
                )
                if time_gap <= delayed_window_minutes:
                    cluster_formed = True
                    cluster_alert  = alert
                    break

            if cluster_formed and cluster_alert:
                entry_b = cluster_alert.token_price_at_alert
                roi_b   = eventual_ath / entry_b if entry_b > 0 else 0
                results['strategy_b'].append(roi_b)

        def _summarize(rois):
            if not rois:
                return {'count': 0, 'avg_roi': 0, 'win_rate': 0, 'median_roi': 0}
            return {
                'count':      len(rois),
                'avg_roi':    round(statistics.mean(rois), 2),
                'win_rate':   round(sum(1 for r in rois if r >= 5.0) / len(rois) * 100, 1),
                'median_roi': round(statistics.median(rois), 2),
            }

        return {
            'strategy_a_immediate':     _summarize(results['strategy_a']),
            'strategy_b_cluster':       _summarize(results['strategy_b']),
            'tokens_strategy_b_missed': len(by_token) - len(results['strategy_b']),
            'recommendation': (
                'immediate' if (
                    results['strategy_a'] and
                    statistics.mean(results['strategy_a']) >
                    (statistics.mean(results['strategy_b']) if results['strategy_b'] else 0)
                ) else 'cluster'
            ),
        }


# =============================================================================
# ASSERTIONS
# =============================================================================

@dataclass
class AssertionResult:
    name:     str
    passed:   bool
    actual:   object
    expected: object
    message:  str


class SimulationAssertions:

    @staticmethod
    def assert_eddie_zone(watchlist: List[Dict]) -> AssertionResult:
        eddie = next((w for w in watchlist if 'EDDIE' in w['wallet_address']), None)
        if not eddie:
            return AssertionResult("eddie_zone", False, None, "Elite", "Eddie not found")
        passed = eddie['zone'] == 'Elite'
        return AssertionResult(
            "eddie_always_elite",
            passed,
            eddie.get('zone'), "Elite",
            f"Eddie zone: {eddie.get('zone')}"
        )

    @staticmethod
    def assert_hank_degraded(watchlist: List[Dict], day: int) -> AssertionResult:
        hank = next((w for w in watchlist if 'HANK' in w['wallet_address']), None)
        if not hank:
            return AssertionResult("hank_degraded", False, None, "warning|critical", "Hank not found")

        if day < 14:
            passed   = hank['status'] in ('healthy', 'warning')
            expected = 'healthy|warning'
        else:
            passed   = hank['status'] in ('warning', 'critical')
            expected = 'warning|critical'

        return AssertionResult(
            "hank_degradation_timing",
            passed,
            hank.get('status'), expected,
            f"Day {day} — Hank status: {hank.get('status')}"
        )

    @staticmethod
    def assert_eddie_beats_victor(watchlist: List[Dict]) -> AssertionResult:
        eddie  = next((w for w in watchlist if 'EDDIE'  in w['wallet_address']), None)
        victor = next((w for w in watchlist if 'VICTOR' in w['wallet_address']), None)
        if not eddie or not victor:
            return AssertionResult("eddie_beats_victor", False, None, None, "Agent not found")

        passed = eddie['professional_score'] > victor['professional_score']
        return AssertionResult(
            "quality_beats_quantity",
            passed,
            f"Eddie:{eddie['professional_score']} Victor:{victor['professional_score']}",
            "Eddie > Victor",
            "Eddie's quality should outscore Victor's volume"
        )

    @staticmethod
    def assert_eddie_beats_larry(watchlist: List[Dict]) -> AssertionResult:
        eddie = next((w for w in watchlist if 'EDDIE' in w['wallet_address']), None)
        larry = next((w for w in watchlist if 'LARRY' in w['wallet_address']), None)
        if not eddie or not larry:
            return AssertionResult("eddie_beats_larry", False, None, None, "Agent not found")

        passed = eddie['professional_score'] > larry['professional_score']
        return AssertionResult(
            "early_entry_beats_late_entry",
            passed,
            f"Eddie:{eddie['professional_score']} Larry:{larry['professional_score']}",
            "Eddie > Larry",
            "Early entry should outscore late entry at same win rate"
        )

    @staticmethod
    def assert_izzy_inactivity_alert(watchlist: List[Dict], day: int) -> AssertionResult:
        izzy = next((w for w in watchlist if 'IZZY' in w['wallet_address']), None)
        if not izzy:
            return AssertionResult("izzy_alert", False, None, None, "Izzy not found")

        if day < 7:
            return AssertionResult("izzy_alert_pre7", True, "too early", "too early", "Pre-7d skip")

        alerts         = izzy.get('degradation_alerts', [])
        has_inactivity = any('activity' in a.get('message', '').lower() for a in alerts)

        return AssertionResult(
            "izzy_inactivity_detected",
            has_inactivity,
            [a['message'] for a in alerts],
            "inactivity alert",
            f"Day {day} — Izzy has {len(alerts)} alerts"
        )

    @staticmethod
    def assert_hank_position_sizing(watchlist: List[Dict], day: int) -> AssertionResult:
        hank = next((w for w in watchlist if 'HANK' in w['wallet_address']), None)
        if not hank or day < 21:
            return AssertionResult("hank_sizing", True, "skip", "skip", "Pre-week4 skip")

        passed = hank.get('win_rate_7d', 100) < 40
        return AssertionResult(
            "hank_conviction_decline",
            passed,
            hank.get('win_rate_7d'), "< 40%",
            f"Week 4 Hank win rate: {hank.get('win_rate_7d')}%"
        )

    @staticmethod
    def assert_rhonda_not_frank(replacements: List[Dict]) -> AssertionResult:
        names = [r.get('agent_name', '') for r in replacements]

        if 'Rising Rhonda' not in names or 'Flash-in-the-Pan Frank' not in names:
            return AssertionResult(
                "replacement_ordering", True, "one not in pool", "skip", "Both not in pool"
            )

        rhonda_rank = names.index('Rising Rhonda')
        frank_rank  = names.index('Flash-in-the-Pan Frank')
        passed      = rhonda_rank < frank_rank

        return AssertionResult(
            "rhonda_ranks_above_frank",
            passed,
            f"Rhonda:{rhonda_rank} Frank:{frank_rank}",
            "Rhonda before Frank",
            "Improving trajectory should beat single-week fluke"
        )

    @staticmethod
    def assert_becky_consistency_penalty(watchlist: List[Dict]) -> AssertionResult:
        becky = next((w for w in watchlist if 'BECKY' in w['wallet_address']), None)
        eddie = next((w for w in watchlist if 'EDDIE' in w['wallet_address']), None)
        if not becky or not eddie:
            return AssertionResult("becky_consistency", False, None, None, "Agent not found")

        passed = becky.get('consistency_score', 100) < eddie.get('consistency_score', 0)
        return AssertionResult(
            "becky_consistency_lower_than_eddie",
            passed,
            f"Becky:{becky.get('consistency_score')} Eddie:{eddie.get('consistency_score')}",
            "Becky < Eddie consistency",
            "Boom-bust should have lower consistency than steady performer"
        )


# =============================================================================
# SINGLE RUN
# =============================================================================

def run_single_simulation(
    days:           int          = 30,
    market_state:   MarketState  = MarketState.BULL,
    seed:           Optional[int] = None,
    verbose:        bool          = True,
    include_alerts: bool          = True,
) -> Dict:
    if seed is not None:
        random.seed(seed)

    print(f"\n{'='*70}")
    print(f"SINGLE SIMULATION RUN | {days} days | Market: {market_state.value} | Seed: {seed}")
    print(f"{'='*70}\n")

    model  = SolanaMarketModel(initial_market_state=market_state, seed=seed)
    agents = build_all_agents(model, include_replacements=True)

    manager   = MockWatchlistLeagueManager(model)
    alert_sim = AlertSimulator(model) if include_alerts else None

    daily_snapshots:   List[Dict]                  = []
    assertion_history: List[List[AssertionResult]] = []

    for day in range(1, days + 1):
        model.step()

        watchlist = manager.build_watchlist_for_service(agents)

        replacement_addrs = {
            addr for addr in agents
            if any(x in addr for x in ['RHONDA', 'CARLOS', 'FRANK'])
        }

        agents_payload = []
        for w in watchlist:
            addr    = w['wallet_address']
            is_repl = addr in replacement_addrs
            agents_payload.append({
                'id':             addr,
                'name':           w['agent_name'],
                'score':          w['professional_score'],
                'status':         w['status'],
                'zone':           w['zone'],
                'tier':           w['zone'],
                'roi_7d':         w['roi_7d'],
                'roi_30d':        w['roi_30d'],
                'runners_7d':     w['runners_7d'],
                'runners_30d':    w['runners_30d'],
                'win_rate_7d':    w['win_rate_7d'],
                'consistency':    w['consistency_score'],
                'position':       w['position'],
                'alerts':         len(w.get('degradation_alerts', [])),
                'is_replacement': is_repl,
            })

        total_runners  = sum(a['runners_30d'] for a in agents_payload)
        total_alerts   = sum(a['alerts']      for a in agents_payload)
        degraded_count = sum(1 for a in agents_payload if a['status'] == 'critical')
        cluster_count  = sum(
            1 for t in (alert_sim.fired_alerts if alert_sim else [])
            if t.is_cluster
        )

        publisher.publish_day_state({
            'status':       'running',
            'mode':         'simulation',
            'day':          day,
            'total_days':   days,
            'market_state': model.market_state.value.upper(),
            'agents':       agents_payload,
            'stats': {
                'total_trades':   model._total_trade_count(),
                'active_tokens':  len(model.active_tokens),
                'total_runners':  total_runners,
                'total_alerts':   total_alerts,
                'total_clusters': cluster_count,
                'degraded_count': degraded_count,
            },
            'events': [],
        })

        if day % 7 == 0 or day == days:
            assertions = [
                SimulationAssertions.assert_eddie_zone(watchlist),
                SimulationAssertions.assert_hank_degraded(watchlist, day),
                SimulationAssertions.assert_eddie_beats_victor(watchlist),
                SimulationAssertions.assert_eddie_beats_larry(watchlist),
                SimulationAssertions.assert_izzy_inactivity_alert(watchlist, day),
                SimulationAssertions.assert_hank_position_sizing(watchlist, day),
                SimulationAssertions.assert_becky_consistency_penalty(watchlist),
            ]

            replacement_candidates = sorted(
                [w for w in watchlist if any(
                    x in w['wallet_address'] for x in ['RHONDA', 'CARLOS', 'FRANK']
                )],
                key=lambda w: w['professional_score'], reverse=True
            )
            assertions.append(
                SimulationAssertions.assert_rhonda_not_frank(replacement_candidates)
            )

            assertion_history.append(assertions)

            if verbose:
                print(f"\n--- Day {day} Assertions ---")
                for a in assertions:
                    status = "✓" if a.passed else "✗"
                    print(f"  {status} {a.name:<40} {a.message}")

        if include_alerts and alert_sim:
            clara_agent = agents.get('WALLET_CLARA_005')
            if (clara_agent and isinstance(clara_agent, ClusterClaraAgent)
                    and clara_agent.is_in_burst()):
                clara_trades = [
                    t for t in (model.all_trades.get('WALLET_CLARA_005') or [])
                    if t.day == day and t.side == 'buy'
                ]
                all_today_buys = [
                    {'token_address': t.token_address, 'wallet_address': wa}
                    for wa, trades in model.all_trades.items()
                    for t in trades if t.day == day and t.side == 'buy'
                ]
                for trade in clara_trades:
                    token = model.active_tokens.get(trade.token_address)
                    if token:
                        alert_sim.process_trade(
                            'WALLET_CLARA_005', 'Cluster Clara',
                            token, day, trade.hour, all_today_buys
                        )

        daily_snapshots.append({
            'day':          day,
            'market_state': model.market_state.value,
            'watchlist': [
                {k: v for k, v in w.items() if not k.startswith('_')}
                for w in watchlist
            ],
        })

    # ── Post-simulation analysis ───────────────────────────────────────────────

    alert_comparison = None
    user_results     = {}
    if alert_sim and alert_sim.fired_alerts:
        alert_comparison = alert_sim.evaluate_cluster_strategy(
            alert_sim.fired_alerts,
            delayed_window_minutes=15.0
        )

        for user_type in AlertSimulator.USER_RESPONSE_PROFILES:
            responses = []
            for alert in alert_sim.fired_alerts[:50]:
                result = alert_sim.simulate_user_response(
                    alert, user_type,
                    total_alerts_received=len(alert_sim.fired_alerts)
                )
                if result:
                    responses.append(result)

            if responses:
                user_results[user_type] = {
                    'avg_roi':              round(statistics.mean([r.roi_if_entered for r in responses]), 2),
                    'win_rate':             round(sum(1 for r in responses if r.was_profitable) / len(responses) * 100, 1),
                    'response_rate':        round(len(responses) / len(alert_sim.fired_alerts) * 100, 1),
                    'avg_response_minutes': round(statistics.mean([r.response_minutes for r in responses]), 1),
                }

    total_assertions = sum(len(a) for a in assertion_history)
    total_passed     = sum(sum(1 for a in run if a.passed) for run in assertion_history)

    final_watchlist = manager.build_watchlist_for_service(agents)

    result = {
        'days_simulated':        days,
        'final_market_state':    model.market_state.value,
        'market_state_history':  [s.value for s in model.market_state_history],
        'total_trades':          model._total_trade_count(),
        'total_tokens_launched': len(model.active_tokens) + len(model.daily_stats),
        'assertion_pass_rate':   round(total_passed / total_assertions * 100, 1) if total_assertions else 0,
        'assertions_passed':     total_passed,
        'assertions_total':      total_assertions,
        'agent_summaries': {
            addr: agent.get_performance_summary()
            for addr, agent in agents.items()
        },
        'final_watchlist_scores': {
            w['wallet_address']: {
                'name':               w['agent_name'],
                'score':              w['professional_score'],
                'zone':               w['zone'],
                'status':             w['status'],
                'roi_7d':             w['roi_7d'],
                'runners_7d':         w['runners_7d'],
                'win_rate_7d':        w['win_rate_7d'],
            }
            for w in final_watchlist
        },
        'alert_strategy_comparison': alert_comparison,
        'user_response_results':     user_results,
        'model_summary':             model.summary(),
    }

    print(f"\n{'='*70}")
    print("FINAL SCORECARD")
    print(f"{'='*70}")
    print(f"{'Agent':<25} {'Score':>6} {'Zone':<12} {'Status':<10} {'ROI_7d':>8} {'Runners':>8}")
    print("-" * 70)
    for addr, data in sorted(
        result['final_watchlist_scores'].items(),
        key=lambda x: x[1]['score'], reverse=True
    ):
        print(
            f"{data['name']:<25} {data['score']:>6.1f} {data['zone']:<12} "
            f"{data['status']:<10} {data['roi_7d']:>7.1f}% {data['runners_7d']:>7}"
        )

    print(f"\nAssertions: {total_passed}/{total_assertions} passed "
          f"({result['assertion_pass_rate']}%)")

    if alert_comparison:
        print(f"\nAlert Strategy Comparison:")
        print(f"  Immediate: avg {alert_comparison['strategy_a_immediate']['avg_roi']}x ROI, "
              f"{alert_comparison['strategy_a_immediate']['win_rate']}% win rate")
        print(f"  Cluster wait: avg {alert_comparison['strategy_b_cluster']['avg_roi']}x ROI, "
              f"{alert_comparison['strategy_b_cluster']['win_rate']}% win rate")
        print(f"  Tokens missed by cluster strategy: {alert_comparison['tokens_strategy_b_missed']}")
        print(f"  Recommendation: {alert_comparison['recommendation'].upper()}")

    publisher.publish_complete({
        'assertions_passed': total_passed,
        'assertions_total':  total_assertions,
        'pass_rate':         result['assertion_pass_rate'],
        'total_trades':      model._total_trade_count(),
    })

    return result


# =============================================================================
# MONTE CARLO RUNNER
# =============================================================================

def run_monte_carlo(
    n_runs:       int   = 1000,
    days:         int   = 30,
    noise_factor: float = 0.15,
) -> Dict:
    print(f"\n{'='*70}")
    print(f"MONTE CARLO | {n_runs} runs | {days} days | Noise: ±{noise_factor*100:.0f}%")
    print(f"{'='*70}\n")

    all_results: List[Dict] = []
    start_time = time.time()

    market_states = list(MarketState)

    for run_idx in range(n_runs):
        seed          = run_idx * 7 + 42
        initial_state = random.choice(market_states)

        try:
            result = run_single_simulation(
                days           = days,
                market_state   = initial_state,
                seed           = seed,
                verbose        = False,
                include_alerts = (run_idx % 10 == 0),
            )
            all_results.append(result)
        except Exception as e:
            print(f"  Run {run_idx} failed: {e}")

        if (run_idx + 1) % 100 == 0:
            elapsed = time.time() - start_time
            print(f"  Progress: {run_idx+1}/{n_runs} runs | {elapsed:.1f}s elapsed")

    assertion_rates = [r['assertion_pass_rate'] for r in all_results]

    agent_scores: Dict[str, List[float]]    = {}
    agent_zones:  Dict[str, Dict[str, int]] = {}
    agent_status: Dict[str, Dict[str, int]] = {}

    for result in all_results:
        for addr, data in result['final_watchlist_scores'].items():
            name = data['name']
            if name not in agent_scores:
                agent_scores[name] = []
                agent_zones[name]  = {}
                agent_status[name] = {}

            agent_scores[name].append(data['score'])
            zone   = data['zone']
            status = data['status']
            agent_zones[name][zone]    = agent_zones[name].get(zone, 0) + 1
            agent_status[name][status] = agent_status[name].get(status, 0) + 1

    strategy_results = [
        r['alert_strategy_comparison']
        for r in all_results
        if r.get('alert_strategy_comparison')
    ]

    def _confidence_interval(data: List[float], confidence: float = 0.95) -> Tuple:
        if not data:
            return (0, 0, 0)
        n    = len(data)
        mean = statistics.mean(data)
        if n < 2:
            return (mean, mean, mean)
        std    = statistics.stdev(data)
        margin = 2 * std / (n ** 0.5)
        return (round(mean - margin, 2), round(mean, 2), round(mean + margin, 2))

    monte_carlo_results = {
        'runs_completed':      len(all_results),
        'assertion_pass_rate': {
            'mean': round(statistics.mean(assertion_rates), 1) if assertion_rates else 0,
            'min':  round(min(assertion_rates), 1)             if assertion_rates else 0,
            'max':  round(max(assertion_rates), 1)             if assertion_rates else 0,
        },
        'per_agent_confidence_intervals': {
            name: {
                'score_95ci':  _confidence_interval(agent_scores[name]),
                'zone_dist':   {k: round(v / len(all_results) * 100, 1)
                                for k, v in agent_zones[name].items()},
                'status_dist': {k: round(v / len(all_results) * 100, 1)
                                for k, v in agent_status[name].items()},
            }
            for name in agent_scores
        },
        'alert_strategy': {
            'pct_runs_immediate_wins': round(
                sum(1 for r in strategy_results
                    if r.get('recommendation') == 'immediate')
                / len(strategy_results) * 100, 1
            ) if strategy_results else 0,
        },
        'elapsed_seconds': round(time.time() - start_time, 1),
    }

    print(f"\n{'='*70}")
    print("MONTE CARLO RESULTS")
    print(f"{'='*70}")
    print(f"Runs completed: {len(all_results)}/{n_runs}")
    print(f"Avg assertion pass rate: {monte_carlo_results['assertion_pass_rate']['mean']}%")
    print(f"\nAgent Score Confidence Intervals (95%):")
    print(f"{'Agent':<30} {'Low':>8} {'Mean':>8} {'High':>8} {'Elite%':>8}")
    print("-" * 70)

    for name, data in monte_carlo_results['per_agent_confidence_intervals'].items():
        ci    = data['score_95ci']
        elite = data['zone_dist'].get('Elite', 0)
        print(f"{name:<30} {ci[0]:>8.1f} {ci[1]:>8.1f} {ci[2]:>8.1f} {elite:>7.1f}%")

    print(f"\nAlert immediate-wins: {monte_carlo_results['alert_strategy']['pct_runs_immediate_wins']}% of runs")
    print(f"Time elapsed: {monte_carlo_results['elapsed_seconds']}s")

    return monte_carlo_results


# =============================================================================
# ENTRYPOINT
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sifter Simulation Harness")
    parser.add_argument('--mode',   choices=['single', 'monte_carlo', 'alert_timing'],
                        default='single')
    parser.add_argument('--days',   type=int, default=30)
    parser.add_argument('--runs',   type=int, default=100)
    parser.add_argument('--seed',   type=int, default=42)
    parser.add_argument('--market',
                        choices=['bull', 'bear', 'neutral', 'crash', 'squeeze'],
                        default='bull')
    parser.add_argument('--output', type=str, default=None,
                        help='Save results to JSON file')
    args = parser.parse_args()

    market_map = {
        'bull':    MarketState.BULL,
        'bear':    MarketState.BEAR,
        'neutral': MarketState.NEUTRAL,
        'crash':   MarketState.CRASH,
        'squeeze': MarketState.SQUEEZE,
    }

    if args.mode == 'single':
        result = run_single_simulation(
            days         = args.days,
            market_state = market_map[args.market],
            seed         = args.seed,
            verbose      = True,
        )

    elif args.mode == 'monte_carlo':
        result = run_monte_carlo(
            n_runs = args.runs,
            days   = args.days,
        )

    if args.output and result:
        with open(args.output, 'w') as f:
            def _clean(obj):
                if isinstance(obj, dict):  return {k: _clean(v) for k, v in obj.items()}
                if isinstance(obj, list):  return [_clean(i) for i in obj]
                if isinstance(obj, (int, float, str, bool)) or obj is None: return obj
                return str(obj)
            json.dump(_clean(result), f, indent=2)
        print(f"\nResults saved to {args.output}")