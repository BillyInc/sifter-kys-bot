# COPY-TRADE LIST B — WALLET CLUSTERS (ranked by signal strength)

Each cluster is a group of wallets that BUY TOGETHER on winners. Copying a cluster means you
act when 2+ of its members buy the same fresh token within ~120s. Co-entry is far stronger than
any single wallet (out-of-sample: 3-4 cluster signals/day = 44-53% runner rate vs ~7% baseline).

Mixed by design: an ELITE anchor + boosters. Some members are 'co-confirmation only' (they sharpen
the signal but you don't copy them solo). Stats are shrinkage-corrected (honest, not in-sample inflated).

| # | Cluster (members) | Tiers | Strength | RR% | nrEV% | Signals/day | Styles | BOT? |
|---|-------------------|-------|----------|-----|-------|-------------|--------|------|
| 1 | `912iwi9r` + `C8TaRv2K` + `4PrW4vBq` | CONS/ELIT/CONS | **MODERATE** | 45.9% | +28% | ~0.67 | accum/first/accum | ✅ |
| 2 | `2hCmu9yG` + `dshAybqF` + `HPviVX3u` | ELIT/CONS/HIGH | **MODERATE** | 48.7% | +18% | ~1.54 | first/first/first | ✅ |
| 3 | `2AqFJzcg` + `DQmMnaki` + `C7ML4W7c` | ELIT/DROP/CONS | **MODERATE** | 44.6% | +20% | ~3.77 | first/first/accum | ✅ |
| 4 | `459CAn1v` + `B1R4D1cd` + `C7ML4W7c` | ELIT/CONS/CONS | **MODERATE** | 50.4% | +10% | ~0.74 | first/first/accum | — |
| 5 | `7AiejjFn` + `C76F4BrL` + `459CAn1v` | CONS/ELIT/ELIT | **FAIR** | 39.6% | +19% | ~0.39 | first/first/first | — |
| 6 | `2wHHnAmd` + `C7ML4W7c` + `HV4cjkte` | ELIT/CONS/HIGH | **MODERATE** | 42.6% | +14% | ~1.08 | first/accum/accum | — |
| 7 | `F6pipncJ` + `HpBQZopr` + `4PrW4vBq` | HIGH/ELIT/CONS | **MODERATE** | 42.7% | +11% | ~0.6 | first/accum/accum | — |
| 8 | `8GCfpN4j` + `DrnuP46q` + `HZqQJv9u` | ELIT/DROP/HIGH | **MODERATE** | 53.0% | -23% | ~1.94 | first/first/first | — |
| 9 | `9yxmCNwZ` + `F7RV6aBW` + `22vL22Pc` | ELIT/DROP/ELIT | **MODERATE** | 44.3% | -9% | ~5.64 | first/first/first | — |
| 10 | `3SkBCx49` + `Bz4zDut6` + `22vL22Pc` | DROP/ELIT/ELIT | **MODERATE** | 42.0% | -6% | ~1.05 | first/first/first | — |
| 11 | `8MA2HGoH` + `CX7HYipa` + `C7ML4W7c` | ELIT/CONS/CONS | **FAIR** | 37.0% | -3% | ~2.21 | accum/accum/accum | — |
| 12 | `5JJZKGkS` + `EQ5idGCx` + `Bz4zDut6` | ELIT/CONS/ELIT | **FAIR** | 27.5% | +1% | ~0.33 | first/first/first | — |

## The ✅ BOT set (autonomous — takes the 3-4 highest-quality/day)

Filter: shrunk runner rate ≥42% AND non-runner EV ≥+5% (so it doesn't bleed while unmonitored).
These run unattended. Combined they offer ~6 signals/day; the bot caps at 4 and takes the highest
signal-strength first.

1. **912iwi9r + C8TaRv2K + 4PrW4vBq** — RR 45.9%, non-runner EV +28%, ~0.67/day, tiers CONS/ELIT/CONS
2. **2hCmu9yG + dshAybqF + HPviVX3u** — RR 48.7%, non-runner EV +18%, ~1.54/day, tiers ELIT/CONS/HIGH
3. **2AqFJzcg + DQmMnaki + C7ML4W7c** — RR 44.6%, non-runner EV +20%, ~3.77/day, tiers ELIT/DROP/CONS

## Manual-trader feed (everything above)
Manual traders see ALL clusters, including higher-RR-but-bleeding ones the bot skips (e.g. clusters
with negative nrEV: ride the runner rate, cut losers by hand). Buy or ignore by strength.

**Strength key:** STRONG = RR≥50% + non-bleed + support≥20. MODERATE = RR≥40%. FAIR = RR≥27%.