/**
 * diaryEncryption.js
 *
 * Client-side AES-256-GCM encryption for watchlist diary notes.
 * The backend (Supabase) only ever stores ciphertext — plaintext
 * never leaves the browser. The encryption key is derived from:
 *
 *   PBKDF2(userId + ":" + passphrase, salt, 310_000 iterations) → AES-256-GCM key
 *
 * Key properties:
 *  - The passphrase is set once by the user and never sent to the server
 *  - The salt is random per-user, stored in Supabase (safe to store — useless without passphrase)
 *  - Without both the userId AND the passphrase, the salt is worthless
 *  - The derived key is cached in sessionStorage for the browser session
 *    so the user only needs to enter the passphrase once per tab session
 *
 * Encrypted payload format (base64-encoded JSON):
 *   { iv: <base64>, ct: <base64> }
 *
 * Session storage key: 'diary_enc_key_b64'
 * The stored value is the raw 256-bit derived key bytes (base64), NOT the passphrase.
 * The passphrase itself is never persisted anywhere.
 */

const PBKDF2_ITERATIONS  = 310_000;  // OWASP 2023 recommendation
const KEY_SESSION_STORE  = 'diary_enc_key_b64';
const MIN_PASSPHRASE_LEN = 8;

// ─── Internal helpers ──────────────────────────────────────────────────────────

function b64ToBytes(b64) {
  return Uint8Array.from(atob(b64), c => c.charCodeAt(0));
}

function bytesToB64(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)));
}

async function importRawKey(rawBytes) {
  return crypto.subtle.importKey(
    'raw', rawBytes,
    { name: 'AES-GCM', length: 256 },
    false,          // not extractable after import
    ['encrypt', 'decrypt']
  );
}

// ─── In-memory key cache ───────────────────────────────────────────────────────
// Holds the CryptoKey for the current JS context lifetime.
// Survives React re-renders; cleared on tab close or explicit logout.
let _keyCache = null;

// ─── Key derivation ────────────────────────────────────────────────────────────

/**
 * Derive a 256-bit key from userId + passphrase + salt using PBKDF2-SHA256.
 * @param {string}     userId
 * @param {string}     passphrase  – user-supplied, never stored
 * @param {Uint8Array} saltBytes   – 32 random bytes stored in Supabase
 * @returns {Promise<{ key: CryptoKey, rawBits: ArrayBuffer }>}
 */
async function deriveKeyFromPassphrase(userId, passphrase, saltBytes) {
  const enc     = new TextEncoder();
  const keyMat  = await crypto.subtle.importKey(
    'raw',
    enc.encode(`${userId}:${passphrase}`),
    { name: 'PBKDF2' },
    false,
    ['deriveBits']
  );
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt: saltBytes, iterations: PBKDF2_ITERATIONS, hash: 'SHA-256' },
    keyMat,
    256
  );
  const key = await importRawKey(bits);
  return { key, rawBits: bits };
}

// ─── Session cache helpers ─────────────────────────────────────────────────────

function cacheKeyInSession(rawBits) {
  try { sessionStorage.setItem(KEY_SESSION_STORE, bytesToB64(rawBits)); } catch (_) {}
}

async function loadKeyFromSession() {
  if (_keyCache) return _keyCache;
  try {
    const stored = sessionStorage.getItem(KEY_SESSION_STORE);
    if (stored) {
      _keyCache = await importRawKey(b64ToBytes(stored));
      return _keyCache;
    }
  } catch (_) {
    sessionStorage.removeItem(KEY_SESSION_STORE);
  }
  return null;
}

// ─── Verification token ────────────────────────────────────────────────────────
// We store a small verification blob in Supabase so we can detect a wrong
// passphrase before attempting to decrypt real notes (better UX than silent
// garbage output).
//
// Format: encrypt the static plaintext "diary_verify_v1" with the derived key.
// On unlock, try to decrypt it — if it throws, the passphrase is wrong.
const VERIFY_PLAINTEXT = 'diary_verify_v1';

export async function createVerificationToken(userId, passphrase, saltB64) {
  const { key, rawBits } = await deriveKeyFromPassphrase(userId, passphrase, b64ToBytes(saltB64));
  const iv  = crypto.getRandomValues(new Uint8Array(12));
  const enc = new TextEncoder();
  const ct  = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, enc.encode(VERIFY_PLAINTEXT));
  return btoa(JSON.stringify({ iv: bytesToB64(iv), ct: bytesToB64(ct) }));
}

