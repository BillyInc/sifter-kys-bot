-- =====================================================================
-- ClickHouse: CLUSTER + PAIR rerank/replacement layer
-- Mirrors the existing per-wallet layer (wallet_token_stats -> mv_wallet_aggregate
-- -> wallet_aggregate_stats) for the NEW cluster and pair granularities.
-- COMPUTE lives here (ClickHouse). Supabase = operational config + backup only.
-- Metric parity with wallet layer: consistency_score = RUNNER-CAPTURE rate,
-- professional_score = composite HEALTH, wins/draws/losses = outcome taxonomy,
-- avg_roi_* = EV, last_active_at = staleness.
-- =====================================================================

-- 0. Extend the existing event logs so cluster trades attribute correctly.
--    (no-op if columns already added; ClickHouse ADD COLUMN IF NOT EXISTS)
ALTER TABLE bot_signal_log  ADD COLUMN IF NOT EXISTS cluster_id String DEFAULT '';
ALTER TABLE bot_trade_log   ADD COLUMN IF NOT EXISTS cluster_id String DEFAULT '';
ALTER TABLE bot_trade_log   ADD COLUMN IF NOT EXISTS variant_id String DEFAULT '';
ALTER TABLE bot_trade_log   ADD COLUMN IF NOT EXISTS is_runner  UInt8   DEFAULT 0;
ALTER TABLE bot_trade_log   ADD COLUMN IF NOT EXISTS realized_roi_mult Float64 DEFAULT 0;
ALTER TABLE bot_trade_log   ADD COLUMN IF NOT EXISTS outcome    String  DEFAULT '';  -- win|draw|loss|runner

