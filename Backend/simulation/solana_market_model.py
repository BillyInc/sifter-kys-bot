"""
solana_market_model.py

The simulation environment. Controls:
  - Time (each step = 1 day)
  - Market state (bull / bear / crash / squeeze)
  - Token launches per day with realistic ATH distributions
  - Global runner leaderboard (what tokens are available to trade)
  - Price curve generation per token (so agents can decide when to exit)

MARKET REALISM NOTE:
  Real crypto market cycles last weeks-to-months, not days. A 30-day simulation
  window represents a single sustained market phase. We model this by:
    - Starting in BULL and keeping it mostly there (85% persistence)
    - Only allowing CRASH events (2-4 days) to briefly interrupt bull conditions
    - Bear/neutral periods are very short transitions before returning to bull
    - This mirrors a typical bull-run month in Solana memecoin markets

Does NOT connect to any real API. All data is synthetic.
Designed to be the foundation that TraderAgent steps on top of.
"""

import random
import statistics
import mesa
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum


# =============================================================================
# MARKET STATES
# =============================================================================

class MarketState(Enum):
    BULL      = "bull"       # 60%+ of tokens hit 30x ATH. High runner frequency.
    NEUTRAL   = "neutral"    # 35% hit 30x. Normal conditions.
    BEAR      = "bear"       # 15% hit 30x. Low runner frequency.
    CRASH     = "crash"      # 2-4 day event. Almost nothing pumps. Everyone loses.
    SQUEEZE   = "squeeze"    # Tokens pump but exit liquidity is thin.


# Probability that a token hits >= 30x ATH from launch, by market state
ATH_30X_PROB = {
    MarketState.BULL:    0.60,
    MarketState.NEUTRAL: 0.35,
    MarketState.BEAR:    0.15,
    MarketState.CRASH:   0.03,
    MarketState.SQUEEZE: 0.30,
}

# How many tokens launch per day, by market state
RUNNERS_PER_DAY = {
    MarketState.BULL:    (8, 14),   # (min, max)
    MarketState.NEUTRAL: (4, 8),
    MarketState.BEAR:    (1, 3),
    MarketState.CRASH:   (0, 1),
    MarketState.SQUEEZE: (3, 7),
}

# ─────────────────────────────────────────────────────────────────────────────
# SUSTAINED BULL MARKET TRANSITIONS
#
# Real memecoin bull runs last 4-12 weeks. In a 30-day window we expect:
#   - Bull dominates (~85% of days)
#   - Brief neutral dips (market cooling, 5-10% of days)
#   - Rare crash event (2-4 days max, ~5% chance any given day)
#   - No extended bear periods within a bull run
#
# To achieve this:
#   BULL     → BULL with 85% prob, neutral 10%, crash 5%
#   NEUTRAL  → returns to BULL with 75% prob (dip is temporary)
#   BEAR     → returns to NEUTRAL/BULL quickly (shouldn't persist in a bull run)
#   CRASH    → resolves to NEUTRAL then back to BULL (not bear)
# ─────────────────────────────────────────────────────────────────────────────
STATE_TRANSITIONS = {
    MarketState.BULL:    [
        (MarketState.BULL,    0.85),
        (MarketState.NEUTRAL, 0.10),
        (MarketState.CRASH,   0.05),
    ],
    MarketState.NEUTRAL: [
        (MarketState.BULL,    0.75),   # temporary dip — snaps back
        (MarketState.NEUTRAL, 0.20),
        (MarketState.BEAR,    0.05),   # rare in a bull run
    ],
    MarketState.BEAR:    [
        (MarketState.NEUTRAL, 0.60),   # bears don't persist in bull runs
        (MarketState.BULL,    0.35),
        (MarketState.CRASH,   0.05),
    ],
    MarketState.CRASH:   [
        (MarketState.CRASH,   0.40),   # crash lasts 2-4 days internally
        (MarketState.NEUTRAL, 0.45),   # resolves to neutral, not bear
        (MarketState.BULL,    0.15),   # v-shape recovery possible
    ],
    MarketState.SQUEEZE: [
        (MarketState.BULL,    0.55),
        (MarketState.NEUTRAL, 0.35),
        (MarketState.BEAR,    0.10),
    ],
}


