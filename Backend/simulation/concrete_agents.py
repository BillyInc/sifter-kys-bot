"""
concrete_agents.py

Concrete agent implementations — subclasses of TraderAgentBase.

FIXES IN THIS VERSION:

  Bug 1 (ATH stamp) — _record_trade_with_ath() stubs removed from all agents.
    ATH stamping is now handled in TraderAgentBase._enter_position(),
    _dca_into_position(), and _execute_sell(). The per-agent stubs were never
    called and are now gone. BoomBustBecky's _inject_big_win() still manually
    stamps ATH on the injected trades since it bypasses the base class methods.

  Bug 5 (Izzy inactivity timing) — InactiveIzzyAgent._should_degrade() changed
    from model.day > 7 to model.day >= 7. She now goes inactive at the START of
    Day 7's step (last trade = Day 6). By the Day 14 assertion check, exactly 8
    days have elapsed since her last trade, cleanly crossing the >7 threshold and
    firing the inactivity alert. _went_inactive_day is also now exposed via
    get_inactive_day() so the harness can pass the exact day into the wallet
    payload for precise alert messaging.

  Bug 7 (Clara bursts into crash) — ClusterClaraAgent.step() now checks market
    state before activating burst mode. Burst will not start if the model is in
    CRASH state. If a burst is already active when a crash begins, it ends early.
"""

import random
from typing import Optional, Dict
from trader_agent_base import (
    TraderAgentBase,
    AgentPersonality,
    ExitPersonality,
    DCAPersonality,
    PERSONALITY_STEADY_EDDIE,
    PERSONALITY_MOMENTUM_MARCUS,
    PERSONALITY_HOT_STREAK_HANK,
    PERSONALITY_VOLATILE_VICTOR,
    PERSONALITY_CLUSTER_CLARA,
    PERSONALITY_INACTIVE_IZZY,
    PERSONALITY_BOOM_BUST_BECKY,
    PERSONALITY_LATE_LARRY,
    PERSONALITY_RISING_RHONDA,
    PERSONALITY_CONSISTENT_CARLOS,
)
from solana_market_model import SolanaMarketModel, MarketState, TradeRecord


# =============================================================================
# BACKGROUND FACTORY SEED CONTENT
# =============================================================================

