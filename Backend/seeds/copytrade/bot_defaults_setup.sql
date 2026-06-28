-- =====================================================================
-- bot_defaults_setup.sql  —  load bot_defaults.json into a DB config row
-- Run AFTER SETUP_ALL.sql. Idempotent. Schema: sifter_dev.
-- The bot loads SL/TP, trade limits, and confluence sizing from here
-- (PAPER_TRADER_INSTRUCTIONS STEP 1) instead of hardcoding them.
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS sifter_dev.bot_defaults (
  id         BOOLEAN PRIMARY KEY DEFAULT TRUE,
  version    TEXT NOT NULL,
  config     JSONB NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT bot_defaults_singleton CHECK (id)
);

INSERT INTO sifter_dev.bot_defaults (id, version, config) VALUES (TRUE,
  'bot_defaults_v1',
  $json$
{
  "schema": "bot_defaults_v1",
  "market_phase": "bear",
  "_note": "BEAR-calibrated; refine SL/TP via paper-trade price paths + Monte Carlo (Phase K).",
  "sl_tp_strategy": {
    "principle": "14-32% of trades run 14-22x; ~70-80% are non-runners. EDGE = small stops on losers + UNCAPPED trailing on winners. A fixed take-profit DESTROYS the edge by capping the 20x runners.",
    "stop_loss_pct": -35,
    "_sl_note": "non-runner realized avg loss -24% to -51%; -35% caps catastrophe without cutting normal noise. BOT-2 bleeds more (-51%) -> tighter -30%.",
    "take_profit_ladder": [
      {
        "at_multiple": 2.0,
        "sell_pct": 25,
        "_why": "de-risk: recover stake early; non-runners rarely exceed ~1.2x so this mostly triggers on real movers"
      },
      {
        "at_multiple": 4.0,
        "sell_pct": 25,
        "_why": "lock a 2x on the position"
      }
    ],
    "trailing_stop_pct": -40,
    "_trail_note": "remaining 50% rides with a WIDE -40% trailing stop to capture the 14-22x median runner. DO NOT hard-cap.",
    "time_stop_min": "PENDING_OHLCV",
    "per_cluster_overrides": {
      "BOT-1": {
        "stop_loss_pct": -35,
        "reason": "non-runner EV +25%, win 63% -> looser stop OK"
      },
      "BOT-2": {
        "stop_loss_pct": -30,
        "reason": "non-runner EV -5%, avg loss -51% -> TIGHTEST stop; copy entry, our exit"
      },
      "BOT-3": {
        "stop_loss_pct": -35,
        "reason": "non-runner EV +3%, win 47% -> standard"
      }
    }
  },
  "trade_limits": {
    "daily_max": 4,
    "_daily": "quality cap; ranked top-4 by signal strength (raw is 34/day, mostly BOT-3/C7ML4W7c noise)",
    "hourly_max": 2,
    "_hourly": "bursts hit 11/hr; cap at 2 to spread entries + respect chase-guard",
    "weekly_max": 28,
    "_weekly": "~4/day x 7; circuit-breaker if exceeded",
    "selection": "RANK all cluster co-entries by signal strength, take top-N up to caps. Never fire blind."
  },
  "confluence_sizing": {
    "base_pct_per_trade": 10,
    "_base": "user rule: 10% of overall capital at a 2-member cluster co-entry",
    "ladder": [
      {
        "trigger": "2 cluster members co-buy (base signal)",
        "size_pct": 10
      },
      {
        "trigger": "ELITE wallet also present (or List-A best wallet co-buys)",
        "add_pct": 5,
        "_data": "ELITE present 11% vs 5% runner rate = 2.2x edge"
      },
      {
        "trigger": "5+ distinct tracked wallets co-buy",
        "add_pct": 5,
        "_data": "5+ co-buyers 10.7% vs 5.5% at 2 = ~2x edge"
      }
    ],
    "max_per_token_pct": 20,
    "_cap": "hard concentration cap 20% of capital on any one token",
    "pyramid_rule": "ADD to position as confirmations arrive ONLY IF chase-guard holds (fill <=1.5x your first entry). Else hold base size — never chase.",
    "_principle": "confluence raises runner rate ~2x -> size scales with confirmation, bounded by chase-guard + concentration cap"
  },
  "bot_can_copy_singles": {
    "default": false,
    "recommendation": "OPT-IN advanced. The 3 clusters are the safe default. If a user adds a List-A elite single, the bot auto-executes its buys ONLY when that buy ALSO has >=1 other tracked co-buyer (fold into confluence) + a separate per-wallet daily cap of 2. Reason: an elite does 100-400 tokens/30d; blind single-wallet auto-copy blows the budget and the 24-35% single RR < 44-53% cluster RR."
  }
}
$json$::jsonb)
ON CONFLICT (id) DO UPDATE SET
  version = EXCLUDED.version,
  config  = EXCLUDED.config,
  updated_at = NOW();

COMMIT;