# =============================================================================
# TOKEN DATA CLASSES
# =============================================================================

@dataclass
class PriceCurve:
    """
    A synthetic price curve for a token from launch to day 30.

    Real Solana tokens follow: fast pump → ATH → extended bleed.
    The curve is sampled at hourly intervals so agents can decide
    when to take profits based on their exit personality.

    Key fields:
      launch_price      — price at t=0 (always 1.0, everything is a multiplier)
      ath_multiplier    — peak price / launch price (e.g. 45.0 = 45x from launch)
      ath_hour          — which hour after launch the ATH occurred
      hourly_prices     — list of price multipliers, one per hour, up to 720h (30d)
    """
    launch_price:   float = 1.0
    ath_multiplier: float = 1.0
    ath_hour:       int   = 0
    hourly_prices:  List[float] = field(default_factory=list)

    # Liquidity — affects realistic exit size (squeeze market)
    liquidity_usd:  float = 50000.0

    # Security flags (pre-set at launch)
    mint_revoked:      bool = True
    liquidity_locked:  bool = True
    has_social:        bool = True


@dataclass
class SimulatedToken:
    """
    A token that launched today in the simulation.

    address:        fake address (token_day{day}_idx{idx})
    symbol:         e.g. $RUNNER7
    launch_day:     which simulation day it launched
    launch_hour:    0-23, which hour of the day
    curve:          full PriceCurve
    qualifies:      does it hit >= 30x ATH from launch? (the scoring threshold)
    """
    address:      str
    symbol:       str
    launch_day:   int
    launch_hour:  int
    curve:        PriceCurve
    qualifies:    bool        # True if ATH >= 30x from launch


@dataclass
class TradeRecord:
    """
    A single trade event. Recorded when an agent buys or sells.

    This is what your real services consume — the equivalent of
    what comes back from the SolanaTracker API in production.

    position_size_usd:  total USD value of this specific buy/sell leg
    cumulative_invested: running total of all buys into this token by this wallet
    is_dca:             True if this is not the first buy into this token
    buy_hour_offset:    hours after token launch this buy occurred (entry timing)
    launch_to_ath_multiplier: token's full ATH from launch price (for floor checks)
    """
    wallet_address:            str
    token_address:             str
    token_symbol:              str
    side:                      str        # 'buy' or 'sell'
    price_multiplier:          float      # price as multiplier from launch
    position_size_usd:         float      # size of THIS leg
    cumulative_invested:       float      # total invested so far (all buys)
    day:                       int
    hour:                      int
    buy_hour_offset:           int        # hours after token launch
    is_dca:                    bool = False
    roi_at_exit:               Optional[float] = None    # set when side='sell'
    pct_position_sold:         Optional[float] = None    # set when side='sell'
    launch_to_ath_multiplier:  float = 0.0               # token's ATH from launch


# =============================================================================
# PRICE CURVE GENERATOR
# =============================================================================