BACKGROUND_CONTENT = {

    "Steady Eddie": [
        "I enter tokens within the first hour of launch. I never chase pumps that are already 5x or more from launch.",
        "I always take my first partial profit at 3-4x from my entry. I never let a 3x turn into a loss.",
        "I have learned that holding more than 25 days on a Solana memecoin is almost always a mistake.",
        "When the market is in crash mode I stop trading entirely. Preserving capital is more important than catching a pump.",
        "I target tokens that show early volume and have at least $50k liquidity. Anything below that is too risky to size properly.",
        "My exit rule: take 40% off at 4x entry, take another 35% off at 8x entry, let the remaining 25% ride.",
        "I never average up more than once. If I DCA, it's within the first 3 hours and only if the token dips back toward launch price.",
        "A 200%+ week is a signal to be more careful, not more aggressive. Markets reverse fast on Solana.",
    ],

    "Momentum Marcus": [
        "I am a momentum trader. I enter when I see early volume surge and exit when momentum fades.",
        "My trailing stop is 25% from the peak price. Once a token drops 25% from its high I exit fully.",
        "I accept slightly later entries (1-4 hours post launch) in exchange for higher confirmation before entering.",
        "I sometimes enter tokens that are already 2-3x from launch if momentum indicators are strong.",
        "In bear markets I reduce size by 40% but don't stop trading. There are always opportunities even in down markets.",
        "I take first profits at 3x from my entry. I never hold through a full round-trip back to entry.",
    ],

    "Hot Streak Hank": [
        "I trade with high conviction. When I find a good token I go in with full size and hold.",
        "My best periods are when I find a cluster of runners in the same week — one good week can define the month.",
        "I struggle to stay disciplined when my performance dips. I start second-guessing entries I would normally take.",
        "When I'm in a cold streak I tend to over-trade or under-trade — both hurt my metrics.",
        "I have noticed my win rate drops significantly when the market shifts from bull to neutral without warning.",
        "Recent performance has been disappointing. I am being more selective but also missing opportunities.",
        "I have not hit a 10x+ runner in 2 weeks. Starting to question my token selection criteria.",
    ],

    "Volatile Victor": [
        "I trade high volume because I believe more shots at goal = more runners hit, even if win rate is lower.",
        "I don't have a consistent exit strategy. Sometimes I scalp, sometimes I diamond hand. I adapt to the feel of each trade.",
        "My position sizes are deliberately smaller than other traders so I can enter more tokens without overexposure.",
        "I DCA frequently — I often spread my buy across 4-6 hours to get a better average entry.",
        "I accept that 50% of my trades will not hit 5x. The 50% that do more than compensate.",
        "Victor's strength is volume and diversification. Victor's weakness is lack of exit discipline.",
    ],

    "Cluster Clara": [
        "I trade in bursts. When conditions align I enter 5-8 tokens in a 48 hour window.",
        "Long quiet periods are intentional — I wait for clear market signals before activating.",
        "My cluster trading behavior means I generate multiple simultaneous alerts for users. This is by design.",
        "When I am active I am very active. When I am quiet it means market conditions don't meet my entry criteria.",
        "I take first profits quickly — usually at 3x — because I have many open positions simultaneously.",
    ],

    "Inactive Izzy": [
        "I was very active in week 1 but have since paused trading for personal reasons.",
        "I am not monitoring the market currently. My watchlist activity has dropped to zero.",
        "Previous trades in week 1 were genuine — the inactivity is situational not performance-based.",
        "When I return I will likely trade similarly to before. This is a temporary pause.",
    ],

    "Boom Bust Becky": [
        "I make large concentrated bets. When I win I win big. When I lose I lose big.",
        "I do not diversify. I believe in finding one exceptional token and putting serious size in.",
        "My $WIF500 trade was a 200x. That single trade defines my historical metrics but is not representative of typical performance.",
        "I hold positions for a long time — often 3-4 weeks — because I believe in letting winners run fully.",
        "My consistency score is low because my results are extremely variable. This is intentional.",
    ],

    "Late Larry": [
        "I wait for confirmation before entering. I never buy in the first hour of a token launch.",
        "By the time I enter, the token has usually already moved 2-5x from launch. I accept this cost for higher confidence.",
        "My entry-to-ATH multiplier is always lower than early traders but my conviction on entries is higher.",
        "I frequently DCA into positions starting from hour 4 post-launch and again at hour 12 if the token holds up.",
        "In volatile markets my SNIPER approach protects me from rugging on low-quality launches.",
    ],

    "Rising Rhonda": [
        "I have been consistently improving over the past 3 weeks. My entry timing is getting earlier.",
        "I model my approach on early-entry traders. I am learning to trust initial signals faster.",
        "My recent win rate of 72% is the best I have achieved and I believe it reflects genuine skill improvement.",
        "I size conservatively but consistently. My position sizes never drop below $130.",
        "I am a strong candidate to replace any degrading wallet because my trajectory is improving not declining.",
    ],

    "Consistent Carlos": [
        "Consistency is my primary metric. I would rather hit 10 solid 5-7x trades than one 50x and nine losses.",
        "My position size variance is deliberately tight. I never let emotion push me to over-size or under-size.",
        "I have not missed a qualifying runner in the last 30 days. Participation rate is a discipline, not an accident.",
        "My entry timing is reliable — always within 3 hours of launch for tokens I choose to enter.",
        "I am the most predictable wallet in any watchlist. Users can rely on my signal consistency.",
    ],
}


# =============================================================================
# CONCRETE AGENTS
# =============================================================================

class SteadyEddieAgent(TraderAgentBase):
    """
    The benchmark wallet. Should always be Elite zone, no degradation.
    """
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        super().__init__(
            unique_id, model,
            PERSONALITY_STEADY_EDDIE,
            wallet_address, llm_chain, background
        )
        if self.background:
            self.background.add_backgrounds(
                BACKGROUND_CONTENT["Steady Eddie"],
                bg_type_list=["trading_rule"] * len(BACKGROUND_CONTENT["Steady Eddie"])
            )

    def _should_degrade(self) -> bool:
        return False


