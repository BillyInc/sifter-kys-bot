"""Security attack simulations for the copy-trading bot.

Verifies bot_security defends against the real copy-trade attack surface:
address poisoning, ticker/mint mimicry, transfer-in activity faking, dust bait.

These import bot_security in isolation (no heavy services.__init__), so they run
even when the full venv isn't synced.
"""

import importlib.util
import os
import sys
import types

import pytest

# Import bot_security without triggering services/__init__ (which pulls in
# wallet_analyzer -> opentelemetry etc.).
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if "services" not in sys.modules:
    pkg = types.ModuleType("services")
    pkg.__path__ = [os.path.join(_PKG_DIR, "services")]
    sys.modules["services"] = pkg

_spec = importlib.util.spec_from_file_location(
    "bot_security", os.path.join(_PKG_DIR, "services", "bot_security.py")
)
bot_security = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bot_security)


ELITE = {
    "Abc123RealEliteWalletXXXXXXXXXXXXXXXXXXXXXXXX",
    "Def456AnotherEliteWalletYYYYYYYYYYYYYYYYYYYYYY",
}
GOOD_MINT = "M" * 44


def _signal(**over):
    base = {
        "token_address": GOOD_MINT,
        "usd_value": 500,
        "side": "buy",
        "wallet_address": next(iter(ELITE)),
    }
    base.update(over)
    return base


class TestAddressPoisoning:
    def test_exact_elite_wallet_passes(self):
        assert bot_security.verify_elite_wallet(next(iter(ELITE)), ELITE) is True

    def test_lookalike_rejected(self):
        real = "Abc123RealEliteWalletXXXXXXXXXXXXXXXXXXXXXXXX"
        poison = "Abc1ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZXXXX"  # same first4/last4
        assert bot_security.verify_elite_wallet(poison, ELITE) is False
        assert bot_security.looks_like_poisoning(poison, ELITE) is True

    def test_screen_flags_poisoning(self):
        real = "Abc123RealEliteWalletXXXXXXXXXXXXXXXXXXXXXXXX"
        poison = real[:4] + "Z" * (len(real) - 8) + real[-4:]
        ok, reason = bot_security.security_screen(
            _signal(wallet_address=poison), ELITE,
            require_elite_wallet=True, check_liquidity=False,
        )
        assert ok is False
        assert reason == "address_poisoning"


class TestMimicry:
    def test_transfer_in_rejected(self):
        ok, reason = bot_security.verify_signal_provenance({"event_type": "transfer"})
        assert ok is False and reason == "non_swap_event"

    def test_airdrop_rejected(self):
        ok, reason = bot_security.verify_signal_provenance({"event_type": "airdrop"})
        assert ok is False

    def test_genuine_buy_passes(self):
        ok, _ = bot_security.verify_signal_provenance({"side": "buy"})
        assert ok is True

    def test_invalid_mint_rejected(self):
        ok, reason = bot_security.verify_token_mint({"token_address": "TOO_SHORT"}, fetch_canonical=False)
        assert ok is False and reason == "invalid_mint"


class TestDustBait:
    def test_dust_rejected(self):
        ok, reason = bot_security.verify_not_dust({"usd_value": 5})
        assert ok is False and reason == "dust_value"

    def test_real_value_passes(self):
        ok, _ = bot_security.verify_not_dust({"usd_value": 500})
        assert ok is True


class TestFullScreen:
    def test_legit_autonomous_signal_passes(self):
        ok, reason = bot_security.security_screen(
            _signal(), ELITE, require_elite_wallet=True, check_liquidity=False,
        )
        assert ok is True, f"unexpected reject: {reason}"

    def test_non_elite_wallet_rejected(self):
        ok, reason = bot_security.security_screen(
            _signal(wallet_address="TotallyUnrelatedWallet" + "Q" * 22),
            ELITE, require_elite_wallet=True, check_liquidity=False,
        )
        assert ok is False and reason == "wallet_not_elite"

    def test_manual_skips_wallet_check(self):
        # Manual trades: user picked the token; wallet provenance not required.
        ok, _ = bot_security.security_screen(
            _signal(wallet_address=""), ELITE,
            require_elite_wallet=False, check_liquidity=False,
        )
        assert ok is True
