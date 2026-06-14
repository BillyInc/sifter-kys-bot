# PROMPT — integrate the copy-trade wallet bundle into SNA_Demo

> Paste everything below the line into a coding agent running in the SNA_Demo repo.

---

You are updating the **SNA_Demo** Solana copy-trade bot to use a finalized wallet/cluster analysis.
The deliverable bundle is at `C:\Users\USER\Downloads\kys_fetcher\sna_deploy\`. **First copy that whole folder into the repo** at `Backend/seeds/copytrade/` and work from there. Do not invent data — every wallet, cluster, stat, SL/TP, limit, and sizing rule comes from these files.

## Ground truth you must respect (do NOT redesign)
1. **The bot trades CLUSTER CO-ENTRY, not single wallets.** A signal = ≥2 members of a cluster buying the same fresh, security-passing token within ~120s.
2. **The bot roster is 3 clusters = 9 wallets** (8 traded + 1 co-confirmation). There is **NO "top 15."** The legacy `elite15` single-wallet path must be **generalized, not extended with a bigger list.**
3. **Record-once-score-many is an invariant.** Acceptance test before you finish: *"Can I add a new signal variant and get its paper-trade result WITHOUT collecting one new live signal?"* If no, the design is wrong.
4. **The bot RANKS co-entries by signal strength and takes the top N up to caps** — it never fires on every cluster co-entry (that path is 14–32%; ranking is 44–53%).

## Read these first, in this order
1. `README_DEPLOY.md` — the manifest (what every file is, where it goes).
2. `PAPER_TRADER_INSTRUCTIONS.md` — the authoritative build spec (§0 architecture, §1 record-once, §2 variants, §3 latency/first-pump, §4 exact code+schema changes, §5 log schema, §6 promotion gate, §7 replacement-deferred).
3. `CLUSTER_ROSTER.md` — the single source of truth for which wallets are in which cluster + their individual stats.
4. `bot_defaults.json` — SL/TP, trade limits, confluence sizing (bot defaults).

## Execute in this sequence

### STEP 1 — Database (run once)
- Apply `SETUP_ALL.sql` in Supabase (schema `sifter_dev`). Creates 6 tables (`paper_raw_cobuys`, `paper_price_paths`, `paper_variants`, `paper_variant_signals`, `copy_wallets`, `copy_clusters`) and seeds 124 wallets + 12 clusters + 257 variants. Idempotent.
- Apply `auto_trade_limits_addendum.sql` (daily 4, hourly 2).
- Add a `bot_defaults` table (or config row) holding the contents of `bot_defaults.json` so the bot loads SL/TP/sizing/limits from the DB, not hardcoded.

### STEP 2 — Make `paper_trader.py` cluster-aware (the central change)
- In `Backend/services/paper_trader.py`, `process_signal` (~line 130): the guard `if signal.get("source") != "elite15"` currently rejects everything non-single-wallet. **Generalize** it to accept `source in {"cluster","single","manual"}`. **Do NOT delete the elite15 path** — add cluster handling alongside it.
- Add a **co-entry assembler** upstream (new module, e.g. `Backend/services/cobuy_assembler.py`): buffer incoming per-wallet buys keyed by `token_address`; when ≥`min_members_to_fire` members of a `copy_clusters` row appear within `co_entry_window_s`, emit a `cluster` signal. Every raw per-wallet buy is still written to `paper_raw_cobuys` (the record-once substrate).
- Set `PaperPosition.signal_type="cluster"`, `signal_key="<cluster_id>:<token>"`.

### STEP 3 — Record-once + score-many
- Write raw co-buys to `paper_raw_cobuys`; capture forward price into `paper_price_paths`.
- Build a variant scorer that evaluates ALL rows of `paper_variants` (from `paper_variants.json`) **offline** against the recorded tables, writing `paper_variant_signals`. Adding a variant must never trigger new live capture. Reuse `paper_trade_runtime.log()` + `paper_trade_logs`.

### STEP 4 — Logging (must be self-describing)
- Every paper signal event logs: `variant_id, cluster_id, trigger_wallets[], wallet_tiers[], entry_style, token_address, trigger_price, fill_price, chase_ratio, aborted+reason, is_runner, edge_kept` (schema in PAPER_TRADER_INSTRUCTIONS §5). One must be able to reconstruct any variant's full record by filtering `variant_id`, and trace each signal back to a `paper_raw_cobuys` id.

### STEP 5 — Live bot (auto-trader)
- Source = `copy_clusters WHERE is_bot_cluster = true` (3 clusters).
- Fire on co-entry (≥2/120s), trigger on the **2nd** confirming buy, apply the **chase-guard** (abort if fill/trigger > 1.5–2×).
- Apply limits from `bot_defaults.json`: daily 4, hourly 2, weekly 28; **rank candidates by signal strength, take top N**.
- Apply SL/TP from `bot_defaults.json.sl_tp_strategy` (stop −35% / BOT-2 −30%; partial TP 25%@2× + 25%@4×; trailing −40% on the rest; **no hard cap**) via the existing TP/SL Celery monitor.
- Apply confluence sizing from `bot_defaults.json.confluence_sizing`: base 10%; +5% if an ELITE/List-A wallet also buys; +5% if 5+ distinct tracked wallets co-buy; hard cap 20%/token; pyramid only if chase-guard holds.

### STEP 6 — Manual trader
- Feed = all 12 clusters (`copy_clusters`) ranked by strength + the single wallets in `COPY_LIST_A_single_wallets.md` / `copy_wallets WHERE selectable AND signal_strength IN ('STRONG','MODERATE')`.
- Show the higher-RR-but-bleeding clusters the bot skips (negative EV) with a warning.
- Surface best-wallet/cluster confluence as a **size-up signal** (ELITE present ≈ 2× runner rate).

### STEP 7 — Bot-user single-wallet copy (opt-in, gated)
- Default OFF. If a user opts in to auto-copy a List-A elite single, the bot executes that wallet's buy ONLY when it also has ≥1 other tracked co-buyer (fold into confluence) + a per-wallet daily cap of 2.

### STEP 8 — Verify
- `SETUP_ALL.sql` applied, all 6 tables present, 124/12/257 rows seeded.
- A simulated co-buy of 2 BOT-1 members within 120s produces a `cluster` paper signal + a `paper_variant_signals` row per matching variant, all tracing to `paper_raw_cobuys`.
- The elite15 single-wallet path still works (not broken).
- Adding a dummy variant row scores against existing recorded data with zero new live capture.

## Deferred (do NOT implement yet)
- **Replacement/staleness swaps** — wait for paper-trade rolling-RR data (PAPER_TRADER_INSTRUCTIONS §7). Bench = clusters #4–12 + same-tier wallets.
- **Bull-market calibration** — dataset is bear-only; flag in UI.
- **Final SL/TP optimization** — current values are bear defaults; refine via Monte Carlo on recorded `paper_price_paths` (fields marked `PENDING_OHLCV`).

## File → role quick reference
| File | Role |
|---|---|
| `SETUP_ALL.sql` | one-shot DB: 6 tables + seed 124 wallets / 12 clusters / 257 variants |
| `auto_trade_limits_addendum.sql` | set daily=4, hourly=2 |
| `bot_defaults.json` | SL/TP, limits, confluence sizing (load into `bot_defaults` table) |
| `CLUSTER_ROSTER.md` | which wallets in which cluster + stats (source of truth) |
| `clusters.json` / `wallets.json` / `paper_variants.json` | machine-readable seeds (already in SETUP_ALL.sql) |
| `COPY_LIST_A_single_wallets.md` | manual single-wallet menu |
| `COPY_LIST_B_clusters.md` | manual cluster menu (✅ = bot set) |
| `PAPER_TRADER_INSTRUCTIONS.md` | full build spec |
| `README_DEPLOY.md` | manifest + deploy order |
| `seed_clusters_wallets.sql` | superseded by SETUP_ALL.sql (reference only) |
