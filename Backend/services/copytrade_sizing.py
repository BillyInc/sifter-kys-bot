"""Confluence sizing + chase-guard for the cluster co-entry bot (bot_defaults-driven).

Pure functions over ``bot_defaults`` so they unit-test without DB/Redis. The live bot and
the paper trader both size and chase-guard identically (one source of truth):

- **Confluence sizing** (§5 / bot_defaults.confluence_sizing): base 10% of capital at a
  2-member co-entry; +5% if an ELITE / List-A wallet also buys; +5% if 5+ distinct tracked
  wallets co-buy; hard cap 20% per token.
- **Chase-guard** (§3): abort if ``fill_price / trigger_price`` exceeds the guard (1.5–2×).
  Pyramiding is allowed only while the chase-guard holds.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# Abort a copy if the fill price has run more than this multiple past the trigger (§3).
DEFAULT_CHASE_GUARD_X = 2.0
# Pyramiding (adding to a position) is only allowed while fill <= this multiple of first entry.
DEFAULT_PYRAMID_MAX_X = 1.5


def confluence_size_pct(
    sizing_cfg: Dict,
    *,
    elite_or_list_a_present: bool,
    distinct_cobuyers: int,
) -> float:
    """Return the % of capital to deploy for a co-entry, per the bot_defaults ladder.

    ``sizing_cfg`` is ``bot_defaults["confluence_sizing"]``. Falls back to the documented
    defaults (10 base / +5 / +5 / cap 20) when keys are absent.
    """
    base = float(sizing_cfg.get("base_pct_per_trade", 10) or 10)
    cap = float(sizing_cfg.get("max_per_token_pct", 20) or 20)

    add_elite = 0.0
    add_breadth = 0.0
    for rung in sizing_cfg.get("ladder", []) or []:
        trig = (rung.get("trigger") or "").lower()
        add = float(rung.get("add_pct") or 0)
        if "elite" in trig or "list-a" in trig:
            add_elite = add or 5.0
        elif "5+" in trig or "distinct" in trig:
            add_breadth = add or 5.0
    # documented defaults if the ladder didn't specify add amounts
    if add_elite == 0.0:
        add_elite = 5.0
    if add_breadth == 0.0:
        add_breadth = 5.0

    size = base
    if elite_or_list_a_present:
        size += add_elite
    if distinct_cobuyers >= 5:
        size += add_breadth
    return round(min(size, cap), 2)


def chase_ratio(fill_price: Optional[float], trigger_price: Optional[float]) -> Optional[float]:
    if not fill_price or not trigger_price or trigger_price <= 0:
        return None
    return fill_price / trigger_price


def is_chase_abort(
    fill_price: Optional[float], trigger_price: Optional[float], guard_x: float = DEFAULT_CHASE_GUARD_X,
) -> bool:
    """True if the entry has chased too far past the trigger — skipping is correct (§3)."""
    ratio = chase_ratio(fill_price, trigger_price)
    return ratio is not None and ratio > guard_x


def can_pyramid(fill_price: Optional[float], first_entry_price: Optional[float],
                max_x: float = DEFAULT_PYRAMID_MAX_X) -> bool:
    """Add to a position only if the new fill is within ``max_x`` of the first entry."""
    ratio = chase_ratio(fill_price, first_entry_price)
    return ratio is not None and ratio <= max_x


def rank_candidates(candidates: List[Dict]) -> List[Dict]:
    """Order co-entry candidates by signal strength (desc) so caps take the top-N (§ limits)."""
    return sorted(candidates, key=lambda c: c.get("signal_strength", 0), reverse=True)
