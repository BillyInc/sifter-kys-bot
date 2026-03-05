"""
trader_agent_base.py

Base class for all simulated wallet agents.

Each agent has a defined personality that controls:
  - How often they trade (participation rate)
  - How early they enter after token launch (entry timing)
  - How they size positions (position sizing + DCA behavior)
  - How they exit (profit-taking personality)
  - How they respond to market state changes

The LLM hook is optional — agents work fully without it.
When plugged in, the LLM generates realistic exit decisions
using ThoughtChain + BackgroundFactory context.

Does NOT import any real platform services.
Designed to have trade data extracted and fed INTO those services.

FIXES IN THIS VERSION:
  Bug 1 — ATH stamp now happens in this base class directly.
    _enter_position(), _dca_into_position(), and _execute_sell() all stamp
    launch_to_ath_multiplier before calling model.record_trade(). Previously
    this was left to _record_trade_with_ath() stubs in each concrete agent,
    which were never called — so every trade had launch_to_ath_multiplier=0.0.
    With ATH=0, _count_runners() skipped the 30x token floor and produced
    false runner counts. All concrete agent _record_trade_with_ath() stubs
    have been removed as they are now dead code.
"""

import random
import statistics
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import mesa

from solana_market_model import (
    SolanaMarketModel,
    SimulatedToken,
    TradeRecord,
    MarketState,
    PriceCurveGenerator,
)


# =============================================================================
# PERSONALITY ENUMS
# =============================================================================

class ExitPersonality(Enum):
    PARTIAL_TAKER    = "partial_taker"
    SCALPER          = "scalper"
    DIAMOND_HANDS    = "diamond_hands"
    TRAILING_STOPPER = "trailing_stopper"
    CHAOS            = "chaos"


class DCAPersonality(Enum):
    ONE_SHOT         = "one_shot"
    FRONT_LOADED     = "front_loaded"
    ACCUMULATOR      = "accumulator"
    SNIPER           = "sniper"


# =============================================================================
# AGENT PERSONALITY CONFIG
# =============================================================================

@dataclass
class AgentPersonality:
    name:               str = "Unknown"
    participation_rate: float = 0.50
    entry_hour_range:   Tuple[int, int] = (0, 2)
    quality_rate:       float = 0.70
    win_rate:           float = 0.60
    avg_position_usd:   float = 250.0
    position_std:       float = 80.0
    min_position_usd:   float = 100.0
    exit_personality:   ExitPersonality = ExitPersonality.PARTIAL_TAKER
    dca_personality:    DCAPersonality = DCAPersonality.ONE_SHOT
    dca_probability:    float = 0.20
    dca_spread_hours:   Tuple[int, int] = (1, 4)
    dca_size_pct:       float = 0.30
    bull_activity_mult:  float = 1.3
    bear_activity_mult:  float = 0.5
    crash_activity_mult: float = 0.1


# =============================================================================
# PREDEFINED PERSONALITIES
# =============================================================================

PERSONALITY_STEADY_EDDIE = AgentPersonality(
    name               = "Steady Eddie",
    participation_rate = 0.85,
    entry_hour_range   = (0, 1),
    quality_rate       = 0.90,
    win_rate           = 0.75,
    avg_position_usd   = 350.0,
    position_std       = 60.0,
    min_position_usd   = 150.0,
    exit_personality   = ExitPersonality.PARTIAL_TAKER,
    dca_personality    = DCAPersonality.FRONT_LOADED,
    dca_probability    = 0.35,
    dca_spread_hours   = (1, 3),
    dca_size_pct       = 0.25,
    bull_activity_mult = 1.2,
    bear_activity_mult = 0.7,
    crash_activity_mult= 0.05,
)

PERSONALITY_MOMENTUM_MARCUS = AgentPersonality(
    name               = "Momentum Marcus",
    participation_rate = 0.75,
    entry_hour_range   = (1, 4),
    quality_rate       = 0.80,
    win_rate           = 0.68,
    avg_position_usd   = 300.0,
    position_std       = 90.0,
    min_position_usd   = 120.0,
    exit_personality   = ExitPersonality.TRAILING_STOPPER,
    dca_personality    = DCAPersonality.FRONT_LOADED,
    dca_probability    = 0.25,
    dca_spread_hours   = (2, 5),
    dca_size_pct       = 0.30,
    bull_activity_mult = 1.3,
    bear_activity_mult = 0.6,
    crash_activity_mult= 0.05,
)