class PriceCurveGenerator:
    """
    Generates realistic synthetic price curves for Solana memecoins.

    Curve shape:
      Phase 1 (launch → ATH): fast exponential pump, hours 0-ATH_HOUR
      Phase 2 (ATH → bleed): gradual decline with volatility, ATH_HOUR onward

    Exit liquidity modeled in SQUEEZE market: high prices have thin orderbooks,
    so large sells move the price down against the agent.
    """

    @staticmethod
    def generate(
        market_state: MarketState,
        target_ath_mult: Optional[float] = None,
        noise_factor: float = 0.15,
    ) -> PriceCurve:
        """
        Generate one token's full price curve.

        target_ath_mult: if provided, build curve toward this ATH.
                         if None, draw from market-state distribution.
        noise_factor:    how much random noise on top of the base curve (0-1).
        """
        # ── Determine ATH ────────────────────────────────────────────────────
        if target_ath_mult is None:
            target_ath_mult = PriceCurveGenerator._draw_ath(market_state)

        # ── Determine when ATH occurs (hours after launch) ────────────────────
        # Bull: ATH often very early (1-6h). Bear: can be later (6-24h).
        if market_state in (MarketState.BULL, MarketState.SQUEEZE):
            ath_hour = random.randint(1, 8)
        elif market_state == MarketState.CRASH:
            ath_hour = random.randint(1, 4)     # quick pump then immediate crash
        else:
            ath_hour = random.randint(2, 18)

        # ── Determine liquidity ───────────────────────────────────────────────
        if market_state == MarketState.SQUEEZE:
            liquidity = random.uniform(15000, 60000)
        elif market_state == MarketState.BULL:
            liquidity = random.uniform(80000, 500000)
        else:
            liquidity = random.uniform(30000, 150000)

        # ── Build hourly price curve (720 hours = 30 days) ────────────────────
        hourly = [1.0]  # hour 0 = launch price = 1.0x

        for h in range(1, 721):
            if h <= ath_hour:
                # Pump phase: exponential approach to ATH
                progress  = h / ath_hour
                base_mult = 1.0 + (target_ath_mult - 1.0) * (progress ** 1.5)
            else:
                # Bleed phase: decay from ATH
                hours_past_ath = h - ath_hour

                # Most tokens bleed 70-90% from ATH over 30 days
                decay_rate = random.uniform(0.003, 0.008)
                base_mult  = target_ath_mult * (1 - decay_rate) ** hours_past_ath

                # Some tokens have "dead cat bounces"
                if random.random() < 0.02:
                    base_mult *= random.uniform(1.1, 1.5)

            # Add noise
            noise     = random.gauss(1.0, noise_factor * 0.3)
            price     = max(0.01, base_mult * noise)
            hourly.append(round(price, 4))

        actual_ath      = max(hourly)
        actual_ath_hour = hourly.index(actual_ath)

        return PriceCurve(
            launch_price     = 1.0,
            ath_multiplier   = round(actual_ath, 2),
            ath_hour         = actual_ath_hour,
            hourly_prices    = hourly,
            liquidity_usd    = round(liquidity, 2),
            mint_revoked     = True,
            liquidity_locked = True,
            has_social       = random.random() < 0.85,
        )

    @staticmethod
    def _draw_ath(market_state: MarketState) -> float:
        """Draw a target ATH multiplier from the market-state distribution."""
        prob_30x = ATH_30X_PROB[market_state]

        if random.random() < prob_30x:
            # Qualifying runner: 30x–200x from launch
            return random.choice([
                random.uniform(30, 50),
                random.uniform(50, 100),
                random.uniform(100, 200),
            ])
        else:
            # Non-qualifying: 2x–29x
            return random.uniform(2, 29)

    @staticmethod
    def get_price_at_hour(curve: PriceCurve, hour: int) -> float:
        """Get the token's price multiplier at a specific hour after launch."""
        idx = min(hour, len(curve.hourly_prices) - 1)
        return curve.hourly_prices[idx]

    @staticmethod
    def get_realistic_exit_price(
        curve: PriceCurve,
        hour: int,
        position_size_usd: float,
        market_state: MarketState,
    ) -> float:
        """
        In SQUEEZE markets, large positions move the price against you.
        Returns the realistic exit price multiplier accounting for slippage.
        """
        base_price = PriceCurveGenerator.get_price_at_hour(curve, hour)

        if market_state != MarketState.SQUEEZE:
            return base_price

        # Slippage: larger position vs liquidity = worse exit
        slippage_pct = min(0.30, position_size_usd / curve.liquidity_usd)
        return base_price * (1 - slippage_pct)


# =============================================================================
# SOLANA MARKET MODEL
# =============================================================================