class MomentumMarcusAgent(TraderAgentBase):
    """Tier A. Slightly later entries than Eddie. Uses trailing stop exits."""
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        super().__init__(
            unique_id, model,
            PERSONALITY_MOMENTUM_MARCUS,
            wallet_address, llm_chain, background
        )
        if self.background:
            self.background.add_backgrounds(
                BACKGROUND_CONTENT["Momentum Marcus"],
                bg_type_list=["trading_rule"] * len(BACKGROUND_CONTENT["Momentum Marcus"])
            )


class HotStreakHankAgent(TraderAgentBase):
    """
    Tier A → degrades to C over weeks 3-4.

    Degradation schedule:
      Week 0-1: Full performance (80% participation, 85% quality, 72% win rate)
      Week 2:   Early signs (participation drops 20%)
      Week 3:   Clear decline (participation 30%, quality 40%, win rate 35%)
      Week 4:   Critical (participation 10%, tiny positions, no runners)
    """
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        super().__init__(
            unique_id, model,
            PERSONALITY_HOT_STREAK_HANK,
            wallet_address, llm_chain, background
        )
        self._degradation_applied_week = -1

        if self.background:
            self.background.add_backgrounds(
                BACKGROUND_CONTENT["Hot Streak Hank"][:5],
                bg_type_list=["trading_rule"] * 5
            )

    def _should_degrade(self) -> bool:
        return self.current_week >= 2 and self._degradation_applied_week < self.current_week

    def _apply_degradation(self):
        self._degradation_applied_week = self.current_week
        week = self.current_week

        if week == 2:
            self.personality.participation_rate = 0.55
            self.personality.quality_rate       = 0.65
            print(f"[HANK] Week 2 decline — participation: 55%, quality: 65%")

        elif week == 3:
            self.personality.participation_rate = 0.30
            self.personality.quality_rate       = 0.40
            self.personality.win_rate           = 0.35
            self.personality.avg_position_usd   = 150.0

            if self.background:
                self.background.add_backgrounds(
                    BACKGROUND_CONTENT["Hot Streak Hank"][5:],
                    bg_type_list=["current_state"] * 2
                )
            print(f"[HANK] Week 3 decline — participation: 30%, quality: 40%, win rate: 35%")

        elif week >= 4:
            self.personality.participation_rate = 0.10
            self.personality.quality_rate       = 0.25
            self.personality.win_rate           = 0.25
            self.personality.avg_position_usd   = 80.0
            print(f"[HANK] Week 4+ CRITICAL — barely trading")


class VolatileVictorAgent(TraderAgentBase):
    """High volume, inconsistent quality. Should never outscore Eddie."""
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        super().__init__(
            unique_id, model,
            PERSONALITY_VOLATILE_VICTOR,
            wallet_address, llm_chain, background
        )
        if self.background:
            self.background.add_backgrounds(
                BACKGROUND_CONTENT["Volatile Victor"],
                bg_type_list=["trading_rule"] * len(BACKGROUND_CONTENT["Volatile Victor"])
            )


