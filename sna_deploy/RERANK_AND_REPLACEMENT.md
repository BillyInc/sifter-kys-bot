# RERANK & REPLACEMENT — attribution, outcomes, staleness (bot / manual / single / pair)

## STORAGE ARCHITECTURE (corrected)
- **ClickHouse = compute + store** (events, aggregates, rolling stats, materialized views). The rerank/
  replacement metrics live here. Reuse the EXISTING per-wallet layer: `wallet_token_stats` ->
  `mv_wallet_aggregate` -> `wallet_aggregate_stats` (+ `wallet_weekly_snapshots`). Add the cluster + pair
  mirrors in `clickhouse_rerank.sql`.
- **Supabase = operational config + BACKUP only** (roster `copy_wallets`/`copy_clusters`, user/bot settings,
  live positions). `SETUP_ALL.sql` seeds the config/backup; it is NOT the analytics store.
- Reads go Redis -> ClickHouse on miss.

## METRIC MAPPING to existing ClickHouse columns
| Our term | Existing column |
|---|---|
| runner-capture rate | `consistency_score` (% qualified tokens with roi_mult >= 10) |
| composite health | `professional_score` |
| win / breakeven / loss | `wins` / `draws` / `losses` |
| EV (ROI%) | `avg_roi_pct`, `avg_roi_mult` |
| **realized $ profit (CO-PRIMARY)** | `total_realized_pnl_usd`, `total_pnl_usd` |
| staleness | `last_active_at` + `wallet_weekly_snapshots` |
| archetype | `tier` (we populate from copy_wallets) |

## RANKING BASIS — entry quality, NOT wallet PnL (Trojan-check clarification, 2026-06)
OUR GOAL: copy wallets that ENTER tokens >=10x below ATH that then run (information asymmetry / early entry),
and apply OUR OWN exits (trailing stops) to capture the runner. We DO NOT mirror their exits. Therefore the
ranking metric is RUNNER RATE (entry quality), and a wallet's own realized PnL is NOT a ranking input.

A Trojan spot-check (their realized $ PnL) on 3 wallets confirmed this distinction — and all 3 MEET our goal:
- `HhP9b26VX`: RR 24%, also personally profitable (+$14k, median +99%). Meets goal.
- `2wHHnAmd`: RR 16%, but flat money (churned $874k for median 0%). Meets goal — finds 185 runners, sells early.
- `8MA2HGoH`: RR 28%, flat (+$594, median -2%). Meets goal — catches runners, does not capture them.
KEY INSIGHT (do not invert): a runner-finder that is "not in profit" because it SELLS EARLY is a PRIME copy
target, not a weak one — it does the hard part (finding the early runner) and leaves the upside for OUR
trailing stop to collect. A wallet that fully captures the move is arguably LESS attractive (less left for us;
may dump on us). So we do NOT demote wallets for low personal PnL.
RULES:
1. RANK on runner-capture + (our-exit) EV + profit_factor. The wallet's OWN PnL is NOT a ranking input.
2. Cards may SHOW the wallet's realized PnL/median-ROI as transparency CONTEXT only (and for the niche user
   who wants to mirror exits), clearly labeled "their result" vs our copy-with-own-exit expectation.
3. The genuine caveats are about OUR execution, not their PnL: (a) our exits must actually capture the runner
   (paper trade validates), (b) entry latency must be livable, (c) very high churn wallets produce too many
   raw entries -> handled by the cluster + daily-cap layer, not by demotion.
4. The earlier non-runner EV used UNWEIGHTED mean ROI%; for OUR-exit EV use realized outcomes from the
   paper trade (with our SL/TP), not the wallet's own exits.

---


How per-trade outcomes roll up into the stats that drive reranking and replacement, for every consumer.
Grounded in the bear-market analysis; thresholds marked **[CALIBRATE]** are set from the paper-trade
distribution (we cannot backtest them on a 30-day window — that is what the paper run produces).

---

## 0. THE ONE COUNTERINTUITIVE RULE (read first)
**We do NOT replace the wallet/cluster with the most losses. We replace the one with the worst rolling
EXPECTED VALUE / runner-capture.** This strategy is fat-tailed: ~15–50% of trades are losers by count,
but the rare runners (≥10x) drive almost all the profit. A wallet with a 60% win rate of tiny gains and
ZERO runners is WORSE than one with a 30% win rate that catches runners. **Win-rate is a secondary,
diagnostic metric — never the replacement trigger.** The trigger is EV + runner-capture + profit factor.

