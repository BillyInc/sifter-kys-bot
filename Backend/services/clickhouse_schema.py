"""
ClickHouse DDL statements for the KYS pipeline.
All tables use ReplacingMergeTree — INSERT new rows, never UPDATE.
Use SELECT ... FINAL to read deduplicated data.
"""

CREATE_TOKEN_SCANS_SQL = """
CREATE TABLE IF NOT EXISTS token_scans
(
    token_address       String,
    scan_id             String,
    discovered_via      String,
    scan_timestamp      DateTime,
    launch_price        Float64,
    current_price       Float64,
    ath_price           Float64,
    launch_to_ath_mult  Float64,
    launch_to_current_mult Float64,
    qualified_10x       UInt8,
    qualified_30x       UInt8,
    market_cap_usd      Float64,
    volume_24h_usd      Float64,
    liquidity_usd       Float64,
    holder_count        UInt32,
    scan_window_days    UInt8,
    token_symbol        String,
    token_name          String,
    updated_at          DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (token_address, scan_id)
PARTITION BY toYYYYMM(scan_timestamp)
"""

CREATE_WALLET_TOKEN_STATS_SQL = """
CREATE TABLE IF NOT EXISTS wallet_token_stats
(
    wallet_address              String,
    token_address               String,
    scan_id                     String,

    -- Entry / timing
    first_entry_price           Float64,
    first_entry_usd             Float64,
    first_entry_timestamp       DateTime,
    last_buy_timestamp          DateTime DEFAULT toDateTime(0),
    first_sell_timestamp        DateTime DEFAULT toDateTime(0),
    sell_time                   DateTime DEFAULT toDateTime(0),
    hold_time_secs              Int64 DEFAULT 0,

    -- Price signals
    avg_entry_price             Float64,
    avg_entry_to_ath_mult       Float64,
    entry_price_to_launch_mult  Float64,
    entry_vs_launch_mult        Float64 DEFAULT 0.0,

    -- Raw price reference data
    ath_price_raw               Float64 DEFAULT 0.0,
    launch_price_raw            Float64 DEFAULT 0.0,
    token_creation_time         DateTime DEFAULT toDateTime(0),
    current_price_usd           Float64 DEFAULT 0.0,

    -- Volume / position size
    tokens_bought_native        Float64 DEFAULT 0.0,
    tokens_sold_native          Float64 DEFAULT 0.0,
    current_balance             Float64 DEFAULT 0.0,
    current_value_usd           Float64 DEFAULT 0.0,
    avg_cost_per_token          Float64 DEFAULT 0.0,

    -- Trade averages
    avg_sell_size_usd           Float64 DEFAULT 0.0,

    -- Trade counts
    buy_count                   UInt16,
    sell_count                  UInt16,
    trade_count                 UInt16 DEFAULT 0,

    -- Financial
    total_spent_usd             Float64,
    sell_proceeds_usd           Float64 DEFAULT 0.0,
    realized_pnl_usd            Float64,
    unrealized_pnl_usd          Float64,
    total_pnl_usd               Float64,
    roi_pct                     Float64 DEFAULT 0.0,
    realized_roi_mult           Float64,
    total_roi_mult              Float64,

    -- Individual trades
    all_buys                    String,
    all_sells                   String,

    -- Token metadata
    token_name                  String DEFAULT '',
    token_symbol                String DEFAULT '',
    token_image                 String DEFAULT '',
    token_decimals              UInt8 DEFAULT 0,
    market_cap_usd              Float64 DEFAULT 0.0,
    liquidity_usd               Float64 DEFAULT 0.0,
    primary_market              String DEFAULT '',

    -- First buyer signal
    first_buyer_rank            UInt16 DEFAULT 0,

    -- Qualification
    qualifies                   UInt8,
    outcome                     String,
    disqualify_reason           String,
    wallet_source               String,

    updated_at                  DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (wallet_address, token_address)
PARTITION BY toYYYYMM(first_entry_timestamp)
"""

