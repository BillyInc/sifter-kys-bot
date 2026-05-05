"""Shared execution rules for Elite 15 paper/live trading."""

from __future__ import annotations

from dataclasses import dataclass


TAKE_PROFIT_MULTIPLIERS = (5.0, 10.0, 20.0, 30.0)
EXIT_FRACTIONS = {
    5.0: 0.25,
    10.0: 0.333,
    20.0: 0.50,
    30.0: 1.0,
}
MAX_POSITION_SHARE = 0.40
ACTIVE_TRADING_BALANCE_SHARE = 0.10
SINGLE_SIGNAL_SHARE_OF_TRADING_BALANCE = 0.30
FOLLOW_ON_SHARE_OF_TRADING_BALANCE = 0.70
DEFAULT_HOURLY_TRADE_LIMIT = 1
DEFAULT_DAILY_TRADE_LIMIT = 8
DEFAULT_MIN_ELITE_USD = 100.0


@dataclass(frozen=True)
class PositionSizingResult:
    wallet_count: int
    signal_type: str
    recommended_usd: float
    capped: bool


def classify_signal(wallet_count: int) -> str:
    if wallet_count >= 3:
        return "mega"
    if wallet_count == 2:
        return "double"
    return "single"


def calculate_position_size(
    portfolio_total: float,
    wallet_count: int,
    existing_position: float = 0.0,
    total_exposure: float = 0.0,
) -> PositionSizingResult:
    """Mirror the mobile bot's position sizing policy."""
    trading_balance = portfolio_total * ACTIVE_TRADING_BALANCE_SHARE
    signal_type = classify_signal(wallet_count)

    if wallet_count >= 3:
        new_size = portfolio_total * MAX_POSITION_SHARE
    elif wallet_count == 2:
        new_size = trading_balance if existing_position == 0 else trading_balance * FOLLOW_ON_SHARE_OF_TRADING_BALANCE
    else:
        new_size = (
            trading_balance * SINGLE_SIGNAL_SHARE_OF_TRADING_BALANCE
            if existing_position == 0
            else trading_balance * FOLLOW_ON_SHARE_OF_TRADING_BALANCE
        )

    capped = False
    per_token_cap = portfolio_total * MAX_POSITION_SHARE
    if existing_position + new_size > per_token_cap:
        new_size = max(0.0, per_token_cap - existing_position)
        capped = True

    if total_exposure + new_size > portfolio_total:
        new_size = max(0.0, portfolio_total - total_exposure)
        capped = True

    return PositionSizingResult(
        wallet_count=wallet_count,
        signal_type=signal_type,
        recommended_usd=round(new_size, 2),
        capped=capped,
    )


def recommended_fraction_for_wallet_count(wallet_count: int) -> float:
    """Fallback fraction for channels that only know a per-trade max amount."""
    if wallet_count >= 3:
        return 1.0
    if wallet_count == 2:
        return 1.0
    return SINGLE_SIGNAL_SHARE_OF_TRADING_BALANCE