class ClusterClaraAgent(TraderAgentBase):
    """
    Trades in bursts — 5-8 tokens in 48h windows, then silence.

    Bug 7 fix: burst activation now checks market state. Clara will not start
    a burst during CRASH — buying into a crash with doubled participation
    produces near-zero quality trades that pollute her metrics and cluster
    alert test data. If a burst is already running when a crash begins, it
    ends early and participation resets.
    """
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        super().__init__(
            unique_id, model,
            PERSONALITY_CLUSTER_CLARA,
            wallet_address, llm_chain, background
        )
        self._in_burst_mode   = False
        self._burst_day_start = -1
        self._burst_duration  = 2
        self._burst_interval  = 7
        self._saved_rate      = None

        if self.background:
            self.background.add_backgrounds(
                BACKGROUND_CONTENT["Cluster Clara"],
                bg_type_list=["trading_rule"] * len(BACKGROUND_CONTENT["Cluster Clara"])
            )

    def step(self):
        days_since_last_burst = (
            (self.model.day - self._burst_day_start)
            if self._burst_day_start > 0 else 999
        )

        is_crash = self.model.market_state == MarketState.CRASH

        if not self._in_burst_mode:
            # Bug 7 fix: do not start a burst during a crash
            if days_since_last_burst >= self._burst_interval and not is_crash:
                self._in_burst_mode   = True
                self._burst_day_start = self.model.day
                self._saved_rate      = self.personality.participation_rate
                self.personality.participation_rate = min(
                    1.0, self.personality.participation_rate * 2.0
                )
                print(f"[CLARA] Day {self.model.day} — BURST MODE activated")
        else:
            # Bug 7 fix: end burst early if market crashes mid-burst
            burst_expired = self.model.day - self._burst_day_start >= self._burst_duration
            if burst_expired or is_crash:
                self._in_burst_mode = False
                if self._saved_rate is not None:
                    self.personality.participation_rate = self._saved_rate
                reason = "burst ended" if burst_expired else "crash — burst cancelled early"
                print(f"[CLARA] Day {self.model.day} — {reason}, going quiet")

        super().step()

    def is_in_burst(self) -> bool:
        return self._in_burst_mode


class InactiveIzzyAgent(TraderAgentBase):
    """
    Active week 1 only. Then completely stops.
    Tests: inactivity alert cascade (yellow → orange → red over time).

    Bug 5 fix: _should_degrade() changed from model.day > 7 to model.day >= 7.
      She goes inactive at the START of Day 7's step before any trading, so her
      last trade is from Day 6. By the Day 14 assertion check, 8 days have elapsed
      (14 - 6 = 8 > 7), cleanly triggering the inactivity alert.

      _went_inactive_day is exposed via get_inactive_day() so build_watchlist_for_service
      can embed the exact day in the wallet payload. _detect_degradation then uses
      model.day - went_inactive_day for precise integer arithmetic rather than fuzzy
      last_trade_time subtraction that loses intra-day hours.
    """
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        super().__init__(
            unique_id, model,
            PERSONALITY_INACTIVE_IZZY,
            wallet_address, llm_chain, background
        )
        self._went_inactive_day = -1

        if self.background:
            self.background.add_backgrounds(
                BACKGROUND_CONTENT["Inactive Izzy"],
                bg_type_list=["context"] * len(BACKGROUND_CONTENT["Inactive Izzy"])
            )

    def _should_degrade(self) -> bool:
        # Bug 5 fix: >= 7 not > 7
        # Goes inactive at start of Day 7 step → last trade is Day 6
        # → 8 days elapsed by Day 14 assertion → inactivity alert fires
        return self.model.day >= 7 and self.is_active

    def _apply_degradation(self):
        self.is_active          = False
        self._went_inactive_day = self.model.day
        print(f"[IZZY] Day {self.model.day} — went INACTIVE")

    def get_inactive_day(self) -> int:
        """Expose exact inactivity day for wallet payload in build_watchlist_for_service."""
        return self._went_inactive_day


