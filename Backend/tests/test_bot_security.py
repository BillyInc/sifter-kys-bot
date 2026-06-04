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
            check_token_safety_gate=False,
        )
        assert ok is True, f"unexpected reject: {reason}"

    def test_non_elite_wallet_rejected(self):
        ok, reason = bot_security.security_screen(
            _signal(wallet_address="TotallyUnrelatedWallet" + "Q" * 22),
            ELITE, require_elite_wallet=True, check_liquidity=False,
            check_token_safety_gate=False,
        )
        assert ok is False and reason == "wallet_not_elite"

    def test_manual_skips_wallet_check(self):
        # Manual trades: user picked the token; wallet provenance not required.
        ok, _ = bot_security.security_screen(
            _signal(wallet_address=""), ELITE,
            require_elite_wallet=False, check_liquidity=False,
            check_token_safety_gate=False,
        )
        assert ok is True


# ── Token-level rug gate (check_token_safety) ───────────────────────────────

def _token_info(*, mint=None, freeze=None, rugged=False, lp_burn=100,
                market="raydium", liquidity=50_000):
    """Build a SolanaTracker get_token_info-shaped response."""
    return {
        "token": {"symbol": "WIF", "name": "dogwifhat"},
        "risk": {"rugged": rugged},
        "pools": [{
            "liquidity": {"usd": liquidity},
            "price": {"usd": 0.01},
            "lpBurn": lp_burn,
            "market": market,
            "security": {"mintAuthority": mint, "freezeAuthority": freeze},
        }],
    }


class TestCheckTokenSafety:
    def test_clean_token_passes(self):
        ok, reason = bot_security.check_token_safety("TOK", token_info=_token_info())
        assert ok is True and reason is None

    def test_mint_authority_active_blocks(self):
        info = _token_info(mint="SomeMintAuthority1111111111111111111111111111")
        ok, reason = bot_security.check_token_safety("TOK", token_info=info)
        assert ok is False and reason == "mint_not_revoked"

    def test_freeze_authority_active_blocks(self):
        info = _token_info(freeze="SomeFreezeAuthority111111111111111111111111111")
        ok, reason = bot_security.check_token_safety("TOK", token_info=info)
        assert ok is False and reason == "freeze_not_revoked"

    def test_rugged_blocks(self):
        ok, reason = bot_security.check_token_safety("TOK", token_info=_token_info(rugged=True))
        assert ok is False and reason == "rugged"

    def test_raydium_unburned_lp_blocks(self):
        info = _token_info(lp_burn=0, market="raydium")
        ok, reason = bot_security.check_token_safety("TOK", token_info=info)
        assert ok is False and reason == "lp_not_burned"

    def test_pumpfun_zero_lp_passes(self):
        # Pre-graduation pump.fun: lpBurn is legitimately 0.
        info = _token_info(lp_burn=0, market="pumpfun")
        ok, reason = bot_security.check_token_safety("TOK", token_info=info)
        assert ok is True and reason is None

    def test_raydium_burned_lp_passes(self):
        info = _token_info(lp_burn=100, market="raydium")
        ok, reason = bot_security.check_token_safety("TOK", token_info=info)
        assert ok is True

    def test_none_token_info_fails_closed(self):
        ok, reason = bot_security.check_token_safety("TOK", token_info=None)
        # token_info=None forces a client lookup; the isolated test env has no
        # ST client, so the lazy import/network fails → fail closed.
        assert ok is False and reason == "security_unavailable"

    def test_empty_pools_fails_closed(self):
        ok, reason = bot_security.check_token_safety("TOK", token_info={"pools": []})
        assert ok is False and reason == "security_unavailable"

    def test_mint_active_beats_everything_else_clean(self):
        # Even with burned LP + not rugged, an active mint authority blocks.
        info = _token_info(mint="X" * 44, lp_burn=100, rugged=False)
        ok, reason = bot_security.check_token_safety("TOK", token_info=info)
        assert ok is False and reason == "mint_not_revoked"

    def test_picks_deepest_liquidity_pool(self):
        info = _token_info()
        # Prepend a shallow pool with an ACTIVE mint authority; the deep pool
        # (clean) must win.
        info["pools"].insert(0, {
            "liquidity": {"usd": 10},
            "lpBurn": 0, "market": "raydium",
            "security": {"mintAuthority": "Active" + "1" * 38, "freezeAuthority": None},
        })
        ok, reason = bot_security.check_token_safety("TOK", token_info=info)
        assert ok is True, f"deepest-pool selection failed: {reason}"


class TestScreenWithSafetyGate:
    """security_screen should fold check_token_safety into its decision."""

    def test_safety_gate_blocks_in_screen(self):
        # A signal whose token is unsafe is rejected by the screen even though
        # provenance/dust/wallet are fine. Patch the gate to report unsafe.
        orig = bot_security.check_token_safety
        bot_security.check_token_safety = lambda *a, **k: (False, "rugged")
        try:
            ok, reason = bot_security.security_screen(
                _signal(), ELITE, require_elite_wallet=True, check_liquidity=False,
            )
        finally:
            bot_security.check_token_safety = orig
        assert ok is False and reason == "rugged"

    def test_safety_gate_pass_allows_screen(self):
        orig = bot_security.check_token_safety
        bot_security.check_token_safety = lambda *a, **k: (True, None)
        try:
            ok, reason = bot_security.security_screen(
                _signal(), ELITE, require_elite_wallet=True, check_liquidity=False,
            )
        finally:
            bot_security.check_token_safety = orig
        assert ok is True, f"unexpected reject: {reason}"
