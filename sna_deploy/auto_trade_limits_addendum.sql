-- Addendum: update auto-trade defaults to data-grounded values
UPDATE sifter_dev.telegram_users SET
  auto_trade_daily_limit = 4,    -- was 8; quality cap (top-4 by strength)
  auto_trade_hourly_limit = 2     -- was 1; allows burst but spreads entries
WHERE auto_trade_source = 'elite15';
-- NOTE: rename source 'elite15' -> 'cluster' once paper_trader.py is cluster-aware (PAPER_TRADER_INSTRUCTIONS §4A).