class BoomBustBeckyAgent(TraderAgentBase):
    """
    Makes one massive winning trade in week 1, then inconsistent.
    Tests: consistency score should reflect her boom-bust variance pattern.

    Note on consistency (Bug 4): the fix for this is in watchlist_manager.py and
    simulation_harness.py — _calculate_entry_consistency_score() is changed to
    measure buy_hour_offset variance (time-from-launch) instead of price variance.
    Becky has a wide range of entry hours across her trades, so her consistency
    score will be lower than Eddie's tightly-timed early entries.
    """
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        super().__init__(
            unique_id, model,
            PERSONALITY_BOOM_BUST_BECKY,
            wallet_address, llm_chain, background
        )
        self._big_win_injected = False

        if self.background:
            self.background.add_backgrounds(
                BACKGROUND_CONTENT["Boom Bust Becky"],
                bg_type_list=["trading_rule"] * len(BACKGROUND_CONTENT["Boom Bust Becky"])
            )

    def step(self):
        if self.model.day == 3 and not self._big_win_injected:
            self._inject_big_win()
        super().step()

    def _inject_big_win(self):
        """
        Manually inject a 200x trade to simulate Becky's historical big win.
        Stamps launch_to_ath_multiplier directly since this bypasses base class methods.
        """
        self._big_win_injected = True

        qualifying = [
            t for t in self.model.active_tokens.values()
            if t.qualifies and t.launch_day <= 3
        ]

        if not qualifying:
            print(f"[BECKY] No qualifying token available for big win injection")
            return

        token    = qualifying[0]
        invested = 800.0
        token_ath = token.curve.ath_multiplier

        buy_trade = TradeRecord(
            wallet_address           = self.wallet_address,
            token_address            = token.address,
            token_symbol             = token.symbol,
            side                     = 'buy',
            price_multiplier         = 1.0,
            position_size_usd        = invested,
            cumulative_invested      = invested,
            day                      = token.launch_day,
            hour                     = token.launch_hour + 1,
            buy_hour_offset          = 1,
            is_dca                   = False,
            launch_to_ath_multiplier = token_ath,    # ← stamped manually (bypasses base class)
        )
        self.model.record_trade(buy_trade)
        self.total_invested += invested

        exit_mult  = min(token_ath, 200.0)
        exit_price = exit_mult
        realized   = invested * exit_mult
        roi_pct    = (exit_mult - 1) * 100

        sell_trade = TradeRecord(
            wallet_address           = self.wallet_address,
            token_address            = token.address,
            token_symbol             = token.symbol,
            side                     = 'sell',
            price_multiplier         = exit_price,
            position_size_usd        = invested,
            cumulative_invested      = invested,
            day                      = self.model.day,
            hour                     = 14,
            buy_hour_offset          = 0,
            is_dca                   = False,
            roi_at_exit              = roi_pct,
            pct_position_sold        = 1.0,
            launch_to_ath_multiplier = token_ath,    # ← stamped manually
        )
        self.model.record_trade(sell_trade)
        self.total_realized += realized

        print(
            f"[BECKY] Big win injected — {token.symbol} at {exit_mult:.0f}x | "
            f"${realized:.0f} realized | token ATH: {token_ath:.1f}x"
        )


class LateLarryAgent(TraderAgentBase):
    """
    Enters 3-8 hours after launch. Good tokens, bad timing.
    Tests: entry timing score tanks Larry vs Eddie despite similar win rates.
    """
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        super().__init__(
            unique_id, model,
            PERSONALITY_LATE_LARRY,
            wallet_address, llm_chain, background
        )
        if self.background:
            self.background.add_backgrounds(
                BACKGROUND_CONTENT["Late Larry"],
                bg_type_list=["trading_rule"] * len(BACKGROUND_CONTENT["Late Larry"])
            )


# =============================================================================
# REPLACEMENT POOL
# =============================================================================

class RisingRhondaAgent(TraderAgentBase):
    """
    Improving trajectory. Should rank as top replacement candidate.
    quality_rate and participation_rate IMPROVE over time.
    """
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        super().__init__(
            unique_id, model,
            PERSONALITY_RISING_RHONDA,
            wallet_address, llm_chain, background
        )
        self._improvement_applied_week = -1

        if self.background:
            self.background.add_backgrounds(
                BACKGROUND_CONTENT["Rising Rhonda"],
                bg_type_list=["trading_rule"] * len(BACKGROUND_CONTENT["Rising Rhonda"])
            )

    def _should_degrade(self) -> bool:
        return self.current_week >= 1 and self._improvement_applied_week < self.current_week

    def _apply_degradation(self):
        self._improvement_applied_week = self.current_week
        week = self.current_week

        if week == 1:
            self.personality.quality_rate       = min(0.92, self.personality.quality_rate + 0.05)
            self.personality.participation_rate = min(0.90, self.personality.participation_rate + 0.05)
        elif week == 2:
            self.personality.win_rate           = min(0.80, self.personality.win_rate + 0.03)
        elif week >= 3:
            self.personality.entry_hour_range   = (0, 1)

        print(f"[RHONDA] Week {week} improvement applied")


