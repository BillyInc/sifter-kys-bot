# AUDIT — verify SNA_Demo correctly integrated the copy-trade bundle

Run this AFTER the implementation agent finishes. Each check has: **how to verify**, the
**expected (ground-truth) value**, what to **FLAG**, and the **FIX**. Mark each ✅ / ❌ / ⚠️.

> Ground-truth source files (the agent must NOT have altered these): `sna_deploy/_ground_truth.json`,
> `clusters.json`, `wallets.json`, `paper_variants.json`, `bot_defaults.json`, `CLUSTER_ROSTER.md`.

## GROUND TRUTH (compare everything to these)
| Quantity | Value |
|---|---|
| Wallets seeded | **124** (ELITE 23, HIGH-RISK 49, CONSERVATIVE 48, DROP-as-co-conf 4) |
| Clusters | **12** (3 bot, 9 manual) |
| Paper variants | **257** (54 bot, 203 manual) |
| Distinct bot wallets | **9** (8 selectable + 1 co-confirmation) |
| Tables created | **6** |
| Stop loss | **−35%** (BOT-2 −30%), trailing **−40%**, NO hard TP cap |
| Limits | daily **4**, hourly **2**, weekly **28** |
| Sizing | base **10%**, cap **20%/token** |

### The 9 bot wallets (must match exactly — full 44-char, no truncation)
- **BOT-1** (RR 45.9 / EV +27.6): `912iwi9rQV6mc6RxGa77QDjcQjLgoKvEVahBFeqdpSgN`, `C8TaRv2K5BSe854b74xSUS92Lqjyv9Kks5W4Fb6VY3fe`, `4PrW4vBqZA6GHCGb9Am25DL8eHs7Sjzw8Xfq4GgyRLi5`
- **BOT-2** (RR 48.7 / EV +17.9): `2hCmu9yGtFXRgmfBGKX254U2mnpC3B1TkXMXx1WJa463`, `dshAybqFXYVVTd4mzy9Uk6KD7km8wE9iZgPMYZdzEXc`, `HPviVX3uyjHEgScheiwSdmm4YW3tUNmpwrD1gxiSohvs`
- **BOT-3** (RR 44.6 / EV +20.5): `2AqFJzcgSMQ9v7Vwh4yE7Vux8brcrjus1eg4K1zM2zUd`, `DQmMnakiKr1YNE2gcpggLCzBrauBwFbQkAaao2FTbjgp` *(co-confirmation, NOT traded solo)*, `C7ML4W7cegR8oBD3K2qeE5WmLgP2BGd8s81Sd78GZxN5`

---

## A. DATABASE INTEGRITY

**A1 — All 6 tables exist.**
Verify: `SELECT table_name FROM information_schema.tables WHERE table_schema='sifter_dev' AND table_name IN ('paper_raw_cobuys','paper_price_paths','paper_variants','paper_variant_signals','copy_wallets','copy_clusters');`
Expected: 6 rows. FLAG if <6. Fix: re-run `SETUP_ALL.sql`.

**A2 — Seed counts exact.**
Verify: `SELECT (SELECT count(*) FROM sifter_dev.copy_wallets), (SELECT count(*) FROM sifter_dev.copy_clusters), (SELECT count(*) FROM sifter_dev.paper_variants);`
Expected: **124, 12, 257**. FLAG any mismatch. Fix: re-run `SETUP_ALL.sql` (idempotent).

**A3 — Tier distribution.**
Verify: `SELECT tier, count(*) FROM sifter_dev.copy_wallets GROUP BY tier;`
Expected: ELITE 23, HIGH-RISK 49, CONSERVATIVE 48, DROP 4. FLAG mismatch → agent edited the seed. Fix: reload from `wallets.json`.

**A4 — Bot clusters = 3, distinct wallets = 9.**
Verify: `SELECT count(*) FROM sifter_dev.copy_clusters WHERE is_bot_cluster;` → 3.
Then count distinct addresses across those 3 clusters' `members` → **9**. FLAG if 15 or any other number (the "top-15" mistake). Fix: reload `clusters.json`.

**A5 — Idempotency.** Re-run `SETUP_ALL.sql`. Counts must be unchanged (124/12/257), no duplicate-key errors. FLAG duplicates → missing `ON CONFLICT`. Fix: ensure all INSERTs have `ON CONFLICT … DO UPDATE`.

