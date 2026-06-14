# Copy-trade DB migration — apply order & verification

Apply these in the **Supabase SQL editor** (schema `sifter_dev`), in order. All are
idempotent and transaction-wrapped, so re-running is safe.

## Run order

1. **`SETUP_ALL.sql`** — one-shot. Creates the 6 tables and seeds the roster + variant grid:
   - `paper_raw_cobuys`, `paper_price_paths` (record-once substrate)
   - `paper_variants`, `paper_variant_signals` (score-many grid)
   - `copy_wallets` (124 wallets), `copy_clusters` (12 clusters, 3 flagged `is_bot_cluster`)
   - seeds **124 wallets / 12 clusters / 257 variants**

2. **`bot_defaults_setup.sql`** — creates `bot_defaults` (singleton config row) and loads
   `bot_defaults.json` (SL/TP, trade limits, confluence sizing). The bot reads SL/TP/sizing/limits
   from this table via `services/copytrade_config.py` instead of hardcoding them.

3. **`auto_trade_limits_addendum.sql`** — sets existing auto-trade users to `daily=4, hourly=2`.

4. **`single_copy_optin.sql`** — creates `bot_single_copy_optins` for the opt-in (default-OFF)
   gated single-wallet copy path (STEP 7). Safe to apply even if unused.

## Verification queries

```sql
-- 6 tables present
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'sifter_dev'
  AND table_name IN ('paper_raw_cobuys','paper_price_paths','paper_variants',
                     'paper_variant_signals','copy_wallets','copy_clusters')
ORDER BY table_name;          -- expect 6 rows

-- seed counts: expect 124 / 12 / 257
SELECT (SELECT count(*) FROM sifter_dev.copy_wallets)  AS wallets,
       (SELECT count(*) FROM sifter_dev.copy_clusters) AS clusters,
       (SELECT count(*) FROM sifter_dev.paper_variants) AS variants;

-- 3 bot clusters
SELECT cluster_id, shrunk_runner_rate_pct, nonrunner_ev_pct, min_members_to_fire, co_entry_window_s
FROM sifter_dev.copy_clusters WHERE is_bot_cluster = true ORDER BY cluster_id;

-- bot_defaults loaded
SELECT version,
       config->'trade_limits'->>'daily_max'  AS daily,
       config->'trade_limits'->>'hourly_max' AS hourly,
       config->'confluence_sizing'->>'base_pct_per_trade' AS base_pct
FROM sifter_dev.bot_defaults;   -- expect bot_defaults_v1 / 4 / 2 / 10
```

## Notes
- `seed_clusters_wallets.sql` is **superseded** by `SETUP_ALL.sql` (roster-only; kept for reference).
- The Python layer (`services/copytrade_config.py`) falls back to the JSON seeds in this folder if
  the DB tables are empty, so code paths don't hard-fail before the migration is applied — but the
  DB is the source of truth once seeded.