---

## 1. PER TRADE: update per WALLET *and* per CLUSTER (dual attribution)
Every closed trade is attributed to BOTH granularities, because they answer different questions:

- **Per-CLUSTER** update → drives which clusters the **bot deploys** (the 3–4/day).
- **Per-WALLET** update → drives wallet **merit** (single-wallet List A ranking + cluster membership health).

Attribution source = `paper_raw_cobuys`: for the signalled token, the wallets that co-bought it within the
window ARE the participants. On trade close:
1. Write the realized outcome to the cluster that fired (`cluster_id`).
2. Write the SAME outcome to EVERY participating wallet (2–N of them, incl. co-confirmation members).
3. Write it to every participating PAIR (each unordered pair of participants).

So one trade → 1 cluster update + N wallet updates + C(N,2) pair updates. This is the core of the model.

---

## 2. WIN / LOSS / BREAKEVEN — how each trade is labeled
Outcome = OUR realized ROI **with our SL/TP exits** (not the wallet's own exit). Closed when SL / TP-ladder /
trailing / time-stop fires. Label by realized ROI:

| Label | Realized ROI | Meaning |
|---|---|---|
| **RUNNER** | ≥ +200% (≥3x) | caught a real mover; trailing stop banked a multiple. **These drive EV.** |
| **WIN** | +10% to +200% | TP ladder caught a 1.5–2x; green but not a runner |
| **BREAKEVEN** | −10% to +10% | noise; in/out near flat |
| **LOSS** | < −10% | hit stop |
| **ABORTED** | n/a | chase-guard blocked entry (tracked separately; not a PnL trade) |

Bands are **[CALIBRATE]** from the realized distribution; the ±10% breakeven band and the +200% runner cut
are starting points. Note RUNNER ⊂ WIN for PnL, but tracked separately because runner-capture is the metric.

---

## 3. METRICS WE JUDGE BY (rolling, trailing window)
Per wallet / cluster / pair, over a trailing window of the last **N closed signals** (N ≥ 20 **[CALIBRATE]**):

| Metric | Definition | Role |
|---|---|---|
| **Rolling EV** | mean(realized ROI) | **PRIMARY** — the money metric, runner-dominated |
| **Runner-capture rate** | runners / closed signals | **PRIMARY** — the edge source |
| **Profit factor** | Σ gains / |Σ losses| | **PRIMARY** — must stay > 1.0 |
| Win rate | wins / closed | secondary / diagnostic only |
| Avg loss | mean(loss ROI) | sizing + stop calibration |
| Signal frequency | signals / week | liveness (is it still producing?) |
| Last-signal age | days since last | inactivity flag |

**Composite health score** = percentile(rolling EV) × percentile(runner-capture) × (profit_factor ≥ 1 gate).
Reranking sorts by this; replacement triggers off its decay.

---

## 4. RERANK BY CLUSTER *AND* WALLET (different cadence, different purpose)
- **Cluster rerank** = the **deployment** decision. The bot trades the top clusters by rolling cluster-health
  that still clear the bot filter (shrunk RR ≥42% equivalent live, non-runner EV ≥ +5%). Slow cadence: weekly
  or every K=50 new signals **[CALIBRATE]** — NOT per trade (avoids churn on noise).
- **Wallet rerank** = the **merit** layer. Feeds (a) the single-wallet List A manual menu, and (b) which
  wallets are eligible to sit in clusters / on the bench. Same slow cadence.
- **They interact:** wallet health feeds cluster composition (a decayed member gets swapped), but the bot's
  go/no-go is always at the cluster level. Re-rank wallets first, then re-form/repair clusters from the
  refreshed wallet ranking.

---

## 5. WHEN IS A WALLET/CLUSTER "FALLING OFF" (staleness → replacement)
Role-aware, sustained, sample-gated. A unit is flagged STALE when ALL hold:
1. **Enough evidence:** ≥ N=20 closed signals in the trailing window **[CALIBRATE]** (else: insufficient data, hold).
2. **Edge gone:** rolling runner-capture < floor **AND** rolling EV < floor, where floor = max(pool median,
   50% of the unit's own baseline) **[CALIBRATE from paper-trade distribution]**.
3. **Sustained:** condition (2) true for K=2 consecutive evaluation windows **[CALIBRATE]** (one bad window ≠ stale).
4. **OR inactivity:** no signal in T=10 days **[CALIBRATE]** → bench regardless.

**Role-aware nuance (critical):** a wallet's health is measured in the ROLE it plays:
- As a **single** (List A): its SOLO runner-capture.
- As a **cluster member**: its **marginal contribution** — the cluster's runner-capture WITH it vs WITHOUT it
  on shared signals. A wallet can be weak solo but a strong co-confirmer (the DROP hubs `C7ML4W7c`,
  `DQmMnaki`); do NOT bench it from a cluster for solo weakness if its marginal cluster contribution is positive.

---

## 6. APPLIED PER CONSUMER

### 6A. BOT (cluster engine)
- **Update:** per cluster + per participating wallet, every closed trade.
- **Judge:** cluster rolling EV + runner-capture + PF.
- **Rerank unit:** CLUSTER (deploy top by health). Wallet health feeds membership.
- **Replace:** cluster-level first (swap a stale cluster for the next bench cluster #4–12), then wallet-level
  WITHIN a cluster (replace a stale member with a **same-tier** bench wallet so the cluster's risk profile is
  unchanged). Co-confirmation members judged by marginal contribution, not solo merit.
- **Falling off:** §5 rule on the cluster's rolling health.

### 6B. MANUAL (advisory feed)
- The user picks their own entry/exit, so their personal PnL is NOT the feed-quality metric. Rerank the FEED
  by each cluster/signal's outcome **under the default exit** (same attribution as the bot) = "advisory quality."
- **Update:** per cluster + per wallet (default-exit outcome). Track per-user actual PnL separately for the
  user's own dashboard — never mix it into feed reranking.
- **Rerank unit:** by rolling signal-strength (cluster + single). Manual sees more (lower-strength) signals
  than the bot, but ranking uses the same health metrics.
- **Replace:** same staleness rule; manual feed just surfaces a deeper list, so benched units drop down the
  feed rather than disappearing.

### 6C. SINGLE WALLET (List A)
- **Update:** per wallet directly (1 wallet = 1 signal; attribution is trivial).
- **Judge:** the wallet's SOLO rolling EV + runner-capture + PF with default exit.
- **Rerank unit:** WALLET. This is the List A ordering + the STRONG/MODERATE/FAIR strength label, recomputed rolling.
- **Falling off:** §5 on solo stats. A single-wallet user is told when their wallet decays and offered a
  same-tier replacement from the ranking.

### 6D. PAIR / CLUSTER SYNERGY
- **Update:** per pair (each unordered pair of co-entry participants) every closed trade.
- **Judge:** the pair's rolling CO-ENTRY runner-capture + EV (shrinkage-corrected, §pair-synergy). A pair needs
  ≥ support **[CALIBRATE]** before its rolling rate is trusted.
- **Rerank unit:** PAIR (drives which pairs anchor clusters). Re-cluster from the refreshed pair ranking on the
  slow cadence.
- **Falling off:** the pair's rolling co-entry runner-capture decays (the two wallets stop co-catching runners),
  OR a member goes stale. Replace the pair with the next-best pair sharing a healthy anchor.

---

## 7. CADENCE (avoid churn)
- **Per trade close:** UPDATE rolling stats (cheap, continuous).
- **Per evaluation window** (weekly OR every K=50 new signals **[CALIBRATE]**): RECOMPUTE ranks, evaluate
  staleness, execute swaps. Never replace on a single trade or a single window.
- **Circuit breaker:** if a deployed cluster's trailing PF < 1.0 over the window, auto-bench immediately
  (faster than the normal cadence) — this is the only fast path.

---

## 8. WHAT IS CALIBRATABLE NOW vs DEFERRED
- **Now (from bear data):** the metric set, the dual-attribution model, the outcome taxonomy, the
  composite-health formula, role-aware contribution, and starting baselines (bot-cluster runner-capture
  baseline ≈ 44–53%, non-runner EV +17–27%; single-wallet ELITE solo ≈ 15–36%).
- **Deferred to paper trade [CALIBRATE]:** all floors, N (min sample), K (consecutive windows), T (inactivity),
  the breakeven band, the runner cut, and the evaluation cadence. The paper run produces the rolling
  distribution that turns these from guesses into measured thresholds. Until then: collect, do not auto-swap.

> Replacement stays DISABLED until the paper trade has produced enough rolling history to set the floors.
> This is consistent with PAPER_TRADER_INSTRUCTIONS §7 (replacement deferred).
