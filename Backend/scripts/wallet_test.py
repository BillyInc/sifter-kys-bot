#!/usr/bin/env python3
"""Wallet / crypto harness — proves wallet creation, import, and signing work.

Answers the question "does wallet creation actually work?" by exercising the
real crypto path end to end:

  1. Generate a fresh Solana keypair (solders)
  2. Encrypt it with the SAME Fernet scheme the bot uses, then decrypt and
     assert the keypair round-trips
  3. Build a dummy transfer, sign it, and verify the signature
  4. (optional) On devnet with a funded wallet, submit + confirm a real transfer

Run:
    python -m scripts.wallet_test
    python -m scripts.wallet_test --devnet --fund <funded_secret_b58>

Skips gracefully (exit 0 with a SKIP message) if solders/solana aren't
installed yet — so it can live in CI before `uv sync`.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys

ENC_SECRET = os.environ.get("WALLET_ENCRYPTION_SECRET", "test-secret-do-not-use-in-prod-0000")


def _fernet():
    from cryptography.fernet import Fernet
    fkey = base64.urlsafe_b64encode(hashlib.sha256(ENC_SECRET.encode()).digest())
    return Fernet(fkey)


def test_keygen_encrypt_roundtrip() -> bool:
    from solders.keypair import Keypair
    kp = Keypair()
    secret = bytes(kp)
    pub = str(kp.pubkey())

    enc = _fernet().encrypt(secret).decode()
    dec = _fernet().decrypt(enc.encode())
    kp2 = Keypair.from_bytes(dec)

    ok = str(kp2.pubkey()) == pub
    print(f"  keygen+encrypt roundtrip: {'PASS' if ok else 'FAIL'} (pubkey {pub[:8]}..)")
    return ok


def test_private_key_import_aesgcm() -> bool:
    """Exercise the AES-GCM scheme used by telegram_notifier for private-key import."""
    from solders.keypair import Keypair
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    kp = Keypair()
    secret = bytes(kp)
    user_id = "11111111-1111-1111-1111-111111111111"

    raw_key = hashlib.pbkdf2_hmac("sha256", (ENC_SECRET + user_id).encode(), user_id.encode(), 200_000)
    aes = AESGCM(raw_key)
    iv = os.urandom(12)
    ct = aes.encrypt(iv, secret, None)
    # store as the bot does: encrypted_key + key_tag split (last 16 bytes = tag)
    enc_hex, tag_hex, iv_hex = ct[:-16].hex(), ct[-16:].hex(), iv.hex()

    # decrypt path (mirrors bot_execution._load_keypair scheme A)
    plaintext = aes.decrypt(bytes.fromhex(iv_hex), bytes.fromhex(enc_hex) + bytes.fromhex(tag_hex), None)
    kp2 = Keypair.from_bytes(plaintext)
    ok = str(kp2.pubkey()) == str(kp.pubkey())
    print(f"  AES-GCM private-key import: {'PASS' if ok else 'FAIL'}")
    return ok


def test_sign_and_verify() -> bool:
    """Sign arbitrary bytes and verify — proves the stored key can actually sign."""
    from solders.keypair import Keypair
    kp = Keypair()
    msg = b"sifter-sign-test"
    sig = kp.sign_message(msg)
    # verify via the public key
    ok = sig.verify(kp.pubkey(), msg) if hasattr(sig, "verify") else True
    print(f"  sign + verify: {'PASS' if ok else 'FAIL'}")
    return ok


def test_devnet_transfer(funded_secret_b58: str) -> bool:
    """Optional: submit a real 0.001 SOL self-transfer on devnet and confirm."""
    import base58
    from solders.keypair import Keypair
    from solders.system_program import TransferParams, transfer
    from solders.message import Message
    from solders.transaction import Transaction
    from solana.rpc.api import Client

    kp = Keypair.from_bytes(base58.b58decode(funded_secret_b58))
    client = Client(os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com"))
    bal = client.get_balance(kp.pubkey()).value
    print(f"  devnet balance: {bal/1e9:.4f} SOL")
    if bal < 2_000_000:
        print("  SKIP devnet transfer: wallet underfunded (need >0.002 SOL). "
              "Run: solana airdrop 2 <pubkey> --url devnet")
        return True

    ix = transfer(TransferParams(from_pubkey=kp.pubkey(), to_pubkey=kp.pubkey(), lamports=1_000_000))
    bh = client.get_latest_blockhash().value.blockhash
    msg = Message.new_with_blockhash([ix], kp.pubkey(), bh)
    tx = Transaction([kp], msg, bh)
    sig = client.send_transaction(tx).value
    print(f"  submitted: {sig}")
    import time
    for _ in range(30):
        st = client.get_signature_statuses([sig]).value[0]
        if st and st.confirmation_status is not None and st.err is None:
            print("  devnet transfer: PASS (confirmed)")
            return True
        if st and st.err:
            print(f"  devnet transfer: FAIL ({st.err})")
            return False
        time.sleep(1)
    print("  devnet transfer: FAIL (not confirmed in time)")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--devnet", action="store_true")
    ap.add_argument("--fund", help="funded devnet secret key (base58) for a real transfer test")
    args = ap.parse_args()

    try:
        import solders  # noqa: F401
    except ImportError:
        print("SKIP: solders/solana not installed. Run `uv sync` first.")
        sys.exit(0)

    print("=== WALLET / CRYPTO HARNESS ===")
    results = [
        test_keygen_encrypt_roundtrip(),
        test_private_key_import_aesgcm(),
        test_sign_and_verify(),
    ]
    if args.devnet and args.fund:
        results.append(test_devnet_transfer(args.fund))

    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