-- =====================================================================
-- 1. CLUSTER granularity (mirror of wallet_token_stats -> aggregate)
-- =====================================================================
-- one row per (cluster, token) co-entry the bot/paper acted on, with our realized outcome
CREATE TABLE IF NOT EXISTS cluster_token_stats
(
    cluster_id        String,
    token_address     String,
    fired_at          DateTime,
    qualifies         UInt8   DEFAULT 1,          -- passed security + entry rules
    n_members_cobuy   UInt16  DEFAULT 2,          -- how many cluster members co-bought
    total_roi_mult    Float64 DEFAULT 0,          -- OUR realized multiple (with our SL/TP)
    roi_pct           Float64 DEFAULT 0,
    is_runner         UInt8   DEFAULT 0,          -- realized >= runner cut (>=10x token / our trail-capture)
    outcome           String  DEFAULT '',         -- win|draw|loss|runner
    total_spent_usd   Float64 DEFAULT 0,
    total_pnl_usd     Float64 DEFAULT 0,
    updated_at        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (cluster_id, token_address)
PARTITION BY toYYYYMM(fired_at);

CREATE TABLE IF NOT EXISTS cluster_aggregate_stats
(
    cluster_id            String,
    is_bot_cluster        UInt8   DEFAULT 0,
    signals               UInt32,
    signals_30d           UInt32  DEFAULT 0,
    wins                  UInt32,
    draws                 UInt32,
    losses                UInt32,
    win_rate              Float64,
    runner_capture_rate   Float64,                -- = consistency: runners / signals  (PRIMARY)
    avg_roi_pct           Float64 DEFAULT 0,       -- = EV  (PRIMARY)
    avg_roi_mult          Float64 DEFAULT 0,
    profit_factor         Float64 DEFAULT 0,       -- gains / |losses|  (PRIMARY, must stay > 1)
    nonrunner_ev_pct      Float64 DEFAULT 0,
    health_score          Float64,                 -- composite (= professional_score parity)
    last_active_at        DateTime,                -- staleness signal
    updated_at            DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (cluster_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_cluster_aggregate
TO cluster_aggregate_stats
AS
SELECT
    cluster_id,
    0                                                                       AS is_bot_cluster, -- set from config join in app
    count()                                                                 AS signals,
    countIf(fired_at >= now() - toIntervalDay(30))                          AS signals_30d,
    countIf(outcome = 'win' OR outcome = 'runner')                          AS wins,
    countIf(outcome = 'draw')                                               AS draws,
    countIf(outcome = 'loss')                                               AS losses,
    if(count() > 0, countIf(outcome IN ('win','runner','draw','loss')) > 0
        AND countIf(outcome IN ('win','runner')) * 100.0
            / countIf(outcome IN ('win','runner','draw','loss')), 0)        AS win_rate,
    if(count() > 0, countIf(is_runner = 1) * 100.0 / count(), 0)            AS runner_capture_rate,
    avg(roi_pct)                                                            AS avg_roi_pct,
    avg(total_roi_mult)                                                     AS avg_roi_mult,
    if(sumIf(roi_pct, roi_pct < 0) != 0,
        sumIf(roi_pct, roi_pct > 0) / abs(sumIf(roi_pct, roi_pct < 0)), 999) AS profit_factor,
    avgIf(roi_pct, is_runner = 0)                                           AS nonrunner_ev_pct,
    -- health: runner-capture + EV weighted; mirrors professional_score shape
    least(100, log(1 + avg(total_roi_mult)) * 100) * 0.4
        + if(count() > 0, countIf(is_runner = 1) * 100.0 / count(), 0) * 0.4
        + greatest(0, avg(roi_pct)) * 0.2                                   AS health_score,
    max(fired_at)                                                           AS last_active_at,
    now()                                                                   AS updated_at
FROM cluster_token_stats
WHERE qualifies = 1
GROUP BY cluster_id;

-- weekly snapshots for staleness/decay trend (mirror wallet_weekly_snapshots)
CREATE TABLE IF NOT EXISTS cluster_weekly_snapshots
(
    cluster_id          String,
    week_start          Date,
    signals             UInt32,
    runner_capture_rate Float64,
    avg_roi_pct         Float64,
    profit_factor       Float64,
    health_score        Float64,
    snapshot_at         DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(snapshot_at)
ORDER BY (cluster_id, week_start);

-- =====================================================================
-- 2. PAIR granularity (synergy health for re-clustering)
-- =====================================================================
CREATE TABLE IF NOT EXISTS pair_token_stats
(
    wallet_a          String,
    wallet_b          String,                      -- store sorted so (a,b) canonical
    token_address     String,
    fired_at          DateTime,
    is_runner         UInt8   DEFAULT 0,
    roi_pct           Float64 DEFAULT 0,
    outcome           String  DEFAULT '',
    updated_at        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (wallet_a, wallet_b, token_address)
PARTITION BY toYYYYMM(fired_at);

CREATE TABLE IF NOT EXISTS pair_aggregate_stats
(
    wallet_a            String,
    wallet_b            String,
    cobuys              UInt32,                     -- support
    runners             UInt32,
    runner_capture_rate Float64,                    -- raw; app applies shrinkage K=25
    avg_roi_pct         Float64,
    nonrunner_ev_pct    Float64,
    health_score        Float64,
    last_active_at      DateTime,
    updated_at          DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (wallet_a, wallet_b);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_pair_aggregate
TO pair_aggregate_stats
AS
SELECT
    wallet_a, wallet_b,
    count()                                          AS cobuys,
    countIf(is_runner = 1)                           AS runners,
    if(count() > 0, countIf(is_runner=1)*100.0/count(), 0) AS runner_capture_rate,
    avg(roi_pct)                                     AS avg_roi_pct,
    avgIf(roi_pct, is_runner = 0)                    AS nonrunner_ev_pct,
    least(100, log(1+avg(roi_pct)/100+1)*50)         AS health_score,
    max(fired_at)                                    AS last_active_at,
    now()                                            AS updated_at
FROM pair_token_stats
GROUP BY wallet_a, wallet_b;

-- NOTE: shrinkage (K=25) is applied in the app layer when ranking pairs:
--   shrunk = (runners + prior*K) / (cobuys + K),  prior = pool runner_capture_rate.
-- A pair needs cobuys >= [CALIBRATE, ~15] before its rate is trusted.

-- =====================================================================
-- 3. Populate wallet_aggregate_stats.tier from our archetypes (one-time / on rerank)
--    (ELITE / HIGH-RISK / CONSERVATIVE / DROP); leave compute to mv, just set tier.
--    Done via app UPDATE/dictionary from Supabase copy_wallets; ClickHouse is source of compute.
-- =====================================================================