CREATE_WALLET_AGGREGATE_STATS_SQL = """
CREATE TABLE IF NOT EXISTS wallet_aggregate_stats
(
    wallet_address              String,
    tokens_appeared_in          UInt32,
    tokens_qualified            UInt32,
    tokens_traded_30d           UInt32 DEFAULT 0,
    wins                        UInt32,
    draws                       UInt32,
    losses                      UInt32,
    win_rate                    Float64,
    avg_entry_to_ath_mult       Float64,
    avg_entry_from_launch_mult  Float64,
    total_roi_pct               Float64,
    avg_roi_pct                 Float64 DEFAULT 0.0,
    avg_roi_mult                Float64,
    avg_spend_per_token_usd     Float64,
    total_spent_usd             Float64,
    total_sell_proceeds_usd     Float64 DEFAULT 0.0,
    total_pnl_usd               Float64,
    total_realized_pnl_usd      Float64 DEFAULT 0.0,
    total_unrealized_pnl_usd    Float64 DEFAULT 0.0,
    avg_hold_time_secs          Float64 DEFAULT 0.0,
    consistency_score           Float64,
    entry_price_multipliers     String,
    professional_score          Float64,
    tier                        String,
    last_active_token           String,
    last_active_at              DateTime,
    updated_at                  DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (wallet_address)
"""

CREATE_WALLET_WEEKLY_SNAPSHOTS_SQL = """
CREATE TABLE IF NOT EXISTS wallet_weekly_snapshots
(
    wallet_address      String,
    week_start          Date,
    tokens_qualified    UInt32,
    wins                UInt32,
    losses              UInt32,
    win_rate            Float64,
    avg_roi_mult        Float64,
    professional_score  Float64,
    tier                String,
    consistency_score   Float64,
    position_in_elite   UInt32,
    snapshot_at         DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(snapshot_at)
ORDER BY (wallet_address, week_start)
PARTITION BY toYYYYMM(week_start)
"""

CREATE_LEADERBOARD_RESULTS_SQL = """
CREATE TABLE IF NOT EXISTS leaderboard_results
(
    result_key          String,
    leaderboard_type    String,
    user_id             String,
    token_set           String,
    rank                UInt16,
    wallet_address      String,
    professional_score  Float64,
    tier                String,
    avg_entry_to_ath_mult Float64,
    avg_roi_mult        Float64,
    consistency_score   Float64,
    tokens_qualified    UInt32,
    win_rate            Float64,
    total_pnl_usd      Float64,
    computed_at         DateTime DEFAULT now(),
    expires_at          DateTime
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (result_key, rank)
PARTITION BY toYYYYMM(computed_at)
"""

# ── Materialized View: auto-aggregate wallet stats on INSERT ──

CREATE_MV_WALLET_AGGREGATE_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_wallet_aggregate
TO wallet_aggregate_stats
AS
SELECT
    wallet_address,
    countDistinct(token_address)                                            AS tokens_appeared_in,
    countIf(qualifies = 1)                                                  AS tokens_qualified,
    countIf(
        qualifies = 1
        AND first_entry_timestamp >= (now() - toIntervalDay(30))
    )                                                                       AS tokens_traded_30d,
    countIf(outcome = 'win')                                                AS wins,
    countIf(outcome = 'draw')                                               AS draws,
    countIf(outcome = 'loss')                                               AS losses,
    if(
        countIf(outcome IN ('win','draw','loss')) > 0,
        countIf(outcome = 'win') * 100.0
            / countIf(outcome IN ('win','draw','loss')),
        0
    )                                                                       AS win_rate,
    ifNull(avgIf(wallet_token_stats.avg_entry_to_ath_mult, qualifies = 1), 0)                 AS avg_entry_to_ath_mult,
    ifNull(avgIf(wallet_token_stats.entry_price_to_launch_mult, qualifies = 1), 0)            AS avg_entry_from_launch_mult,
    0.0                                                                     AS total_roi_pct,
    ifNull(avgIf(wallet_token_stats.roi_pct, qualifies = 1), 0)                               AS avg_roi_pct,
    ifNull(avgIf(wallet_token_stats.total_roi_mult, qualifies = 1), 0)                        AS avg_roi_mult,
    avg(wallet_token_stats.total_spent_usd)                                                    AS avg_spend_per_token_usd,
    sum(wallet_token_stats.total_spent_usd)                                                    AS total_spent_usd,
    sum(wallet_token_stats.sell_proceeds_usd)                                                  AS total_sell_proceeds_usd,
    sum(wallet_token_stats.total_pnl_usd)                                                      AS total_pnl_usd,
    sum(wallet_token_stats.realized_pnl_usd)                                                   AS total_realized_pnl_usd,
    sum(wallet_token_stats.unrealized_pnl_usd)                                                 AS total_unrealized_pnl_usd,
    ifNull(avgIf(wallet_token_stats.hold_time_secs, qualifies = 1 AND wallet_token_stats.hold_time_secs > 0), 0) AS avg_hold_time_secs,
    if(
        countIf(qualifies = 1) > 0,
        countIf(qualifies = 1 AND wallet_token_stats.avg_entry_to_ath_mult >= 10) * 100.0
            / countIf(qualifies = 1),
        0
    )                                                                       AS consistency_score,
    ''                                                                      AS entry_price_multipliers,
    (
        least(100, log(1 + ifNull(avgIf(wallet_token_stats.avg_entry_to_ath_mult, qualifies=1), 0)) * 100) * 0.50 +
        if(
            countIf(qualifies = 1) > 0,
            countIf(qualifies = 1 AND wallet_token_stats.avg_entry_to_ath_mult >= 10) * 100.0
                / countIf(qualifies = 1),
            0
        ) * 0.30 +
        least(100, log(1 + ifNull(avgIf(wallet_token_stats.total_roi_mult, qualifies=1), 0)) * 100) * 0.20
    )                                                                       AS professional_score,
    ''                                                                      AS tier,
    ifNull(argMaxIf(token_address, first_entry_timestamp, qualifies=1), '') AS last_active_token,
    ifNull(maxIf(first_entry_timestamp, qualifies=1), now())                AS last_active_at,
    now()                                                                   AS updated_at