PERSONALITY_HOT_STREAK_HANK = AgentPersonality(
    name               = "Hot Streak Hank",
    participation_rate = 0.80,
    entry_hour_range   = (0, 2),
    quality_rate       = 0.85,
    win_rate           = 0.72,
    avg_position_usd   = 400.0,
    position_std       = 100.0,
    min_position_usd   = 150.0,
    exit_personality   = ExitPersonality.PARTIAL_TAKER,
    dca_personality    = DCAPersonality.ONE_SHOT,
    dca_probability    = 0.15,
    dca_spread_hours   = (1, 3),
    dca_size_pct       = 0.20,
    bull_activity_mult = 1.4,
    bear_activity_mult = 0.4,
    crash_activity_mult= 0.0,
)

PERSONALITY_VOLATILE_VICTOR = AgentPersonality(
    name               = "Volatile Victor",
    participation_rate = 0.90,
    entry_hour_range   = (0, 3),
    quality_rate       = 0.50,
    win_rate           = 0.50,
    avg_position_usd   = 180.0,
    position_std       = 120.0,
    min_position_usd   = 80.0,
    exit_personality   = ExitPersonality.CHAOS,
    dca_personality    = DCAPersonality.ACCUMULATOR,
    dca_probability    = 0.50,
    dca_spread_hours   = (2, 8),
    dca_size_pct       = 0.40,
    bull_activity_mult = 1.5,
    bear_activity_mult = 0.8,
    crash_activity_mult= 0.20,
)

PERSONALITY_CLUSTER_CLARA = AgentPersonality(
    name               = "Cluster Clara",
    participation_rate = 0.70,
    entry_hour_range   = (0, 2),
    quality_rate       = 0.78,
    win_rate           = 0.68,
    avg_position_usd   = 280.0,
    position_std       = 70.0,
    min_position_usd   = 120.0,
    exit_personality   = ExitPersonality.PARTIAL_TAKER,
    dca_personality    = DCAPersonality.FRONT_LOADED,
    dca_probability    = 0.30,
    dca_spread_hours   = (1, 4),
    dca_size_pct       = 0.30,
    bull_activity_mult = 1.6,
    bear_activity_mult = 0.3,
    crash_activity_mult= 0.0,
)

PERSONALITY_INACTIVE_IZZY = AgentPersonality(
    name               = "Inactive Izzy",
    participation_rate = 0.60,
    entry_hour_range   = (1, 4),
    quality_rate       = 0.70,
    win_rate           = 0.60,
    avg_position_usd   = 200.0,
    position_std       = 80.0,
    min_position_usd   = 100.0,
    exit_personality   = ExitPersonality.SCALPER,
    dca_personality    = DCAPersonality.ONE_SHOT,
    dca_probability    = 0.10,
    dca_spread_hours   = (2, 6),
    dca_size_pct       = 0.20,
    bull_activity_mult = 1.0,
    bear_activity_mult = 0.5,
    crash_activity_mult= 0.0,
)

PERSONALITY_BOOM_BUST_BECKY = AgentPersonality(
    name               = "Boom Bust Becky",
    participation_rate = 0.40,
    entry_hour_range   = (0, 3),
    quality_rate       = 0.65,
    win_rate           = 0.45,
    avg_position_usd   = 600.0,
    position_std       = 300.0,
    min_position_usd   = 200.0,
    exit_personality   = ExitPersonality.DIAMOND_HANDS,
    dca_personality    = DCAPersonality.ONE_SHOT,
    dca_probability    = 0.05,
    dca_spread_hours   = (1, 2),
    dca_size_pct       = 0.10,
    bull_activity_mult = 1.2,
    bear_activity_mult = 0.3,
    crash_activity_mult= 0.0,
)

PERSONALITY_LATE_LARRY = AgentPersonality(
    name               = "Late Larry",
    participation_rate = 0.75,
    entry_hour_range   = (3, 8),
    quality_rate       = 0.72,
    win_rate           = 0.65,
    avg_position_usd   = 220.0,
    position_std       = 70.0,
    min_position_usd   = 100.0,
    exit_personality   = ExitPersonality.TRAILING_STOPPER,
    dca_personality    = DCAPersonality.SNIPER,
    dca_probability    = 0.40,
    dca_spread_hours   = (4, 12),
    dca_size_pct       = 0.50,
    bull_activity_mult = 1.1,
    bear_activity_mult = 0.6,
    crash_activity_mult= 0.05,
)

