/**
 * DiaryUnlock.jsx
 *
 * Two-mode component shown when the diary is locked:
 *
 *  SETUP mode (isNew = true):
 *    User is setting their passphrase for the first time.
 *    - Shows passphrase + confirm fields
 *    - Derives key, generates salt + verification_token
 *    - POSTs salt + verification_token to /api/diary/salt
 *    - Calls onUnlocked() on success
 *
 *  UNLOCK mode (isNew = false):
 *    User has a passphrase set — just needs to enter it.
 *    - Derives key and verifies against stored verification_token
 *    - Calls onUnlocked() on success
 *    - Shows error if passphrase is wrong
 *
 * Props:
 *   userId             – string
 *   apiUrl             – string
 *   isNew              – bool
 *   saltB64            – string | null  (null when isNew)
 *   verificationToken  – string | null  (null when isNew)
 *   onUnlocked         – () => void
 */

import React, { useState, useRef, useEffect } from 'react';
import { Lock, Eye, EyeOff, KeyRound, ShieldCheck, AlertCircle, Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { setupDiaryEncryption, unlockDiary, passphraseRequirements } from './diaryEncryption';

export default function DiaryUnlock({ userId, apiUrl, isNew, saltB64, verificationToken, onUnlocked }) {
  const [passphrase,    setPassphrase]    = useState('');
  const [confirm,       setConfirm]       = useState('');
  const [showPass,      setShowPass]      = useState(false);
  const [showConfirm,   setShowConfirm]   = useState(false);
  const [loading,       setLoading]       = useState(false);
  const [error,         setError]         = useState(null);
  const [strength,      setStrength]      = useState(0); // 0-4
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  // ── Passphrase strength indicator ──────────────────────────────────────────
  useEffect(() => {
    if (!passphrase) { setStrength(0); return; }
    let score = 0;
    if (passphrase.length >= 8)  score++;
    if (passphrase.length >= 14) score++;
    if (/[A-Z]/.test(passphrase) && /[a-z]/.test(passphrase)) score++;
    if (/[0-9!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?]/.test(passphrase)) score++;
    setStrength(score);
  }, [passphrase]);

  const strengthLabel  = ['', 'Weak', 'Fair', 'Good', 'Strong'][strength];
  const strengthColor  = ['', 'text-red-400', 'text-yellow-400', 'text-blue-400', 'text-green-400'][strength];
  const strengthBg     = ['bg-white/10', 'bg-red-500', 'bg-yellow-500', 'bg-blue-500', 'bg-green-500'][strength];

  // ── Setup (first time) ─────────────────────────────────────────────────────
  const handleSetup = async () => {
    setError(null);
    const validationError = passphraseRequirements.validate(passphrase);
    if (validationError) { setError(validationError); return; }
    if (passphrase !== confirm) { setError('Passphrases do not match.'); return; }

    setLoading(true);
    try {
      const { saltB64: newSalt, verificationToken: newToken } = await setupDiaryEncryption(userId, passphrase);

      const res  = await fetch(`${apiUrl}/api/diary/salt`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id:            userId,
          salt_b64:           newSalt,
          verification_token: newToken,
        }),
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || 'Failed to save passphrase.');

      onUnlocked();
    } catch (err) {
      setError(err.message || 'Setup failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // ── Unlock (returning user) ────────────────────────────────────────────────
  const handleUnlock = async () => {
    setError(null);
    if (!passphrase) { setError('Please enter your passphrase.'); return; }

    setLoading(true);
    try {
      const ok = await unlockDiary(userId, passphrase, saltB64, verificationToken);
      if (!ok) {
        setError('Incorrect passphrase. Please try again.');
        setPassphrase('');
        inputRef.current?.focus();
        return;
      }
      onUnlocked();
    } catch (err) {
      setError(err.message || 'Unlock failed.');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') isNew ? handleSetup() : handleUnlock();
  };

  // ── Shared input style ─────────────────────────────────────────────────────
  const inputCls = "w-full bg-black/60 border border-white/10 rounded-xl px-4 py-3 pr-11 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-purple-500/60 transition font-mono tracking-widest";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-10 px-4"
    >
      <div className="w-full max-w-sm space-y-6">

        {/* Icon + heading */}
        <div className="text-center space-y-3">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-purple-500/15 border border-purple-500/25 mx-auto">
            {isNew ? <KeyRound size={24} className="text-purple-400" /> : <Lock size={24} className="text-purple-400" />}
          </div>
          <div>
            <h3 className="font-bold text-base text-gray-100">
              {isNew ? 'Set a diary passphrase' : 'Unlock your diary'}
            </h3>
            <p className="text-xs text-gray-500 mt-1 leading-relaxed">
              {isNew
                ? 'Your notes are encrypted before leaving your device. Choose a passphrase — it\'s never sent to the server.'
                : 'Your notes are end-to-end encrypted. Enter your passphrase to decrypt them.'}
            </p>
          </div>
        </div>

        {/* Passphrase field */}
        <div className="space-y-3">
          <div className="relative">
            <input
              ref={inputRef}
              type={showPass ? 'text' : 'password'}
              value={passphrase}
              onChange={e => setPassphrase(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isNew ? 'Choose a passphrase' : 'Enter your passphrase'}
              className={inputCls}
              autoComplete={isNew ? 'new-password' : 'current-password'}
            />
            <button
              type="button"
              onClick={() => setShowPass(v => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400 transition"
            >
              {showPass ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>

          {/* Strength bar (setup only) */}
          {isNew && passphrase && (
            <div className="space-y-1">
              <div className="flex gap-1">
                {[1, 2, 3, 4].map(i => (
                  <div key={i} className={`h-1 flex-1 rounded-full transition-all duration-300 ${i <= strength ? strengthBg : 'bg-white/10'}`} />
                ))}
              </div>
              <p className={`text-[10px] font-semibold ${strengthColor}`}>{strengthLabel}</p>
            </div>
          )}

          {/* Confirm field (setup only) */}
          {isNew && (
            <div className="relative">
              <input
                type={showConfirm ? 'text' : 'password'}
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Confirm passphrase"
                className={inputCls + (confirm && confirm !== passphrase ? ' border-red-500/40' : '')}
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowConfirm(v => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400 transition"
              >
                {showConfirm ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2.5">
            <AlertCircle size={13} className="shrink-0" />
            {error}
          </motion.div>
        )}

        {/* Submit button */}
        <button
          onClick={isNew ? handleSetup : handleUnlock}
          disabled={loading || !passphrase || (isNew && !confirm)}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 rounded-xl text-sm font-bold text-white transition"
        >
          {loading
            ? <><Loader2 size={15} className="animate-spin" /> {isNew ? 'Encrypting…' : 'Unlocking…'}</>
            : isNew
              ? <><ShieldCheck size={15} /> Set passphrase & open diary</>
              : <><Lock size={15} /> Unlock diary</>
          }
        </button>

        {/* Security note */}
        <p className="text-[10px] text-gray-700 text-center leading-relaxed">
          {isNew
            ? '⚠️ This passphrase cannot be recovered. If you forget it, your notes cannot be decrypted.'
            : '🔒 Decryption happens entirely in your browser.'}
        </p>

      </div>
    </motion.div>
  );
}