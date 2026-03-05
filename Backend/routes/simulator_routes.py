# routes/simulator.py
#
# Three endpoints:
#   POST /api/simulator/copy           — copy trading simulation
#   POST /api/simulator/skill          — skill vs luck analysis
#   POST /api/simulator/exit-strategies — exit strategy comparison
#
# All endpoints work entirely off data passed from the frontend
# (roi_details, other_runners, consistency_score).
# No new blockchain fetches required — just math.

import math
import random
import statistics
from flask import Blueprint, request, jsonify

simulator_bp = Blueprint('simulator', __name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _require_json(*fields):
    """Return (data, error_response) — error_response is None if all fields present."""
    data = request.get_json(silent=True)
    if not data:
        return None, (jsonify({'success': False, 'error': 'No JSON body'}), 400)
    for f in fields:
        if f not in data:
            return None, (jsonify({'success': False, 'error': f'Missing field: {f}'}), 400)
    return data, None


def _apply_delay_penalty(entry_to_ath_mult, delay_minutes, trade_age_minutes=None):
    """
    Estimate the realistic multiplier a user gets given their entry delay.

    Logic:
      - In the first hour after launch, price moves ~0.8% per minute on average.
      - After 1 hour, momentum slows to ~0.3% per minute.
      - We subtract the price appreciation that occurred during the delay window
        from the entry_to_ath_mult.

    Returns adjusted multiplier (>= 1.0 clamped).
    """
    if entry_to_ath_mult is None or entry_to_ath_mult <= 1:
        return entry_to_ath_mult or 1.0

    if delay_minutes <= 1:
        return entry_to_ath_mult

    # Price appreciation during delay
    if delay_minutes <= 60:
        pct_moved = delay_minutes * 0.008      # 0.8%/min in first hour
    else:
        pct_moved = 60 * 0.008 + (delay_minutes - 60) * 0.003

    pct_moved = min(pct_moved, 0.85)           # cap: can't move more than 85% of the gain
    adjusted  = entry_to_ath_mult * (1 - pct_moved)
    return max(1.0, round(adjusted, 3))


def _simulate_exit(entry_to_ath_mult, strategy):
    """
    Given a wallet's entry_to_ath_mult (their potential gain) and an exit strategy,
    return the realistic multiplier the user actually captures.

    entry_to_ath_mult: how many x from user's entry to the ATH
    strategy: one of copy|ath|trail20|trail30|tp3x|hold
    """
    if entry_to_ath_mult is None or entry_to_ath_mult <= 1:
        return entry_to_ath_mult or 1.0

    if strategy == 'ath':
        # Exit at ATH: capture 92% (slight slippage)
        return round(entry_to_ath_mult * 0.92, 3)

    elif strategy == 'trail20':
        # Trailing 20%: exit when price drops 20% from peak
        # On average this captures about 78% of the ATH move
        return round(entry_to_ath_mult * 0.78, 3)

    elif strategy == 'trail30':
        # Trailing 30%: captures more of big runners, misses more on small ones
        return round(entry_to_ath_mult * 0.72, 3)

    elif strategy == 'tp3x':
        # Take profit at 3x regardless
        return min(entry_to_ath_mult, 3.0)

    elif strategy == 'copy':
        # Copy wallet exits: wallet typically exits at ~80% of ATH
        return round(entry_to_ath_mult * 0.80, 3)

    elif strategy == 'hold':
        # Hold forever: price decays from ATH; model as 60% of ATH captured avg
        return round(entry_to_ath_mult * 0.60, 3)

    return entry_to_ath_mult


def _roi_mult_to_pct(mult):
    return round((mult - 1) * 100, 1) if mult is not None else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT 1: Copy Simulator
# ─────────────────────────────────────────────────────────────────────────────

@simulator_bp.route('/api/simulator/copy', methods=['POST'])
def simulate_copy():
    """
    Simulate what a user would have made copying this wallet,
    and project forward with Monte Carlo.

    Request body:
      wallet_address   str
      roi_details      list[dict]  — per-token breakdown from ResultsPanel
      delay_minutes    float       — user's entry delay
      exit_strategy    str         — copy|ath|trail20|trail30|tp3x|hold
      filter_min_usd   float       — ignore trades below this size (0 = no filter)
      ignore_sells     bool        — if true, hold regardless of wallet sells

    Response:
      past_period:
        wallet_roi_pct, your_roi_pct, gap_pct
        biggest_miss: {symbol, wallet_mult, your_mult}
      future_period:
        likely_low/high (70%), good_low/high (20%), bad_low/high (10%)
        prob_profit, prob_loss, worst_case
      risk:
        max_drawdown, recovery_weeks, suggested_allocation
    """
    data, err = _require_json('roi_details', 'delay_minutes', 'exit_strategy')
    if err:
        return err

    roi_details   = data['roi_details']
    delay_minutes = float(data.get('delay_minutes', 30))
    exit_strategy = data.get('exit_strategy', 'trail20')
    filter_min    = float(data.get('filter_min_usd', 0))
    ignore_sells  = bool(data.get('ignore_sells', False))

    # ── Filter trades ─────────────────────────────────────────────────────────
    trades = [
        t for t in roi_details
        if t.get('entry_to_ath_multiplier') is not None
        and t.get('entry_to_ath_multiplier', 0) > 0
    ]
    if filter_min > 0:
        trades = [t for t in trades if (t.get('total_invested') or 0) >= filter_min]

    if not trades:
        return jsonify({'success': False, 'error': 'No qualifying trades after filters'}), 400

    # ── Past period: per-trade simulation ────────────────────────────────────
    wallet_mults = []
    user_mults   = []
    biggest_miss = None

    for t in trades:
        w_mult = t.get('entry_to_ath_multiplier', 1.0)

        # Apply delay penalty
        u_mult = _apply_delay_penalty(w_mult, delay_minutes)

        # Apply exit strategy (if ignore_sells, override to hold)
        if ignore_sells:
            u_mult = _simulate_exit(u_mult, 'hold')
        else:
            u_mult = _simulate_exit(u_mult, exit_strategy)

        wallet_mults.append(w_mult)
        user_mults.append(u_mult)

        gap = w_mult - u_mult
        if biggest_miss is None or gap > (biggest_miss['wallet_mult'] - biggest_miss['your_mult']):
            biggest_miss = {
                'symbol':      t.get('runner', t.get('symbol', '???')),
                'wallet_mult': round(w_mult, 2),
                'your_mult':   round(u_mult, 2),
            }

    # Aggregate past ROI as geometric average
    def _geo_mean(mults):
        if not mults:
            return 1.0
        product = 1.0
        for m in mults:
            product *= max(0.01, m)
        return product ** (1 / len(mults))

    wallet_geo = _geo_mean(wallet_mults)
    user_geo   = _geo_mean(user_mults)

    # ── Monte Carlo — 10,000 simulations ─────────────────────────────────────
    n_sims = 10_000
    sim_returns = []
    base_mean   = user_geo
    base_std    = statistics.pstdev(user_mults) if len(user_mults) > 1 else base_mean * 0.3

    for _ in range(n_sims):
        # Sample random subset of trades (bootstrap-ish)
        n_trades = max(1, int(len(trades) * random.uniform(0.6, 1.0)))
        sampled  = random.choices(user_mults, k=n_trades)

        # Add market condition noise
        market_factor = random.gauss(1.0, 0.15)
        sim_roi = _geo_mean(sampled) * market_factor

        # Add delay variance
        delay_noise = random.gauss(1.0, delay_minutes * 0.003)
        sim_roi     = max(0.3, sim_roi * delay_noise)
        sim_returns.append(sim_roi)

    sim_returns.sort()
    n = len(sim_returns)

    # Percentile helper
    def pct(p):
        idx = min(int(p / 100 * n), n - 1)
        return sim_returns[idx]

    likely_low  = _roi_mult_to_pct(pct(15))
    likely_high = _roi_mult_to_pct(pct(85))
    good_low    = _roi_mult_to_pct(pct(80))
    good_high   = _roi_mult_to_pct(pct(95))
    bad_low     = _roi_mult_to_pct(pct(1))
    bad_high    = _roi_mult_to_pct(pct(15))
    worst_case  = _roi_mult_to_pct(pct(2))

    prob_profit = round(sum(1 for r in sim_returns if r > 1.0) / n * 100, 1)
    prob_loss   = round(sum(1 for r in sim_returns if r < 0.95) / n * 100, 1)

    # ── Risk metrics ──────────────────────────────────────────────────────────
    losing_sims  = [r for r in sim_returns if r < 1.0]
    max_drawdown = _roi_mult_to_pct(pct(2))      # 2nd percentile as "max realistic dd"

    # Recovery: rough heuristic based on how deep drawdowns are
    avg_loss = (sum(1 - r for r in losing_sims) / len(losing_sims)) if losing_sims else 0
    recovery_weeks = max(1, min(12, round(avg_loss * 40)))

    # Suggested allocation based on prob of loss and depth
    if prob_loss < 10 and abs(worst_case) < 15:
        suggested_allocation = '15–25%'
    elif prob_loss < 20 and abs(worst_case) < 30:
        suggested_allocation = '10–15%'
    elif prob_loss < 35:
        suggested_allocation = '5–10%'
    else:
        suggested_allocation = '< 5%'

    return jsonify({
        'success': True,
        'results': {
            'filter_min_usd': filter_min,
            'trade_count':    len(trades),
            'past_period': {
                'wallet_roi_pct': _roi_mult_to_pct(wallet_geo),
                'your_roi_pct':   _roi_mult_to_pct(user_geo),
                'gap_pct':        round(_roi_mult_to_pct(user_geo) - _roi_mult_to_pct(wallet_geo), 1),
                'biggest_miss':   biggest_miss,
            },
            'future_period': {
                'likely_low':  likely_low,
                'likely_high': likely_high,
                'good_low':    good_low,
                'good_high':   good_high,
                'bad_low':     bad_low,
                'bad_high':    bad_high,
                'worst_case':  worst_case,
                'prob_profit': prob_profit,
                'prob_loss':   prob_loss,
            },
            'risk': {
                'max_drawdown':          max_drawdown,
                'recovery_weeks':        recovery_weeks,
                'suggested_allocation':  suggested_allocation,
            },
        }
    })


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT 2: Skill vs Luck
# ─────────────────────────────────────────────────────────────────────────────

@simulator_bp.route('/api/simulator/skill', methods=['POST'])
def analyze_skill():
    """
    Measure the wallet's internal behavioral consistency.
    NOT a comparison to other wallets — purely self-referential.

    Request body:
      roi_details       list[dict]
      other_runners     list[dict]
      consistency_score float  (0-100 from backend)
      score_breakdown   dict

    Four factors scored 0-100:
      1. Entry consistency   — how reliably early vs ATH across trades
      2. Profit distribution — top trade % of total profits (low = skilled)
      3. Win rate stability  — variance in per-trade profitability
      4. Risk management     — max loss size (controlled = skilled)
    """
    data, err = _require_json('roi_details')
    if err:
        return err

    roi_details      = data['roi_details']
    other_runners    = data.get('other_runners', [])
    raw_consistency  = float(data.get('consistency_score', 50))
    score_breakdown  = data.get('score_breakdown', {})

    all_trades = roi_details + [
        {
            'entry_to_ath_multiplier': r.get('entry_to_ath_multiplier'),
            'roi_multiplier':          r.get('roi_multiplier'),
            'runner':                  r.get('symbol', r.get('ticker', '?')),
        }
        for r in other_runners
    ]

    if len(all_trades) < 2:
        return jsonify({
            'success': True,
            'results': {
                'overall_skill_score': 50,
                'verdict': 'INSUFFICIENT DATA',
                'factors': {},
                'future_outlook_pct': 50,
                'confidence_pct':     20,
                'implications': ['Not enough trade history to assess skill reliably.'],
            }
        })

    # ── Factor 1: Entry Consistency (via raw_consistency from backend) ────────
    entry_score = round(raw_consistency)
    entry_vals  = [t.get('entry_to_ath_multiplier') for t in all_trades if t.get('entry_to_ath_multiplier')]
    if entry_vals:
        entry_std = statistics.pstdev(entry_vals)
        entry_mean = statistics.mean(entry_vals)
        cv = entry_std / entry_mean if entry_mean > 0 else 1.0
        # Low CV (< 0.3) = very consistent = high score
        entry_score = max(0, min(100, round(100 - (cv * 100))))
    entry_label = f"±{round(statistics.pstdev(entry_vals), 1)}x variance" if len(entry_vals) > 1 else "1 trade"

    # ── Factor 2: Profit Distribution ─────────────────────────────────────────
    roi_mults = [t.get('roi_multiplier') or t.get('entry_to_ath_multiplier', 1) for t in all_trades]
    roi_mults = [m for m in roi_mults if m and m > 0]

    if roi_mults:
        total_roi = sum(roi_mults)
        max_roi   = max(roi_mults)
        top_trade_pct = (max_roi / total_roi * 100) if total_roi > 0 else 100

        # Top trade < 30% = well diversified = high score
        # Top trade > 70% = one-hit wonder = low score
        if top_trade_pct <= 20:   profit_score = 95
        elif top_trade_pct <= 30: profit_score = 85
        elif top_trade_pct <= 45: profit_score = 70
        elif top_trade_pct <= 60: profit_score = 50
        elif top_trade_pct <= 75: profit_score = 30
        else:                     profit_score = 12
        profit_label = f"Top trade = {round(top_trade_pct)}% of total"
    else:
        profit_score = 50
        top_trade_pct = None
        profit_label = '—'

    # ── Factor 3: Win Rate Stability ──────────────────────────────────────────
    wins   = sum(1 for m in roi_mults if m >= 2.0)   # 2x+ = meaningful win
    losses = sum(1 for m in roi_mults if m < 1.0)
    total  = len(roi_mults)
    win_rate = wins / total if total > 0 else 0

    # For stability we want: win rate between 30-60%, not 0% or 100%
    # And low variance between trades
    if total > 3:
        roi_std = statistics.pstdev(roi_mults)
        roi_mean = statistics.mean(roi_mults)
        # Controlled variance (CV 0.3-1.0) = skilled; very high CV = lucky outlier
        cv_roi = roi_std / roi_mean if roi_mean > 0 else 1
        if cv_roi <= 0.5:   stability_score = 90
        elif cv_roi <= 0.8: stability_score = 75
        elif cv_roi <= 1.2: stability_score = 55
        elif cv_roi <= 2.0: stability_score = 35
        else:               stability_score = 15
    else:
        stability_score = 50

    stability_label = f"{round(win_rate * 100)}% win rate across {total} trades"

    # ── Factor 4: Risk Management ─────────────────────────────────────────────
    loss_mults  = [m for m in roi_mults if m < 1.0]
    if loss_mults:
        max_loss_pct = (1 - min(loss_mults)) * 100   # worst single loss
        avg_loss_pct = (1 - statistics.mean(loss_mults)) * 100
        if max_loss_pct <= 15:   risk_score = 92
        elif max_loss_pct <= 25: risk_score = 78
        elif max_loss_pct <= 40: risk_score = 58
        elif max_loss_pct <= 60: risk_score = 35
        else:                    risk_score = 15
        risk_label = f"Max loss -{round(max_loss_pct)}%"
    else:
        risk_score = 70   # no losses yet — not enough data to say great or bad
        risk_label = 'No losses recorded'

    # ── Weighted overall score ────────────────────────────────────────────────
    overall = round(
        0.30 * entry_score +
        0.30 * profit_score +
        0.20 * stability_score +
        0.20 * risk_score
    )

    # ── Verdict ───────────────────────────────────────────────────────────────
    if overall >= 75:
        verdict = 'GENUINELY SKILLED TRADER'
    elif overall >= 55:
        verdict = 'MIXED — SOME SKILL PRESENT'
    else:
        verdict = 'LIKELY LUCKY — NOT REPEATABLE'

    # ── Forward outlook via simple Monte Carlo ────────────────────────────────
    n_sims = 5000
    success_count = 0
    for _ in range(n_sims):
        # Skilled wallets: draw from their actual distribution with noise
        # Lucky wallets: draw from much wider distribution
        noise_scale = 0.5 if overall >= 70 else 1.5
        sim_roi_avg = statistics.mean(roi_mults) * random.gauss(1.0, noise_scale * 0.25)
        if sim_roi_avg > 1.3:   # at least 30% gain
            success_count += 1

    future_outlook = round(success_count / n_sims * 100, 1)
    confidence_pct = min(95, round(30 + total * 3))   # more trades = more confidence

    # ── Implications ─────────────────────────────────────────────────────────
    implications = []
    if overall >= 75:
        implications.append('Process appears repeatable — not reliant on single lucky trade.')
        if entry_score >= 70:
            implications.append('Entries consistently early relative to ATH across tokens.')
        if profit_score >= 70:
            implications.append(f'Profits distributed across many trades (top trade = {round(top_trade_pct)}%).')
        if risk_score >= 70:
            implications.append('Losses are controlled and disciplined.')
    else:
        implications.append('Performance concentrated in too few trades to be confident.')
        if profit_score < 50 and top_trade_pct:
            implications.append(f'One trade drives {round(top_trade_pct)}% of profits — vulnerable to regression.')
        if entry_score < 50:
            implications.append('Entry timing is inconsistent — sometimes early, sometimes late.')

    return jsonify({
        'success': True,
        'results': {
            'overall_skill_score': overall,
            'verdict':             verdict,
            'trade_count':         total,
            'factors': {
                'entry_consistency': {
                    'score':       entry_score,
                    'value_label': entry_label,
                    'detail':      'How reliably early vs ATH across all trades',
                },
                'profit_distribution': {
                    'score':       profit_score,
                    'value_label': profit_label,
                    'detail':      'Profits spread across trades vs one big hit',
                },
                'win_rate_stability': {
                    'score':       stability_score,
                    'value_label': stability_label,
                    'detail':      'Variance in per-trade profitability',
                },
                'risk_management': {
                    'score':       risk_score,
                    'value_label': risk_label,
                    'detail':      'Size and frequency of losses',
                },
            },
            'future_outlook_pct': future_outlook,
            'confidence_pct':     confidence_pct,
            'implications':       implications,
        }
    })


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT 3: Exit Strategy Comparison
# ─────────────────────────────────────────────────────────────────────────────

@simulator_bp.route('/api/simulator/exit-strategies', methods=['POST'])
def compare_exit_strategies():
    """
    Test all exit strategies against the wallet's historical trades
    and return ranked results with a recommendation.

    Request body:
      roi_details  list[dict]

    Response:
      strategies: [{id, label, avg_roi_mult, win_rate, best_mult, worst_mult}]
      recommended: strategy_id
      recommendation_reason: str
      trade_count: int
    """
    data, err = _require_json('roi_details')
    if err:
        return err

    roi_details = data['roi_details']
    trades = [
        t for t in roi_details
        if t.get('entry_to_ath_multiplier') is not None
        and t.get('entry_to_ath_multiplier', 0) > 0
    ]

    if not trades:
        return jsonify({'success': False, 'error': 'No qualifying trades in roi_details'}), 400

    strategies = [
        {'id': 'copy',    'label': 'Copy wallet exits'},
        {'id': 'ath',     'label': 'Exit at ATH'},
        {'id': 'trail20', 'label': 'Trailing stop 20%'},
        {'id': 'trail30', 'label': 'Trailing stop 30%'},
        {'id': 'tp3x',    'label': 'Take profit 3x'},
        {'id': 'hold',    'label': 'Hold forever'},
    ]

    results = []
    for s in strategies:
        mults = []
        for t in trades:
            w_mult = t.get('entry_to_ath_multiplier', 1.0)
            u_mult = _simulate_exit(w_mult, s['id'])
            mults.append(u_mult)

        wins     = sum(1 for m in mults if m >= 1.5)   # 50% gain = win
        win_rate = round(wins / len(mults) * 100, 1) if mults else 0

        results.append({
            'id':          s['id'],
            'label':       s['label'],
            'avg_roi_mult': round(statistics.mean(mults), 2) if mults else 1.0,
            'win_rate':    win_rate,
            'best_mult':   round(max(mults), 2) if mults else 1.0,
            'worst_mult':  round(min(mults), 2) if mults else 1.0,
        })

    # ── Recommendation: best risk-adjusted strategy ───────────────────────────
    # Score = avg_roi_mult * win_rate_weight - downside_penalty
    def _risk_score(s):
        win_w   = s['win_rate'] / 100
        avg     = s['avg_roi_mult']
        worst   = s['worst_mult']
        downside_penalty = max(0, (1 - worst) * 2)   # penalise big losses heavily
        return avg * win_w - downside_penalty

    results.sort(key=lambda s: _risk_score(s), reverse=True)
    best = results[0]

    # Reason string
    reason_parts = []
    reason_parts.append(
        f"Best risk-adjusted return: {best['avg_roi_mult']}x average with {best['win_rate']}% win rate."
    )
    if best['worst_mult'] < 0.7:
        reason_parts.append(f"Note: worst case is {best['worst_mult']}x — size positions accordingly.")
    elif best['worst_mult'] >= 0.85:
        reason_parts.append(f"Downside is limited ({best['worst_mult']}x worst case), making this the safest choice.")
    reason = ' '.join(reason_parts)

    return jsonify({
        'success': True,
        'results': {
            'strategies':            results,
            'recommended':           best['id'],
            'recommendation_reason': reason,
            'trade_count':           len(trades),
        }
    })