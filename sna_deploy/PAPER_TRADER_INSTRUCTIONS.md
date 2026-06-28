# PAPER TRADER / LIVE BOT / MANUAL BOT — BUILD INSTRUCTIONS

**Status:** authoritative spec. Supersedes the legacy "Elite 15" single-wallet framing.
**Audience:** whoever implements the SNA_Demo `Backend/services/` paper-trade + execution path.
**Data source of truth:** `kys_fetcher/` analysis — `wallet_archetypes_merged.json`, `pair_synergy_merged.json`, `cluster_cards.json`, `reports/product_clusters.json`, `wallet_entry_style.json`.

---

## 0. THE ONE THING TO GET RIGHT FIRST (architecture correction)

The bot does **NOT** copy single wallets. The bot copies **CLUSTER CO-ENTRY**.

- A signal fires when **≥2 members of a defined cluster buy the same fresh, security-passing token within ~120s** (excluding same-block ≤30s snipes).
- The bot roster is **3 clusters = 9 distinct wallets**, NOT a "top 15 single wallets."
- There is no "Elite 15." The legacy `elite15` naming in the schema/`paper_trader.py` is a single-wallet path that must be **generalized to cluster signals** (see §4).

**Why (data-grounded):** out-of-sample, single-wallet count/popularity is anti-predictive (4% vs 7% base). Cluster co-entry by proven pairs is the only selector that beats base out-of-sample: **3/day → 53%, 4/day → 44% runner rate.** Co-entry IS the product.

### The 3 bot clusters (9 wallets)
| Cluster | Members | Shrunk RR | non-runner EV | ~sig/day |
|---|---|---|---|---|
| BOT-1 | `912iwi9r` + `C8TaRv2K` + `4PrW4vBq` | 45.9% | +27.6% | 0.67 |
| BOT-2 | `2hCmu9yG` + `dshAybqF` + `HPviVX3u` | 48.7% | +17.9% | 1.54 |
| BOT-3 | `2AqFJzcg` + `DQmMnaki` + `C7ML4W7c` | 44.6% | +20.5% | 3.77 |

(Full wallet addresses in `cluster_cards.json` / `COPY_LIST_B_clusters.md`. Some members — e.g. `DQmMnaki`, `C7ML4W7c` — are DROP-tier **co-confirmation only**: they sharpen the signal but are never traded solo.)

Bot filter that produced this set: shrunk RR ≥42% **AND** non-runner EV ≥+5% (so it does not bleed while unmonitored). Combined ~6/day → **daily cap 4, take highest signal-strength first**.

---

## 1. THE GOLDEN RULE: RECORD ONCE, SCORE MANY (never paper-trade twice)

The paper trader must be built so that **a new signal variant NEVER requires re-running live signals.** This is the whole point. The way to guarantee it:

1. **Record the RAW signal stream, exit-agnostic.** Every co-buy event from every wallet we track is appended to an immutable log with: timestamp, wallet, token, trigger price, and a reference to fetch the token's **forward price path**. We store *events and price paths*, not pre-aggregated outcomes.
2. **Variants are SCORERS over that raw stream, not collectors.** A "variant" (different cluster, window, chase-guard, min-members, exit rule) is a function evaluated offline against the already-recorded events. Adding a variant = adding a scorer = zero new live capture.
3. **Exits are simulated on the recorded price path, never live.** SL/TP/trailing variants replay against the stored path. You only ever re-capture live if you change **execution physics** (latency, slippage model) — never to test a different *selection* or *exit*.

> **Acceptance test for this rule:** "Can I add a brand-new cluster definition tomorrow and get its 100-signal paper-trade result *without collecting a single new live signal*?" If no, the architecture is wrong.

---

## 2. WHAT VARIANTS WE PAPER-TRADE (test ALL — adding them is free)

Because variants are offline scorers, we test the full grid. Two families:

### 2A. BOT-SELECTION variants (autonomous path)
- **Cluster set:** each of the 12 clusters in `cluster_cards.json` (the 3 bot clusters + 9 manual/bench), scored independently.
- **Co-entry window:** 60s / 120s / 300s (confirm 120s is optimal *live*, not just in backtest).
- **Chase-guard:** abort if fill/trigger > 1.5x / 2x / off (critical — this is what makes first-pump copyable, see §3).
- **Min members:** 2 vs 3 co-buyers required (higher bar = fewer, stronger).
- **Exit rule:** the SL/TP grid (per archetype × entry-style) replayed on stored paths.