export async function verifyPassphrase(userId, passphrase, saltB64, verificationTokenB64) {
  try {
    const { key, rawBits } = await deriveKeyFromPassphrase(userId, passphrase, b64ToBytes(saltB64));
    const { iv, ct }       = JSON.parse(atob(verificationTokenB64));
    const dec              = new TextDecoder();
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: b64ToBytes(iv) },
      key,
      b64ToBytes(ct)
    );
    if (dec.decode(plain) !== VERIFY_PLAINTEXT) return false;
    // Correct — cache the key
    _keyCache = key;
    cacheKeyInSession(rawBits);
    return true;
  } catch {
    return false;
  }
}

// ─── Public API ────────────────────────────────────────────────────────────────

export const passphraseRequirements = {
  minLength: MIN_PASSPHRASE_LEN,
  validate(p) {
    if (!p || p.length < MIN_PASSPHRASE_LEN) return `Passphrase must be at least ${MIN_PASSPHRASE_LEN} characters.`;
    return null; // valid
  },
};

/**
 * First-time setup: initialise encryption for a new user.
 * Call when the user sets their passphrase for the first time.
 *
 * @returns {{ saltB64, verificationToken }} — both must be saved to Supabase
 */
export async function setupDiaryEncryption(userId, passphrase) {
  const error = passphraseRequirements.validate(passphrase);
  if (error) throw new Error(error);

  const saltBytes = crypto.getRandomValues(new Uint8Array(32));
  const saltB64   = bytesToB64(saltBytes);

  const { key, rawBits }   = await deriveKeyFromPassphrase(userId, passphrase, saltBytes);
  const verificationToken  = await createVerificationToken(userId, passphrase, saltB64);

  _keyCache = key;
  cacheKeyInSession(rawBits);

  return { saltB64, verificationToken };
}

/**
 * Returning user: unlock diary with their passphrase.
 * Returns true if passphrase is correct, false otherwise.
 */
export async function unlockDiary(userId, passphrase, saltB64, verificationToken) {
  return verifyPassphrase(userId, passphrase, saltB64, verificationToken);
}

/**
 * Check if the diary is already unlocked for this session
 * (passphrase was entered earlier in this tab session).
 */
export async function isDiaryUnlocked() {
  const key = await loadKeyFromSession();
  return key !== null;
}

/** Lock the diary — clears key from memory and sessionStorage */
export function lockDiary() {
  _keyCache = null;
  sessionStorage.removeItem(KEY_SESSION_STORE);
}

// ─── Encrypt / decrypt ─────────────────────────────────────────────────────────

async function getKey() {
  const key = _keyCache || await loadKeyFromSession();
  if (!key) throw new Error('Diary is locked. Please enter your passphrase.');
  return key;
}

/**
 * Encrypt { text, tags } into a base64 ciphertext blob.
 */
export async function encryptNote(plainPayload) {
  const key = await getKey();
  const iv  = crypto.getRandomValues(new Uint8Array(12));
  const enc = new TextEncoder();
  const ct  = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    enc.encode(JSON.stringify(plainPayload))
  );
  return btoa(JSON.stringify({ iv: bytesToB64(iv), ct: bytesToB64(ct) }));
}

/**
 * Decrypt a ciphertext blob back to { text, tags }.
 * Returns null on failure (wrong key, corrupted data).
 */
export async function decryptNote(encryptedPayloadB64) {
  try {
    const key        = await getKey();
    const { iv, ct } = JSON.parse(atob(encryptedPayloadB64));
    const dec        = new TextDecoder();
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: b64ToBytes(iv) },
      key,
      b64ToBytes(ct)
    );
    return JSON.parse(dec.decode(plain));
  } catch (err) {
    console.warn('[diary] decryptNote failed:', err.message);
    return null;
  }
}

/**
 * Decrypt an array of Supabase rows in parallel.
 * Rows that fail decryption are silently omitted.
 */
export async function decryptNotes(rows) {
  const results = await Promise.all(
    rows.map(async row => {
      const payload = await decryptNote(row.encrypted_payload);
      if (!payload) return null;
      return {
        id:            row.id,
        type:          row.type,
        walletAddress: row.wallet_address ?? null,
        walletRef:     row.wallet_address ?? null,
        createdAt:     new Date(row.created_at).getTime(),
        editedAt:      row.edited_at ? new Date(row.edited_at).getTime() : null,
        source:        row.wallet_address ? 'wallet' : 'global',
        text:          payload.text,
        tags:          payload.tags || [],
      };
    })
  );
  return results.filter(Boolean);
}