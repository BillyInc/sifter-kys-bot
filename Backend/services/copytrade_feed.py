"""Manual-trader advisory feed (STEP 6).

Builds the data the manual trader sees: all 12 clusters ranked by strength, plus the
List-A single wallets. Pure derivation over ``copytrade_config`` (no DB writes), so it is
unit-testable and shared by the bot UI render layer.

Two honesty signals the manual trader must see (and the auto-bot acts on):
- ``bleeds``  — high-RR but negative non-runner EV: the auto-bot SKIPS these (they lose while
  held unattended); a manual trader may ride the RR and cut by hand. Flagged with a warning.
- ``size_up`` — an ELITE / List-A wallet is in the cluster: ELITE present ≈ 2x runner rate,
  so confluence with one is a size-up signal.
"""

from __future__ import annotations

from typing import Dict, List

from services.copytrade_config import get_copytrade_config


def build_cluster_feed() -> List[Dict]:
    """All 12 clusters, ranked by strength then RR, with bot-set / bleed / size-up flags."""
    cfg = get_copytrade_config()
    feed: List[Dict] = []
    for c in cfg.manual_clusters():
        tradable = [m for m in c.members if m.tradable]
        co_conf = [m for m in c.members if not m.tradable]
        elite_present = any((m.tier or "").upper() == "ELITE" for m in c.members)
        feed.append({
            "cluster_id": c.cluster_id,
            "is_bot_cluster": c.is_bot_cluster,
            "strength": c.strength,
            "runner_rate_pct": c.shrunk_runner_rate_pct,
            "nonrunner_ev_pct": c.nonrunner_ev_pct,
            "signals_per_day": c.signals_per_day,
            "min_members_to_fire": c.min_members_to_fire,
            "co_entry_window_s": c.co_entry_window_s,
            "members": [
                {"address": m.address, "tier": m.tier, "entry_style": m.entry_style,
                 "role": m.role, "tradable": m.tradable}
                for m in c.members
            ],
            "tradable_count": len(tradable),
            "co_confirmation_count": len(co_conf),
            "bleeds": c.bleeds_unmonitored,          # auto-bot skips; manual rides + cuts by hand
            "bleeds_warning": (
                "High RR but negative EV — the auto-bot skips this; ride the RR and cut by hand."
                if c.bleeds_unmonitored else None
            ),
            "size_up": elite_present,                 # ELITE present ≈ 2x runner rate
        })
    return feed


def build_single_wallet_feed(strengths=("STRONG", "MODERATE")) -> List[Dict]:
    """List-A selectable single wallets, ranked by strength then runner rate."""
    cfg = get_copytrade_config()
    out: List[Dict] = []
    for w in cfg.list_a_singles(strengths=strengths):
        out.append({
            "address": w.address,
            "tier": w.tier,
            "runner_rate_pct": w.runner_rate_pct,
            "nonrunner_ev_pct": w.nonrunner_ev_pct,
            "profit_factor": w.profit_factor,
            "tokens_30d": w.tokens_30d,
            "entry_style": w.entry_style,
            "signal_strength": w.signal_strength,
            "size_up": (w.tier or "").upper() == "ELITE",
        })
    return out