**A6 — Limits applied.**
Verify: `SELECT auto_trade_daily_limit, auto_trade_hourly_limit FROM sifter_dev.telegram_users LIMIT 5;`
Expected: 4 and 2. FLAG 8/1 (legacy). Fix: run `auto_trade_limits_addendum.sql`.

**A7 — bot_defaults loaded.** A `bot_defaults` table/row exists holding `bot_defaults.json`. FLAG if SL/TP/sizing are hardcoded in Python instead of DB-loaded. Fix: create the table, load JSON, point the bot to it.

---

## B. ARCHITECTURE CORRECTNESS (highest-risk — these are the mistakes we kept catching)

**B1 — NOT "top 15 single wallets."** The bot must trade cluster co-entry. 
Verify: search the bot code for any roster of 15 single wallets, or auto-trading on a single wallet's buy.
`rg -n "top.?15|elite.?15|top_?15" Backend/services/` — any *new* single-wallet auto-trade roster is a FAIL.
Expected: bot reads `copy_clusters WHERE is_bot_cluster`. FLAG a 15-wallet list. Fix: replace with the 3-cluster source.

**B2 — `elite15` legacy path NOT broken.**
Verify: the original single-wallet `source=='elite15'` handling in `paper_trader.py` still runs (regression test it). FLAG if deleted/throws. Fix: keep it; add cluster handling alongside.

**B3 — Source guard generalized.**
Verify: `rg -n "source.*!=.*elite15" Backend/services/paper_trader.py` — the hard reject must be gone, replaced by `source in {'cluster','single','manual'}`. FLAG if still rejecting non-elite15. Fix per PAPER_TRADER_INSTRUCTIONS §4A.

**B4 — Co-entry assembler exists and is correct.**
Verify: a module buffers per-wallet buys by token and emits a cluster signal only when **≥min_members_to_fire (2) members of the SAME cluster buy within co_entry_window_s (120s)**.
FLAG if it fires on a single buy, or counts buys from different clusters as one signal, or ignores the 120s window. Fix: implement per PAPER_TRADER_INSTRUCTIONS §4A.