class SolanaMarketModel(mesa.Model):
    """
    The simulation environment.

    Each step() = 1 day.

    MARKET DESIGN (30-day bull run):
      The simulation represents a sustained bull market month. Market state
      is initialised to BULL and transitions are weighted to stay there.
      Only short CRASH events (2-4 days) can significantly interrupt bull
      conditions. This is realistic — crypto bull runs don't flip to bear
      and back in a matter of days.

    Responsibilities:
      - Advance time
      - Transition market state (sustained bull bias)
      - Launch new tokens each day
      - Maintain a 30-day active token pool
      - Collect all trade records from agents
      - Expose methods your real services can call to get trade data
    """

    def __init__(
        self,
        initial_market_state: MarketState = MarketState.BULL,
        seed: Optional[int] = None,
    ):
        super().__init__()

        if seed is not None:
            random.seed(seed)

        # ── Time ─────────────────────────────────────────────────────────────
        self.day        = 0
        self.hour       = 0          # 0-23 within current day
        self.start_date = datetime(2025, 1, 1)

        # ── Market state ─────────────────────────────────────────────────────
        self.market_state           = initial_market_state
        self.market_state_history:  List[MarketState] = [initial_market_state]
        self.crash_days_remaining   = 0    # crash events last 2-4 days

        # ── Token pool ───────────────────────────────────────────────────────
        # All tokens launched in last 30 days
        self.active_tokens:  Dict[str, SimulatedToken] = {}
        # Tokens launched today (reset each step)
        self.todays_tokens:  List[SimulatedToken] = []

        # ── Trade ledger ─────────────────────────────────────────────────────
        # All trades across all agents, indexed by wallet_address
        self.all_trades: Dict[str, List[TradeRecord]] = {}

        # ── Agents ───────────────────────────────────────────────────────────
        self.schedule   = mesa.time.RandomActivation(self)
        self.agent_list = []

        # ── Stats ────────────────────────────────────────────────────────────
        self.daily_stats: List[Dict] = []

        print(f"[MARKET] Initialized | Day 0 | State: {self.market_state.value}")

    # =========================================================================
    # CORE STEP
    # =========================================================================

    def step(self):
        """
        Advance the simulation by one day.

        Order:
          1. Transition market state
          2. Launch today's tokens
          3. Step all agents (they observe tokens and decide to trade)
          4. Record daily stats
          5. Expire old tokens (> 30 days old)
        """
        self.day += 1

        # 1. Market state
        self._transition_market_state()

        # 2. Launch tokens
        self.todays_tokens = self._launch_todays_tokens()
        for token in self.todays_tokens:
            self.active_tokens[token.address] = token

        # 3. Agent steps
        self.schedule.step()

        # 4. Stats
        self._record_daily_stats()

        # 5. Expire tokens older than 30 days
        self._expire_old_tokens()

        print(
            f"[MARKET] Day {self.day:>3} | "
            f"State: {self.market_state.value:<8} | "
            f"Tokens launched: {len(self.todays_tokens):>2} | "
            f"Active tokens: {len(self.active_tokens):>3} | "
            f"Total trades: {self._total_trade_count():>4}"
        )

    # =========================================================================
    # MARKET STATE TRANSITIONS
    # =========================================================================

    def _transition_market_state(self):
        """
        Probabilistically transition to a new market state.

        Sustained bull bias: once in BULL, we stay there ~85% of days.
        CRASH events are special — they last 2-4 days then resolve to
        NEUTRAL (not BEAR), allowing quick recovery back to BULL.

        This models real memecoin bull runs where the dominant state
        is bull with only brief interruptions over a 30-day window.
        """
        if self.market_state == MarketState.CRASH:
            self.crash_days_remaining -= 1
            if self.crash_days_remaining <= 0:
                # Crash ends → resolve to neutral (will snap back to bull)
                options = [(MarketState.NEUTRAL, 0.65), (MarketState.BULL, 0.35)]
                self.market_state = self._weighted_choice(options)
        else:
            transitions = STATE_TRANSITIONS[self.market_state]
            new_state   = self._weighted_choice(transitions)

            if new_state == MarketState.CRASH and self.market_state != MarketState.CRASH:
                self.crash_days_remaining = random.randint(2, 4)

            self.market_state = new_state

        self.market_state_history.append(self.market_state)

    # =========================================================================
    # TOKEN LAUNCHES
    # =========================================================================

    def _launch_todays_tokens(self) -> List[SimulatedToken]:
        """
        Launch a batch of tokens today based on current market state.
        Each token gets a full 30-day price curve generated upfront.

        In reality tokens launch throughout the day at random hours.
        We model this so agents can have realistic "hours after launch" entry times.
        """
        min_count, max_count = RUNNERS_PER_DAY[self.market_state]
        count = random.randint(min_count, max_count)

        tokens     = []
        used_hours = set()

        for idx in range(count):
            # Each token launches at a different hour
            launch_hour = random.randint(0, 23)
            while launch_hour in used_hours and len(used_hours) < 24:
                launch_hour = random.randint(0, 23)
            used_hours.add(launch_hour)

            address = f"token_d{self.day:03d}_i{idx:02d}"
            symbol  = f"${self._random_ticker()}"
            curve   = PriceCurveGenerator.generate(self.market_state)

            token = SimulatedToken(
                address     = address,
                symbol      = symbol,
                launch_day  = self.day,
                launch_hour = launch_hour,
                curve       = curve,
                qualifies   = curve.ath_multiplier >= 30.0,
            )
            tokens.append(token)

        return tokens

    # =========================================================================
    # DATA ACCESS — called by agents and your real services
    # =========================================================================

    def get_tokens_available_at(self, day: int, hour: int) -> List[SimulatedToken]:
        """
        Tokens an agent could see and trade at a given day + hour.
        Only returns tokens that have already launched by this time.
        """
        return [
            t for t in self.active_tokens.values()
            if t.launch_day < day
            or (t.launch_day == day and t.launch_hour <= hour)
        ]

    def get_price_at(self, token: SimulatedToken, day: int, hour: int) -> float:
        """
        Get token price as a multiplier from launch at a specific point in time.
        hour_offset = total hours since launch.
        """
        hours_since_launch = (day - token.launch_day) * 24 + (hour - token.launch_hour)
        hours_since_launch = max(0, hours_since_launch)
        return PriceCurveGenerator.get_price_at_hour(token.curve, hours_since_launch)

    def record_trade(self, trade: TradeRecord):
        """Called by agents when they buy or sell."""
        if trade.wallet_address not in self.all_trades:
            self.all_trades[trade.wallet_address] = []
        self.all_trades[trade.wallet_address].append(trade)

    def get_wallet_trades(
        self,
        wallet_address: str,
        days_back: int = 7,
    ) -> List[TradeRecord]:
        """
        Returns trades for a wallet within the last N days.
        This is what your _get_recent_trades() equivalent calls
        instead of hitting Supabase.
        """
        cutoff_day = self.day - days_back
        trades     = self.all_trades.get(wallet_address, [])
        return [t for t in trades if t.day >= cutoff_day]

    def get_wallet_trades_as_dicts(
        self,
        wallet_address: str,
        days_back: int = 7,
    ) -> List[Dict]:
        """
        Same as get_wallet_trades but returns dicts matching
        the shape your real WatchlistLeagueManager._get_recent_trades() expects.

        Field mapping:
          side                     → 'buy' or 'sell'
          usd_value                → position_size_usd
          price_per_token          → price_multiplier (multiplier as proxy for price)
          block_time               → ISO timestamp
          roi_percent              → only set on sells
          token_address            → token_address
          token_ticker             → token_symbol
          launch_to_ath_multiplier → token's full ATH from launch (for floor checks)
        """
        raw    = self.get_wallet_trades(wallet_address, days_back)
        result = []

        for t in raw:
            sim_date = self.start_date + timedelta(days=t.day, hours=t.hour)
            entry = {
                'wallet_address':          t.wallet_address,
                'token_address':           t.token_address,
                'token_ticker':            t.token_symbol,
                'side':                    t.side,
                'usd_value':               t.position_size_usd,
                'price_per_token':         t.price_multiplier,
                'block_time':              sim_date.isoformat(),
                'roi_percent':             t.roi_at_exit if t.roi_at_exit else 0.0,
                'is_dca':                  t.is_dca,
                'buy_hour_offset':         t.buy_hour_offset,
                'launch_to_ath_multiplier': t.launch_to_ath_multiplier,
            }
            result.append(entry)

        return result

    def get_qualifying_runners_pool(self, days_back: int = 30) -> List[Dict]:
        """
        Returns the pool of qualifying runner tokens (ATH >= 30x from launch)
        from the last N days. This is what your promotion queue logic uses
        instead of calling find_trending_runners_enhanced().
        """
        cutoff_day = self.day - days_back
        runners    = []

        for token in self.active_tokens.values():
            if token.launch_day >= cutoff_day and token.qualifies:
                runners.append({
                    'address':        token.address,
                    'symbol':         token.symbol,
                    'ath_multiplier': token.curve.ath_multiplier,
                    'ath_hour':       token.curve.ath_hour,
                    'launch_day':     token.launch_day,
                    'liquidity_usd':  token.curve.liquidity_usd,
                    'qualifies_30x':  True,
                })

        return sorted(runners, key=lambda r: r['ath_multiplier'], reverse=True)

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _expire_old_tokens(self):
        """Remove tokens older than 30 days from active pool."""
        expired = [
            addr for addr, t in self.active_tokens.items()
            if self.day - t.launch_day > 30
        ]
        for addr in expired:
            del self.active_tokens[addr]

    def _record_daily_stats(self):
        total_trades = self._total_trade_count()
        qualifying   = sum(1 for t in self.todays_tokens if t.qualifies)

        self.daily_stats.append({
            'day':             self.day,
            'market_state':    self.market_state.value,
            'tokens_launched': len(self.todays_tokens),
            'qualifying_30x':  qualifying,
            'total_trades':    total_trades,
        })

    def _total_trade_count(self) -> int:
        return sum(len(v) for v in self.all_trades.values())

    @staticmethod
    def _weighted_choice(options: List[tuple]):
        """Choose from [(value, probability), ...] list."""
        values  = [o[0] for o in options]
        weights = [o[1] for o in options]
        return random.choices(values, weights=weights, k=1)[0]

    @staticmethod
    def _random_ticker() -> str:
        """Generate a random fake token ticker."""
        syllables = ['PEPE', 'DOGE', 'BONK', 'MOON', 'PUMP', 'FROG',
                     'CAT',  'DOG',  'WIF',  'MEME', 'APE',  'CHAD',
                     'BULL', 'SHIB', 'CORN', 'GOAT', 'FISH', 'BOOP']
        return random.choice(syllables) + str(random.randint(10, 99))

    # =========================================================================
    # SIMULATION SUMMARY — called after all steps complete
    # =========================================================================

    def summary(self) -> Dict:
        """Print and return a summary of the simulation run."""
        state_counts = {}
        for s in self.market_state_history:
            state_counts[s.value] = state_counts.get(s.value, 0) + 1

        total_qualifying = sum(
            1 for t in self.active_tokens.values() if t.qualifies
        )

        summary = {
            'total_days':         self.day,
            'market_states':      state_counts,
            'total_trades':       self._total_trade_count(),
            'active_tokens':      len(self.active_tokens),
            'qualifying_runners': total_qualifying,
            'agents':             len(self.agent_list),
        }

        print("\n" + "=" * 60)
        print("SIMULATION SUMMARY")
        print("=" * 60)
        for k, v in summary.items():
            print(f"  {k:<25} {v}")
        print("=" * 60 + "\n")

        return summary