PERSONALITY_RISING_RHONDA = AgentPersonality(
    name               = "Rising Rhonda",
    participation_rate = 0.80,
    entry_hour_range   = (0, 2),
    quality_rate       = 0.85,
    win_rate           = 0.72,
    avg_position_usd   = 300.0,
    position_std       = 80.0,
    min_position_usd   = 130.0,
    exit_personality   = ExitPersonality.PARTIAL_TAKER,
    dca_personality    = DCAPersonality.FRONT_LOADED,
    dca_probability    = 0.30,
    dca_spread_hours   = (1, 3),
    dca_size_pct       = 0.25,
    bull_activity_mult = 1.3,
    bear_activity_mult = 0.6,
    crash_activity_mult= 0.05,
)

PERSONALITY_CONSISTENT_CARLOS = AgentPersonality(
    name               = "Consistent Carlos",
    participation_rate = 0.70,
    entry_hour_range   = (0, 3),
    quality_rate       = 0.88,
    win_rate           = 0.70,
    avg_position_usd   = 250.0,
    position_std       = 40.0,
    min_position_usd   = 150.0,
    exit_personality   = ExitPersonality.PARTIAL_TAKER,
    dca_personality    = DCAPersonality.FRONT_LOADED,
    dca_probability    = 0.25,
    dca_spread_hours   = (1, 4),
    dca_size_pct       = 0.30,
    bull_activity_mult = 1.1,
    bear_activity_mult = 0.7,
    crash_activity_mult= 0.05,
)


# =============================================================================
# TRADER AGENT BASE
# =============================================================================