FROM wallet_token_stats
GROUP BY wallet_address
"""

DROP_MV_WALLET_AGGREGATE_SQL = "DROP VIEW IF EXISTS mv_wallet_aggregate"


# ════════════════════════════════════════════════════════════════════════════
# Telegram trading-bot analytics (bot rebuild). Additive — never alters the
# tables above. All ReplacingMergeTree, read with FINAL. No fake-volume /
# risk-score / market-cap columns (intentionally excluded from the build).
# ════════════════════════════════════════════════════════════════════════════

CREATE_BOT_SIGNAL_LOG_SQL = """
CREATE TABLE IF NOT EXISTS bot_signal_log
(
    signal_key      String,
    token_address   String,
    token_symbol    String  DEFAULT '',
    wallet_count    UInt16  DEFAULT 1,
    signal_type     String  DEFAULT 'single',
    total_usd       Float64 DEFAULT 0,
    consensus_met   UInt8   DEFAULT 0,
    blacklisted     UInt8   DEFAULT 0,
    users_notified  UInt32  DEFAULT 0,
    users_executed  UInt32  DEFAULT 0,
    emitted_at      DateTime,
    updated_at      DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (signal_key)
PARTITION BY toYYYYMM(emitted_at)
"""

CREATE_BOT_TRADE_LOG_SQL = """
CREATE TABLE IF NOT EXISTS bot_trade_log
(
    trade_id            String,
    user_id             String,
    signal_key          String  DEFAULT '',
    token_address       String,
    token_symbol        String  DEFAULT '',
    side                String  DEFAULT 'buy',
    trigger_type        String  DEFAULT 'auto_elite',
    signal_type         String  DEFAULT 'single',
    wallet_count        UInt16  DEFAULT 1,
    execution_mode      String  DEFAULT 'safe_noop',
    status              String  DEFAULT 'filled',
    stage               String  DEFAULT 'confirm',
    reason              String  DEFAULT '',
    requested_usd       Float64 DEFAULT 0,
    executed_usd        Float64 DEFAULT 0,
    effective_price_usd Float64 DEFAULT 0,
    price_impact_bps    UInt32  DEFAULT 0,
    slippage_bps        UInt32  DEFAULT 0,
    realized_pnl_usd    Float64 DEFAULT 0,
    roi_pct             Float64 DEFAULT 0,
    txid                String  DEFAULT '',
    created_at          DateTime,
    updated_at          DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (user_id, trade_id)
PARTITION BY toYYYYMM(created_at)
"""

CREATE_BOT_FEE_LOG_SQL = """
CREATE TABLE IF NOT EXISTS bot_fee_log
(
    fee_id           String,
    trade_id         String,
    user_id          String,
    token_address    String,
    token_symbol     String  DEFAULT '',
    side             String  DEFAULT 'buy',
    trigger_type     String  DEFAULT 'auto_elite',
    gross_usd        Float64 DEFAULT 0,
    fee_bps          UInt16  DEFAULT 100,
    fee_usd          Float64 DEFAULT 0,
    treasury_wallet  String  DEFAULT '',
    fee_txid         String  DEFAULT '',
    collected_at     DateTime,
    updated_at       DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (fee_id)
PARTITION BY toYYYYMM(collected_at)
"""

# ── Per-user bot stats (feeds My Account / Stats screen) ──
CREATE_USER_BOT_STATS_AGG_SQL = """
CREATE TABLE IF NOT EXISTS user_bot_stats_agg
(
    user_id             String,
    total_trades        UInt32  DEFAULT 0,
    closed_trades       UInt32  DEFAULT 0,
    winning_trades      UInt32  DEFAULT 0,
    losing_trades       UInt32  DEFAULT 0,
    win_rate            Float64 DEFAULT 0,
    total_pnl_usd       Float64 DEFAULT 0,
    avg_roi_pct         Float64 DEFAULT 0,
    best_trade_mult     Float64 DEFAULT 1,
    best_trade_symbol   String  DEFAULT '',
    total_executed_usd  Float64 DEFAULT 0,
    last_trade_at       DateTime,
    updated_at          DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (user_id)
"""

CREATE_MV_USER_BOT_STATS_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_user_bot_stats
TO user_bot_stats_agg
AS
SELECT
    user_id,
    count()                                          AS total_trades,
    countIf(status = 'closed')                       AS closed_trades,
    countIf(roi_pct > 0 AND status = 'closed')       AS winning_trades,
    countIf(roi_pct <= 0 AND status = 'closed')      AS losing_trades,
    if(
        countIf(status = 'closed') > 0,
        countIf(roi_pct > 0 AND status = 'closed') * 100.0
            / countIf(status = 'closed'),
        0
    )                                                AS win_rate,
    sum(realized_pnl_usd)                            AS total_pnl_usd,
    avg(roi_pct)                                     AS avg_roi_pct,
    if(max(roi_pct) > 0, 1 + max(roi_pct) / 100, 1)  AS best_trade_mult,
    argMax(token_symbol, roi_pct)                    AS best_trade_symbol,
    sum(executed_usd)                                AS total_executed_usd,
    max(created_at)                                  AS last_trade_at,
    now()                                            AS updated_at
FROM bot_trade_log
GROUP BY user_id
"""

# ── Fee revenue rollups (feed operator Fee Revenue panel) ──
CREATE_FEE_REVENUE_AGG_SQL = """
CREATE TABLE IF NOT EXISTS fee_revenue_agg
(
    day                  Date,
    total_trades         UInt32  DEFAULT 0,
    total_fee_usd        Float64 DEFAULT 0,
    auto_trade_fee_usd   Float64 DEFAULT 0,
    manual_trade_fee_usd Float64 DEFAULT 0,
    updated_at           DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (day)
"""

CREATE_FEE_BY_TOKEN_AGG_SQL = """
CREATE TABLE IF NOT EXISTS fee_by_token_agg
(
    token_address    String,
    token_symbol     String  DEFAULT '',
    total_fee_usd    Float64 DEFAULT 0,
    trade_count      UInt32  DEFAULT 0,
    last_fee_at      DateTime,
    updated_at       DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (token_address)
"""

CREATE_MV_FEE_REVENUE_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_fee_revenue
TO fee_revenue_agg
AS
SELECT
    toDate(collected_at)                                       AS day,
    count()                                                    AS total_trades,
    sum(fee_usd)                                               AS total_fee_usd,
    sumIf(fee_usd, trigger_type = 'auto_elite')                AS auto_trade_fee_usd,
    sumIf(fee_usd, trigger_type = 'manual')                    AS manual_trade_fee_usd,
    now()                                                      AS updated_at
FROM bot_fee_log
GROUP BY day
"""

CREATE_MV_FEE_BY_TOKEN_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_fee_by_token
TO fee_by_token_agg
AS
SELECT
    token_address,
    argMax(token_symbol, collected_at)  AS token_symbol,
    sum(fee_usd)                        AS total_fee_usd,
    count()                             AS trade_count,
    max(collected_at)                   AS last_fee_at,
    now()                               AS updated_at
FROM bot_fee_log
GROUP BY token_address
"""