class ConsistentCarlosAgent(TraderAgentBase):
    """
    Lower ROI than Eddie but extremely stable.
    Tests: tight position variance → high consistency score.
    """
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        super().__init__(
            unique_id, model,
            PERSONALITY_CONSISTENT_CARLOS,
            wallet_address, llm_chain, background
        )
        if self.background:
            self.background.add_backgrounds(
                BACKGROUND_CONTENT["Consistent Carlos"],
                bg_type_list=["trading_rule"] * len(BACKGROUND_CONTENT["Consistent Carlos"])
            )


class FlashInThePanFrankAgent(TraderAgentBase):
    """
    One incredible week (week 1), then silent.
    Should NOT be promoted ahead of Rhonda or Carlos.
    Tests: single-week flukes filtered by promotion queue.
    """
    def __init__(self, unique_id, model, wallet_address, llm_chain=None, background=None):
        flash_personality = AgentPersonality(
            name                = "Flash-in-the-Pan Frank",
            participation_rate  = 0.90,
            entry_hour_range    = (0, 1),
            quality_rate        = 0.95,
            win_rate            = 0.85,
            avg_position_usd    = 500.0,
            position_std        = 50.0,
            min_position_usd    = 200.0,
            exit_personality    = ExitPersonality.DIAMOND_HANDS,
            dca_personality     = DCAPersonality.ONE_SHOT,
            dca_probability     = 0.05,
            dca_spread_hours    = (1, 2),
            dca_size_pct        = 0.10,
            bull_activity_mult  = 1.0,
            bear_activity_mult  = 0.5,
            crash_activity_mult = 0.0,
        )
        super().__init__(
            unique_id, model, flash_personality,
            wallet_address, llm_chain, background
        )
        self._went_inactive_day = -1

    def _should_degrade(self) -> bool:
        return self.model.day > 7 and self.is_active

    def _apply_degradation(self):
        self.is_active          = False
        self._went_inactive_day = self.model.day
        print(f"[FRANK] Day {self.model.day} — went INACTIVE after one good week")


# =============================================================================
# AGENT FACTORY
# =============================================================================

def build_all_agents(
    model: SolanaMarketModel,
    include_replacements: bool = True,
    llm_factory=None,
    background_factory=None,
) -> Dict[str, TraderAgentBase]:
    """
    Instantiates all agents and registers them with the model.
    Returns dict: {wallet_address: agent_instance}
    """
    agents = {}

    def _make_bg(name):
        if background_factory is None:
            return None
        return background_factory.create_background(
            type('FakeAgent', (), {
                'component_id': name.replace(' ', '_').lower(),
                'context': {}
            })()
        )

    def _make_llm(name):
        if llm_factory is None:
            return None
        return llm_factory(name)

    specs = [
        ("WALLET_EDDIE_001",   SteadyEddieAgent),
        ("WALLET_MARCUS_002",  MomentumMarcusAgent),
        ("WALLET_HANK_003",    HotStreakHankAgent),
        ("WALLET_VICTOR_004",  VolatileVictorAgent),
        ("WALLET_CLARA_005",   ClusterClaraAgent),
        ("WALLET_IZZY_006",    InactiveIzzyAgent),
        ("WALLET_BECKY_007",   BoomBustBeckyAgent),
        ("WALLET_LARRY_008",   LateLarryAgent),
    ]

    if include_replacements:
        specs += [
            ("WALLET_RHONDA_009", RisingRhondaAgent),
            ("WALLET_CARLOS_010", ConsistentCarlosAgent),
            ("WALLET_FRANK_011",  FlashInThePanFrankAgent),
        ]

    for uid, (wallet_addr, AgentClass) in enumerate(specs):
        agent = AgentClass(
            unique_id      = uid,
            model          = model,
            wallet_address = wallet_addr,
            llm_chain      = _make_llm(AgentClass.__name__),
            background     = _make_bg(AgentClass.__name__),
        )
        model.schedule.add(agent)
        model.agent_list.append(agent)
        agents[wallet_addr] = agent

    print(f"\n[FACTORY] Built {len(agents)} agents")
    for addr, agent in agents.items():
        print(f"  {addr:<20} → {agent.personality.name}")
    print()

    return agents