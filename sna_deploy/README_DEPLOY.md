# SNA_Demo Deployment Bundle — what to add and where

Everything the SNA_Demo bot/paper-trader/manual-trader needs from the wallet analysis.
**Market phase:** bear (Jun 2026). All stats are bear-only — flag in UI.

## The roster in one line
The bot is **3 clusters = 9 wallets** (8 traded + 1 co-confirmation). NOT a top-15 single-wallet list.
Single wallets (List A) are a **manual-trader menu only**.

---

## Files in this bundle

| File | What it is | Where it goes in SNA_Demo |
|---|---|---|
| **⭐ SETUP_ALL.sql** | **ONE-SHOT.** All 6 tables (4 paper + 2 roster) + all seeds (124 wallets, 12 clusters, 257 variants). Idempotent, wrapped in a transaction. | **Run this ONCE in Supabase SQL editor.** Replaces the per-part SQL below. |
| **⭐ CLUSTER_ROSTER.md** | **Single source of truth** — every bot & manual cluster with each member's FULL address + individual stats (tier/RR/EV/style/strength). | Read this to see exactly which wallets are in which cluster. |
| **clusters.json** | 12 clusters w/ full addresses, 3 flagged `is_bot_cluster`. Machine-readable. | App cluster config; already seeded by SETUP_ALL.sql into `copy_clusters`. Live bot reads `is_bot_cluster=true` (3); manual reads all 12. |
| **wallets.json** | 124 wallets: tier, role, RR, EV, style, strength. Machine-readable. | Already seeded by SETUP_ALL.sql into `copy_wallets`. Replaces legacy "elite15" roster. |
| **paper_variants.json** | 257 variant scorers (bot + manual). Machine-readable copy. | Already seeded by SETUP_ALL.sql into `paper_variants`. Each = offline scorer (PAPER_TRADER_INSTRUCTIONS §1). |
| **seed_clusters_wallets.sql** | (Superseded by SETUP_ALL.sql — kept for reference; roster-only.) | — |
| **PAPER_TRADER_INSTRUCTIONS.md** | Authoritative build spec: record-once-score-many, variant grid, latency/first-pump, `paper_trader.py` changes, log schema, promotion gate. | Hand to the implementer. |
| **COPY_LIST_A_single_wallets.md** | Single-wallet menu, ranked by strength. | Manual-trader UI. The elite lone-wolves (CkunCFewE 35.7% etc.) live here, NOT in bot clusters. |
| **COPY_LIST_B_clusters.md** | Cluster menu, bot-set marked. | Manual-trader UI; ✅ rows = auto roster. |

> **Note on the roster:** bot cluster MEMBERS are individually modest (RR 3–15%); the cluster's 44–49% RR comes from *confluence* (co-buying), not individual skill. The best individual wallets are lone-wolves in List A. This is by design — see CLUSTER_ROSTER.md.

---

## Order of operations

1. **Apply migrations** (new tables in PAPER_TRADER_INSTRUCTIONS §4B/4C: `paper_raw_cobuys`, `paper_price_paths`, `paper_variants`, `paper_variant_signals`).
2. **Run `seed_clusters_wallets.sql`** → populates the wallet + cluster roster.
3. **Load `paper_variants.json`** → the score-many grid.
4. **Modify `paper_trader.py`** per §4A — generalize `source != "elite15"` to accept cluster signals; add the co-entry assembler.
5. **Wire the live bot** to `copy_clusters WHERE is_bot_cluster` with daily cap 4, 2nd-buy trigger, chase-guard.
6. **Wire the manual feed** to all 12 clusters + List A singles, ranked by strength.
7. **Start a paper-trade run** → record raw stream, score all 257 variants offline. Promotion gate is pre-registered (§6).

---

## The 3 bot clusters (full addresses in clusters.json)

- **BOT-1** `912iwi9r…` + `C8TaRv2K…` + `4PrW4vBq…` — RR 45.9%, EV +27.6% (accumulator-heavy → latency-forgiving)
- **BOT-2** `2hCmu9yG…` + `dshAybqF…` + `HPviVX3u…` — RR 48.7%, EV +17.9% (first-pump → needs fast exec)
- **BOT-3** `2AqFJzcg…` + `DQmMnaki…`(co-conf) + `C7ML4W7c…` — RR 44.6%, EV +20.5%

Combined ~6 signals/day → cap 4, take highest strength first. Out-of-sample expectation: **3-4/day at 44-53% runner rate** (vs ~7% base).

---

## NOT included / deferred
- **Replacement/staleness rule** — deferred by decision; the paper trader measures rolling per-cluster RR, then we set the swap trigger. Bench = clusters #4-12 + same-tier wallets.
- **Bull-market calibration** — dataset is bear-only.
- Some mid-tier wallet RRs are proxy-lower-bounds (unresolved residual ATH) — they can only rise; re-resolve + refit synergy when API credits allow.