### 2B. MANUAL-TRADER variants (advisory feed)
- **All 12 clusters** ranked by strength (incl. the high-RR-but-bleeding ones the bot skips).
- **Single-wallet signals (List A):** every STRONG/MODERATE individual wallet as a standalone manual signal.
- **Strength-tiered tracking:** STRONG / MODERATE / FAIR scored separately so we learn which band converts live.

Every variant runs **in parallel on the same recorded stream.** A token that triggers 5 variants is scored 5 times, once. One campaign evaluates the entire grid.

---

## 3. LATENCY & FIRST-PUMP COPYABILITY (must be modeled in paper trade)

Several top wallets are **first-pump** (buy in first ~5 min, thin buffer). A naive copy chases and loses. The paper trader must model and the live bot must enforce:

1. **Trigger on the 2nd confirming co-buy, not the 1st.** A lone first-pump buy is uncopyable; the *second* cluster member buying within 120s both validates the signal and gives a realistic entry price (still ~1.3x of the first buyer per our latency curve).
2. **Chase-guard (hard abort):** at execution, compute `fill_price / trigger_price`. If > threshold (1.5–2x), ABORT. Skipping is correct; bag-buying is not. The paper trader records aborts as a distinct outcome so we measure how often latency kills a signal.
3. **Simulated execution latency:** the paper trader applies a configurable lag (bot ≈ 30–60s, manual ≈ 60–300s) to the entry, fills at the path price *at lag*, and records `edge_kept = buffer_at_fill / buffer_at_trigger`. This is how we prove first-pump clusters survive (or don't) under realistic latency before going live.
4. **Entry-style tag on every signal** (`accumulator` / `first-pump` / `first-dip` from `wallet_entry_style.json`). Accumulator/dip = latency-forgiving; first-pump = latency-critical. The live bot deprioritizes first-pump when execution is slow.

---

## 4. CHANGES TO THE EXISTING SNA_Demo CODE

The paper subsystem exists (`paper_trader.py`, `paper_trade_runtime.py`, `paper_trading_manager.py`) but is single-wallet/elite15-only. Required changes:

### 4A. `paper_trader.py`
- **Line ~130** `process_signal`: `if signal.get("source") != "elite15"` — generalize. Accept `source in {"cluster", "single", "manual"}`. Do **not** drop the elite15 path; add cluster handling alongside.
- Add a **co-entry assembler** upstream: buffer incoming per-wallet buys keyed by `token_address`; emit a `cluster` signal when ≥N members of a cluster appear within the window. The assembler is the new front door; raw per-wallet buys still get logged (for variant re-scoring).
- `PaperPosition.signal_type` / `signal_key`: set `signal_type = "cluster"` and `signal_key = "<cluster_id>:<token>"` so positions trace back to which cluster + which variant opened them.

### 4B. New raw-event table (the record-once substrate)
```sql
CREATE TABLE sifter_dev.paper_raw_cobuys (
  id            BIGSERIAL PRIMARY KEY,
  ts            TIMESTAMPTZ NOT NULL,         -- buy time (firstBuy)
  wallet        TEXT NOT NULL,
  wallet_tier   TEXT,                          -- ELITE/HIGH-RISK/CONSERVATIVE/CO-CONF
  entry_style   TEXT,                          -- accumulator/first-pump/first-dip
  token_address TEXT NOT NULL,
  trigger_price NUMERIC NOT NULL,
  security_pass BOOLEAN,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE sifter_dev.paper_price_paths (   -- forward path per signalled token
  token_address TEXT NOT NULL,
  ts            TIMESTAMPTZ NOT NULL,
  price         NUMERIC NOT NULL,
  PRIMARY KEY (token_address, ts)
);
```
These two tables are immutable inputs. Every variant scorer reads them; nothing rewrites them.

### 4C. Variant-scoring tables (the score-many output)
```sql
CREATE TABLE sifter_dev.paper_variants (
  variant_id    TEXT PRIMARY KEY,             -- e.g. 'BOT-2|win120|chase2x|min2|exit_A'
  family        TEXT NOT NULL,                -- 'bot' | 'manual'
  config        JSONB NOT NULL                -- {cluster, window_s, chase_x, min_members, exit_rule}
);
CREATE TABLE sifter_dev.paper_variant_signals (
  id            BIGSERIAL PRIMARY KEY,
  variant_id    TEXT REFERENCES sifter_dev.paper_variants(variant_id),
  token_address TEXT NOT NULL,
  fired_ts      TIMESTAMPTZ NOT NULL,
  entry_price   NUMERIC,                       -- after simulated latency
  aborted       BOOLEAN DEFAULT FALSE,         -- chase-guard tripped
  exit_price    NUMERIC,                       -- from replayed exit rule on path
  is_runner     BOOLEAN,                       -- token hit >=10x on path
  realized_roi  NUMERIC,
  edge_kept     NUMERIC                        -- buffer_at_fill / buffer_at_trigger
);
```

### 4D. Reuse, don't rebuild
`paper_trade_runtime.log()` and `paper_trade_logs` already give structured logging + operator panel. Keep them. `paper_trading_manager.record_trade(trigger_type=...)` already distinguishes `auto_elite` vs `manual` — extend the enum to `auto_cluster` / `manual_cluster` / `manual_single`.

---

## 5. LOGGING — the logs MUST reflect the variant structure

Every log line and every recorded signal must answer: **which variant, which cluster, which wallets, what outcome, why.** Mandatory fields on each paper signal event (via `paper_trade_runtime.log`):

```
event_type     : signal_fired | signal_aborted_chase | exit_taken | signal_ignored
variant_id     : 'BOT-2|win120|chase2x|min2|exit_A'
cluster_id     : BOT-2  (or single-wallet id for List A variants)
trigger_wallets: [w1, w2]            # which members co-bought
wallet_tiers   : [ELITE, CONSERVATIVE]
entry_style    : first-pump
token_address  : ...
trigger_price  : ...
fill_price     : ...                  # after latency
chase_ratio    : fill/trigger
aborted        : bool + reason
is_runner      : (filled later when path resolves)
edge_kept      : ...
```

This makes the log **self-describing**: you can reconstruct any variant's full track record by filtering `variant_id`, and you can prove the no-double-run property (every `paper_variant_signals` row points back to a `paper_raw_cobuys` event id).

**Operator-panel rollup** (`get_status`): per-variant live runner rate, signals/day, abort rate, median edge_kept — sorted so the operator sees which variants are converging on the backtest (bot 44–53%) and which are not.

---

## 6. PROMOTION RULE (paper → live) — pre-register BEFORE running

To avoid cherry-picking the post-hoc winner (overfitting), the deploy decision is fixed in advance:

> A variant is promotable to LIVE only if, over **≥100 fired signals**: realized runner rate ≥ X% **AND** profit factor ≥ Y **AND** abort rate ≤ Z%, with the result holding on the **later half** of the paper window (temporal stability).

Fill X/Y/Z from the backtest expectation (bot variants: target ≥40% RR). Pre-registration is what separates a real edge from a data-dredged one. Do not tune X/Y/Z after seeing results.

---

## 7. REPLACEMENT / STALENESS — DEFERRED, decided after paper trade

Per decision: **do not hard-code the swap rule yet.** The paper trade itself produces the staleness signal (rolling per-cluster runner rate). After the first campaign we decide the unit (cluster-level vs wallet-level) and the trigger (decay below floor) from real forward data. Until then:
- Keep a **bench**: clusters #4–#12 in `cluster_cards.json` and same-tier wallets are the replacement pool.
- Replacement, when defined, will be **tier-matched** (a stale ELITE anchor → bench ELITE, never a HIGH-RISK) so a swap never silently changes a cluster's risk profile.
- The paper trader must log per-cluster rolling RR so the staleness threshold is *measured*, not guessed.

---

## 8. WHAT GOES WHERE (summary)

| Component | Consumes | Behavior |
|---|---|---|
| **Live bot (auto)** | 3 bot clusters, cap 4/day | Fire on cluster co-entry (≥2/120s), 2nd-buy trigger, chase-guard hard-abort, take highest signal-strength first. Unattended → only non-bleeding clusters (EV≥+5%). |
| **Manual bot** | all 12 clusters + List A singles | Full ranked feed by strength; user buys/ignores. Sees high-RR-but-bleeding signals the auto-bot skips (ride RR, cut by hand). |
| **Paper trader** | raw co-buy stream + price paths | Record once; score ALL bot + manual variants in parallel offline; simulate latency + exits; pre-registered promotion gate; per-variant self-describing logs. |

---

## 9. OPEN ITEMS (honest)
- All numbers are **bear-market only** (Jun 2026). Bull behavior unknown — flag in UI.
- Bot-cluster min support is 16–17 co-buys: deploy as a paper-trade *hypothesis*, not proven live edge.
- Some mid-tier wallet runner rates are still proxy-lower-bounds (730/1997 residual ATH unresolved) — they can only rise, never fall, so no false promotion. Re-resolve when credits allow, then refit synergy.
