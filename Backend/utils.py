"""
Shared scoring utilities used by wallet_analyzer.py and worker_tasks.py.
"""
import math


def _roi_to_score(multiplier, ceiling=1000):
    """
    Logarithmic ROI → score conversion.

    Replaces the broken `avg_total_roi / 10 * 100` formula which produced
    unbounded scores (500+ for a 50x token) that overwhelmed the 60%
    entry timing component.

    Score table:
      1x    →   0
      5x    →  23.3
      10x   →  33.3
      50x   →  56.7
      100x  →  66.7
      500x  →  89.9
      1000x → 100

    Args:
        multiplier: Total ROI as a multiplier (e.g. 10 for 10x).
                    Values <= 1 return 0 (no gain or loss).
        ceiling:    Multiplier that maps to 100. Default 1000x.

    Returns:
        float in [0, 100]
    """
    if not multiplier or multiplier <= 1:
        return 0.0
    return min(100.0, (math.log10(multiplier) / math.log10(ceiling)) * 100)