**B5 — Bot RANKS, never fires blind.**
Verify: the live bot computes a signal-strength score per co-entry and takes the **top N up to the daily cap**; it does NOT execute every cluster co-entry.
FLAG if it buys on first qualifying co-entry with no ranking (that's the 14–32% path, not 44–53%). Fix: add the ranked queue + cap.

**B6 — 2nd-buy trigger + chase-guard.**
Verify: signal fires on the **2nd** confirming member's buy (not the 1st); execution aborts if `fill_price/trigger_price > 1.5–2×`.
FLAG missing chase-guard (first-pump clusters will buy tops). Fix per PAPER_TRADER_INSTRUCTIONS §3.

---

## C. RECORD-ONCE-SCORE-MANY (the no-double-run invariant)

**C1 — Raw substrate populated.** Every tracked buy lands in `paper_raw_cobuys`; signalled tokens get rows in `paper_price_paths`. FLAG if signals are recorded only post-aggregation. Fix: log raw events first.

**C2 — Variant scoring is OFFLINE over recorded tables.** The scorer reads `paper_raw_cobuys`+`paper_price_paths` and writes `paper_variant_signals`. FLAG if any variant opens its own live capture stream. Fix: make variants pure scorers.

**C3 — THE ACCEPTANCE TEST.** Insert a new dummy row into `paper_variants`, run the scorer. It must produce `paper_variant_signals` for that variant **from already-recorded data, with zero new live capture**. FLAG if it requires live signals. Fix: decouple capture from scoring.

**C4 — Traceability.** Each `paper_variant_signals` row references a `paper_raw_cobuys.id`. FLAG orphan signals. Fix: add the FK linkage.

---

## D. SL / TP

**D1 — Stop loss.** Default −35%; BOT-2 override −30%. Verify against `bot_defaults.json`. FLAG other values. Fix: load from DB.

**D2 — NO hard take-profit cap (CRITICAL).** The runner portion (remaining 50%) must ride a **−40% trailing stop**, NOT a fixed sell at a multiple. A fixed TP cap caps the 20× runners and destroys the edge.
Verify: read the TP/SL monitor logic. FLAG any unconditional "sell 100% at Nx". Fix: partial TP (25%@2×, 25%@4×) + trailing −40% on the rest.

**D3 — Per-cluster overrides honored.** BOT-2 uses −30% (it bleeds −51%). FLAG if all clusters share one stop. Fix: read `per_cluster_overrides`.

**D4 — Time-stop NOT fabricated.** It's `PENDING_OHLCV`. FLAG a made-up time-stop number presented as derived. Fix: leave as TODO until Monte Carlo on `paper_price_paths`.

---

## E. TRADE LIMITS

**E1** daily 4, hourly 2, weekly 28 enforced. FLAG legacy 8/day. Fix: load from `bot_defaults.json`.
**E2** weekly circuit-breaker exists. FLAG if missing. Fix: add.
**E3** hourly cap actually spreads bursts (signals hit 11/hr raw). FLAG if a burst can fire >2 in an hour. Fix: enforce hourly gate.

---

## F. CONFLUENCE SIZING

**F1** base 10% per trade. FLAG other. 
**F2** +5% when an ELITE/List-A wallet also buys; +5% when 5+ distinct tracked wallets co-buy. FLAG if sizing ignores confluence. Fix: implement the ladder from `bot_defaults.json.confluence_sizing`.
**F3** hard cap **20%/token**. FLAG if a single token can exceed 20%. Fix: clamp.
**F4** pyramid adds ONLY if chase-guard holds (fill ≤1.5× first entry). FLAG if it adds at any price (chasing). Fix: gate the add on chase-guard.

---

## G. MANUAL FEED

**G1** feed = all 12 clusters + List-A STRONG/MODERATE singles, ranked by strength. FLAG if only bot clusters shown. 
**G2** bleeding clusters (negative EV, e.g. cluster with EV −23%) shown WITH a warning, not hidden and not auto-traded. FLAG if auto-traded or unlabeled.
**G3** confluence is surfaced as a size-up hint (ELITE present ≈ 2× runner rate). FLAG if absent. Fix per PAPER_TRADER_INSTRUCTIONS §8.

---

## H. BOT SINGLE-WALLET COPY (opt-in, gated)

**H1** default OFF. FLAG if ON by default.
**H2** when enabled, a List-A single's buy auto-executes ONLY with ≥1 other tracked co-buyer + per-wallet daily cap 2. FLAG if it blindly copies every buy of an elite wallet (blows the budget). Fix per prompt STEP 7.

---

## I. DATA FIDELITY (no invented data)

**I1 — Bot wallet addresses match exactly.** Compare the 9 seeded bot-cluster addresses to the Ground-Truth list above (full 44-char). FLAG any truncated (8-char), altered, or hallucinated address. Fix: reload from `clusters.json`.

**I2 — Cluster membership matches `CLUSTER_ROSTER.md`.** Spot-check each bot cluster's 3 members. FLAG any wallet swapped between clusters. Fix: reload.

**I3 — Stats not fabricated.** `copy_clusters.shrunk_runner_rate_pct` for BOT-1/2/3 = 45.9 / 48.7 / 44.6. FLAG invented numbers (e.g. a clean "50%"). Fix: reload.

**I4 — No new wallets/clusters invented.** Counts stay 124/12/257. FLAG extras. Fix: delete non-seed rows.

---

## J. DEFERRED ITEMS MUST NOT BE IMPLEMENTED

**J1** No hard-coded replacement/staleness swap logic (deferred until paper-trade rolling-RR data). FLAG any auto-swap rule. Fix: remove; keep bench list only.
**J2** No bull-market numbers presented as derived (dataset is bear-only). FLAG fabricated bull SL/TP. Fix: label bear-only.
**J3** SL/TP labeled as bear defaults / `PENDING_OHLCV`, not "optimized." FLAG over-claiming. Fix: relabel.

---

## FINAL SCORECARD
| Section | Checks | Pass | Flag | Notes |
|---|---|---|---|---|
| A Database | A1–A7 | | | |
| B Architecture | B1–B6 | | | **B1–B5 are blockers** |
| C Record-once | C1–C4 | | | **C3 is a blocker** |
| D SL/TP | D1–D4 | | | **D2 is a blocker** |
| E Limits | E1–E3 | | | |
| F Sizing | F1–F4 | | | |
| G Manual | G1–G3 | | | |
| H Single opt-in | H1–H2 | | | |
| I Data fidelity | I1–I4 | | | **I1 is a blocker** |
| J Deferred | J1–J3 | | | |

**Sign-off rule:** do NOT go past paper-trade until all **blockers** (B1–B5, C3, D2, I1) are ✅.
Any ❌ on a blocker = stop and fix before proceeding.