class TraderAgentBase(mesa.Agent):
    """
    Base class for all simulated wallet agents.
    
    ATH STAMPING (Bug 1 fix):
      launch_to_ath_multiplier is looked up from model.active_tokens and stamped
      onto every TradeRecord in _enter_position(), _dca_into_position(), and
      _execute_sell() before calling model.record_trade(). This guarantees all
      trades carry the correct ATH so _count_runners() and _calculate_win_rate()
      can enforce the 30x token floor. The _record_trade_with_ath() pattern in
      concrete agents was dead code and has been removed entirely.
    """
    
    def __init__(
        self,
        unique_id:   int,
        model:       SolanaMarketModel,
        personality: AgentPersonality,
        wallet_address: str,
        llm_chain = None,
        background = None,
    ):
        super().__init__(unique_id, model)
        
        self.personality     = personality
        self.wallet_address  = wallet_address
        self.llm_chain       = llm_chain
        self.background      = background
        
        self.open_positions: Dict[str, 'OpenPosition'] = {}
        self.closed_trades:  List[ClosedTrade] = []
        self.total_invested: float = 0.0
        self.total_realized: float = 0.0
        
        self.is_active:        bool  = True
        self.degradation_week: int   = -1
        self.current_week:     int   = 0
        
        self._noise_seed: Optional[float] = None
        
        print(f"[AGENT] {personality.name} initialized | wallet: {wallet_address[:12]}...")
    
    # =========================================================================
    # MAIN STEP
    # =========================================================================
    
    def step(self):
        """Called once per simulation day."""
        
        self.current_week = self.model.day // 7
        
        if self._should_degrade():
            self._apply_degradation()
        
        if not self.is_active:
            return
        
        eff_rate = self._effective_participation_rate()
        
        for token in self.model.todays_tokens:
            if random.random() > eff_rate:
                continue
            if random.random() > self.personality.quality_rate:
                continue
            if token.address in self.open_positions:
                continue
            self._enter_position(token)
        
        for token_address in list(self.open_positions.keys()):
            pos = self.open_positions[token_address]
            if not pos.dca_complete and random.random() < self.personality.dca_probability:
                self._dca_into_position(pos)
        
        for token_address in list(self.open_positions.keys()):
            pos = self.open_positions[token_address]
            self._evaluate_exit(pos)
    
    # =========================================================================
    # ENTRY
    # =========================================================================
    
    def _enter_position(self, token: SimulatedToken):
        """Open a new position in a token."""
        
        min_h, max_h = self.personality.entry_hour_range
        entry_hour_offset = random.randint(min_h, max_h)
        
        entry_day  = token.launch_day
        entry_hour = token.launch_hour + entry_hour_offset
        
        if entry_hour > 23:
            entry_day  += entry_hour // 24
            entry_hour  = entry_hour % 24
        
        entry_price = self.model.get_price_at(token, entry_day, entry_hour)
        
        size = max(
            self.personality.min_position_usd,
            random.gauss(self.personality.avg_position_usd, self.personality.position_std)
        )
        size = round(size, 2)

        # ── Bug 1 fix: stamp ATH at record time ───────────────────────────────
        ath = (
            self.model.active_tokens[token.address].curve.ath_multiplier
            if token.address in self.model.active_tokens else 0.0
        )

        trade = TradeRecord(
            wallet_address           = self.wallet_address,
            token_address            = token.address,
            token_symbol             = token.symbol,
            side                     = 'buy',
            price_multiplier         = entry_price,
            position_size_usd        = size,
            cumulative_invested      = size,
            day                      = entry_day,
            hour                     = entry_hour,
            buy_hour_offset          = entry_hour_offset,
            is_dca                   = False,
            launch_to_ath_multiplier = ath,          # ← stamped
        )
        self.model.record_trade(trade)
        self.total_invested += size
        
        pos = OpenPosition(
            token          = token,
            entry_day      = entry_day,
            entry_hour     = entry_hour,
            entry_price    = entry_price,
            total_invested = size,
            buy_records    = [trade],
            peak_price     = entry_price,
        )
        self.open_positions[token.address] = pos
    
    # =========================================================================
    # DCA
    # =========================================================================
    
    def _dca_into_position(self, pos: 'OpenPosition'):
        """Add a second buy into an open position."""
        if pos.dca_complete:
            return
        
        min_spread, max_spread = self.personality.dca_spread_hours
        hours_since_entry = (self.model.day - pos.entry_day) * 24
        
        if hours_since_entry < min_spread:
            return
        
        dca_size = pos.buy_records[0].position_size_usd * self.personality.dca_size_pct
        dca_size = max(self.personality.min_position_usd * 0.5, dca_size)
        dca_size = round(dca_size, 2)
        
        current_price = self.model.get_price_at(pos.token, self.model.day, 12)
        
        if self.personality.dca_personality == DCAPersonality.SNIPER:
            if current_price > pos.entry_price * 1.5:
                return
        
        new_cumulative = pos.total_invested + dca_size

        # ── Bug 1 fix: stamp ATH at record time ───────────────────────────────
        ath = (
            self.model.active_tokens[pos.token.address].curve.ath_multiplier
            if pos.token.address in self.model.active_tokens else 0.0
        )
        
        trade = TradeRecord(
            wallet_address           = self.wallet_address,
            token_address            = pos.token.address,
            token_symbol             = pos.token.symbol,
            side                     = 'buy',
            price_multiplier         = current_price,
            position_size_usd        = dca_size,
            cumulative_invested      = new_cumulative,
            day                      = self.model.day,
            hour                     = random.randint(8, 20),
            buy_hour_offset          = hours_since_entry,
            is_dca                   = True,
            launch_to_ath_multiplier = ath,          # ← stamped
        )
        self.model.record_trade(trade)
        self.total_invested += dca_size
        
        pos.total_invested = new_cumulative
        pos.buy_records.append(trade)
        pos.dca_complete = True
        
        total_value = sum(r.price_multiplier * r.position_size_usd for r in pos.buy_records)
        pos.weighted_avg_entry = total_value / pos.total_invested
    
    # =========================================================================
    # EXIT
    # =========================================================================
    
    def _evaluate_exit(self, pos: 'OpenPosition'):
        current_price = self.model.get_price_at(pos.token, self.model.day, 14)
        current_mult  = current_price / pos.entry_price
        
        if current_price > pos.peak_price:
            pos.peak_price = current_price
        
        if self.model.day == pos.entry_day:
            return
        
        if self.llm_chain is not None:
            decision = self._llm_exit_decision(pos, current_price, current_mult)
        else:
            decision = self._deterministic_exit_decision(pos, current_price, current_mult)
        
        if decision['action'] == 'hold':
            return
        
        if decision['action'] in ('partial_exit', 'full_exit'):
            pct_to_sell = decision.get('pct', 1.0)
            self._execute_sell(pos, current_price, pct_to_sell)
    
    def _deterministic_exit_decision(
        self,
        pos: 'OpenPosition',
        current_price: float,
        current_mult: float,
    ) -> Dict:
        ep = self.personality.exit_personality
        
        if ep == ExitPersonality.SCALPER:
            if current_mult >= 2.0 and not pos.first_partial_taken:
                pos.first_partial_taken = True
                return {'action': 'partial_exit', 'pct': 0.80}
            if current_mult >= 3.0:
                return {'action': 'full_exit', 'pct': 1.0}
        
        elif ep == ExitPersonality.PARTIAL_TAKER:
            if current_mult >= 3.0 and not pos.first_partial_taken:
                pos.first_partial_taken = True
                return {'action': 'partial_exit', 'pct': 0.40}
            if current_mult >= 8.0 and not pos.second_partial_taken:
                pos.second_partial_taken = True
                return {'action': 'partial_exit', 'pct': 0.35}
        
        elif ep == ExitPersonality.DIAMOND_HANDS:
            drawdown_from_peak = (pos.peak_price - current_price) / pos.peak_price
            if drawdown_from_peak > 0.70:
                return {'action': 'full_exit', 'pct': 1.0}
        
        elif ep == ExitPersonality.TRAILING_STOPPER:
            drawdown_from_peak = (pos.peak_price - current_price) / pos.peak_price
            if pos.peak_price > pos.entry_price * 2.0:
                if drawdown_from_peak > 0.25:
                    return {'action': 'full_exit', 'pct': 1.0}
        
        elif ep == ExitPersonality.CHAOS:
            if current_mult >= 1.5:
                roll = random.random()
                if roll < 0.15:
                    return {'action': 'full_exit', 'pct': 1.0}
                elif roll < 0.30:
                    return {'action': 'partial_exit', 'pct': random.uniform(0.20, 0.60)}
        
        days_held = self.model.day - pos.entry_day
        if days_held >= 25:
            return {'action': 'full_exit', 'pct': 1.0}
        
        if pos.total_invested < 75:
            return {'action': 'full_exit', 'pct': 1.0}
        
        return {'action': 'hold'}
    
    def _llm_exit_decision(
        self,
        pos: 'OpenPosition',
        current_price: float,
        current_mult: float,
    ) -> Dict:
        try:
            market_context = f"Current market: {self.model.market_state.value}"
            position_context = (
                f"Token: {pos.token.symbol} | "
                f"Entry: {pos.entry_price:.3f}x from launch | "
                f"Current: {current_price:.3f}x | "
                f"Multiple from entry: {current_mult:.2f}x | "
                f"Peak: {pos.peak_price:.3f}x | "
                f"Days held: {self.model.day - pos.entry_day} | "
                f"Position size: ${pos.total_invested:.0f}"
            )
            
            background_context = ""
            if self.background:
                bg_results = self.background.search_short_memory_by_doc(
                    [f"exit decision {pos.token.symbol}"]
                )
                if bg_results and bg_results[0]:
                    background_context = " | ".join(bg_results[0][:2])
            
            chain_input = {
                'personality':   self.personality.name,
                'market':        market_context,
                'position':      position_context,
                'background':    background_context,
                'recent_trades': self._get_recent_trade_summary(),
            }
            
            self.llm_chain.set_input(chain_input)
            self.llm_chain.run_step()
            output = self.llm_chain.get_output()
            
            if 'json' in output:
                decision = output['json']
                if decision.get('action') in ('hold', 'partial_exit', 'full_exit'):
                    return decision
            
        except Exception as e:
            print(f"[AGENT:{self.personality.name}] LLM exit failed: {e} — using deterministic")
        
        return self._deterministic_exit_decision(pos, current_price, current_mult)
    
    def _execute_sell(self, pos: 'OpenPosition', current_price: float, pct: float):
        """Record a sell trade and close/partially close the position."""
        
        sell_size  = pos.total_invested * pct
        exit_price = PriceCurveGenerator.get_realistic_exit_price(
            pos.token.curve,
            (self.model.day - pos.token.launch_day) * 24,
            sell_size,
            self.model.market_state,
        )
        
        roi_mult = exit_price / pos.entry_price
        roi_pct  = (roi_mult - 1) * 100
        realized = sell_size * roi_mult

        # ── Bug 1 fix: stamp ATH at record time ───────────────────────────────
        ath = (
            self.model.active_tokens[pos.token.address].curve.ath_multiplier
            if pos.token.address in self.model.active_tokens else 0.0
        )
        
        trade = TradeRecord(
            wallet_address           = self.wallet_address,
            token_address            = pos.token.address,
            token_symbol             = pos.token.symbol,
            side                     = 'sell',
            price_multiplier         = exit_price,
            position_size_usd        = sell_size,
            cumulative_invested      = pos.total_invested,
            day                      = self.model.day,
            hour                     = random.randint(8, 20),
            buy_hour_offset          = 0,
            is_dca                   = False,
            roi_at_exit              = roi_pct,
            pct_position_sold        = pct,
            launch_to_ath_multiplier = ath,          # ← stamped
        )
        self.model.record_trade(trade)
        self.total_realized += realized
        
        if pct >= 1.0 or pos.remaining_pct - pct <= 0.05:
            self.closed_trades.append(ClosedTrade(
                token_symbol    = pos.token.symbol,
                total_invested  = pos.total_invested,
                total_realized  = realized,
                roi_mult        = roi_mult,
                ath_mult        = pos.token.curve.ath_multiplier,
                entry_mult      = pos.entry_price,
                days_held       = self.model.day - pos.entry_day,
                qualifies_30x   = pos.token.qualifies,
                position_size   = pos.total_invested,
                captured_pct    = (exit_price / pos.token.curve.ath_multiplier),
                buy_count       = len(pos.buy_records),
            ))
            del self.open_positions[pos.token.address]
        else:
            pos.total_invested *= (1 - pct)
            pos.remaining_pct  -= pct
    
    # =========================================================================
    # DEGRADATION HOOKS — override in subclasses
    # =========================================================================
    
    def _should_degrade(self) -> bool:
        return False
    
    def _apply_degradation(self):
        pass
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _effective_participation_rate(self) -> float:
        state = self.model.market_state
        if state == MarketState.BULL:
            mult = self.personality.bull_activity_mult
        elif state == MarketState.BEAR:
            mult = self.personality.bear_activity_mult
        elif state == MarketState.CRASH:
            mult = self.personality.crash_activity_mult
        else:
            mult = 1.0
        return min(1.0, self.personality.participation_rate * mult)
    
    def _get_recent_trade_summary(self) -> str:
        if not self.closed_trades:
            return "No closed trades yet."
        recent = self.closed_trades[-5:]
        summaries = [
            f"{t.token_symbol} {t.roi_mult:.1f}x ({'W' if t.roi_mult >= 5 else 'L'})"
            for t in recent
        ]
        return " | ".join(summaries)
    
    def get_performance_summary(self) -> Dict:
        wins     = sum(1 for t in self.closed_trades if t.roi_mult >= 5.0)
        total    = len(self.closed_trades)
        win_rate = (wins / total * 100) if total > 0 else 0.0
        
        qualifying = [t for t in self.closed_trades if t.qualifies_30x]
        avg_entry_to_ath = (
            statistics.mean([t.ath_mult / t.entry_mult for t in qualifying])
            if qualifying else 0.0
        )
        
        recent_sizes    = [t.position_size for t in self.closed_trades[-10:]]
        avg_recent_size = statistics.mean(recent_sizes) if recent_sizes else 0.0
        
        roi_mults = [t.roi_mult for t in self.closed_trades]
        avg_roi   = statistics.mean(roi_mults) if roi_mults else 0.0
        
        runners_30d = sum(
            1 for t in self.closed_trades[-30:]
            if t.qualifies_30x and t.roi_mult >= 5.0
        )
        
        return {
            'wallet_address':     self.wallet_address,
            'name':               self.personality.name,
            'total_trades':       total,
            'win_rate':           round(win_rate, 1),
            'avg_roi_multiplier': round(avg_roi, 2),
            'avg_entry_to_ath':   round(avg_entry_to_ath, 2),
            'runners_30d':        runners_30d,
            'avg_position_usd':   round(avg_recent_size, 2),
            'total_invested':     round(self.total_invested, 2),
            'total_realized':     round(self.total_realized, 2),
            'open_positions':     len(self.open_positions),
            'is_active':          self.is_active,
        }


# =============================================================================
# OPEN / CLOSED POSITION DATACLASSES
# =============================================================================

@dataclass
class OpenPosition:
    token:              SimulatedToken
    entry_day:          int
    entry_hour:         int
    entry_price:        float
    total_invested:     float
    buy_records:        List[TradeRecord]
    peak_price:         float
    
    weighted_avg_entry:    float = 0.0
    dca_complete:          bool  = False
    first_partial_taken:   bool  = False
    second_partial_taken:  bool  = False
    remaining_pct:         float = 1.0


@dataclass
class ClosedTrade:
    token_symbol:   str
    total_invested: float
    total_realized: float
    roi_mult:       float
    ath_mult:       float
    entry_mult:     float
    days_held:      int
    qualifies_30x:  bool
    position_size:  float
    captured_pct:   float
    buy_count:      int