/**
 * useDiary.js
 *
 * React hook for encrypted diary. Passphrase-based key derivation edition.
 *
 * The hook does NOT handle passphrase prompting — that's delegated to
 * DiaryUnlock.jsx. Instead, it:
 *   1. On mount, fetches salt + verification_token from the backend
 *   2. Checks if the diary is already unlocked (sessionStorage key present)
 *   3. If locked, sets `locked = true` so the parent can show DiaryUnlock
 *   4. Once unlocked (key in session), loads + decrypts notes
 *
 * Usage:
 *   const diary = useDiary({ userId, apiUrl, walletAddress });
 *
 *   diary.locked           – true = show <DiaryUnlock> before anything else
 *   diary.isNew            – true = user hasn't set a passphrase yet
 *   diary.saltB64          – pass to DiaryUnlock for setup/unlock
 *   diary.verificationToken – pass to DiaryUnlock for unlock verification
 *   diary.onUnlocked()     – call after DiaryUnlock succeeds to reload notes
 *   diary.notes            – decrypted note objects
 *   diary.loading          – fetching/decrypting
 *   diary.error            – string | null
 *   diary.addNote(data)    – { type, text, tags, walletRef? }
 *   diary.updateNote(id, data)
 *   diary.deleteNote(id)
 *   diary.refresh()
 *   diary.lock()           – clear session key and re-lock
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  isDiaryUnlocked,
  lockDiary,
  encryptNote,
  decryptNotes,
} from './diaryEncryption';

const LS_FALLBACK = 'diary_fallback_';

function lsGet(userId) {
  try { return JSON.parse(localStorage.getItem(LS_FALLBACK + userId) || '[]'); }
  catch { return []; }
}
function lsSet(userId, notes) {
  try { localStorage.setItem(LS_FALLBACK + userId, JSON.stringify(notes)); }
  catch (_) {}
}

export function useDiary({ userId, apiUrl, walletAddress = null }) {
  const [notes,              setNotes]              = useState([]);
  const [loading,            setLoading]            = useState(true);
  const [error,              setError]              = useState(null);
  const [locked,             setLocked]             = useState(true);  // until proven otherwise
  const [isNew,              setIsNew]              = useState(false);  // no passphrase yet
  const [saltB64,            setSaltB64]            = useState(null);
  const [verificationToken,  setVerificationToken]  = useState(null);
  const [offline,            setOffline]            = useState(false);
  const initDone = useRef(false);

  // ── Step 1: fetch salt info + check session ────────────────────────────────
  const init = useCallback(async () => {
    if (!userId || initDone.current) return;
    initDone.current = true;
    setLoading(true);

    try {
      const res  = await fetch(`${apiUrl}/api/diary/salt?user_id=${userId}`);
      const data = await res.json();
      if (!data.success) throw new Error(data.error);

      setSaltB64(data.salt_b64);
      setVerificationToken(data.verification_token);
      setIsNew(data.is_new);

      if (data.is_new) {
        // No passphrase set yet — show setup UI
        setLocked(true);
        setLoading(false);
        return;
      }

      // Check if already unlocked this session
      const alreadyUnlocked = await isDiaryUnlocked();
      if (alreadyUnlocked) {
        setLocked(false);
      } else {
        setLocked(true);
        setLoading(false);
      }
    } catch (err) {
      console.warn('[useDiary] init failed, going offline:', err.message);
      setOffline(true);
      // Offline: check if we have a session key cached
      const alreadyUnlocked = await isDiaryUnlocked();
      setLocked(!alreadyUnlocked);
      setLoading(false);
    }
  }, [userId, apiUrl]);

  // ── Step 2: load notes (only when unlocked) ────────────────────────────────
  const loadNotes = useCallback(async () => {
    if (!userId || locked) return;
    setLoading(true);
    setError(null);

    if (offline) {
      const local = lsGet(userId).filter(n =>
        walletAddress ? n.walletAddress === walletAddress : true
      );
      setNotes(local);
      setLoading(false);
      return;
    }

    try {
      const params = new URLSearchParams({ user_id: userId });
      if (walletAddress) params.set('wallet_address', walletAddress);

      const res  = await fetch(`${apiUrl}/api/diary/notes?${params}`);
      const data = await res.json();
      if (!data.success) throw new Error(data.error);

      const decrypted = await decryptNotes(data.notes);
      setNotes(decrypted);
    } catch (err) {
      console.error('[useDiary] loadNotes:', err);
      setError('Failed to load notes.');
      const local = lsGet(userId);
      if (local.length) setNotes(local);
    } finally {
      setLoading(false);
    }
  }, [userId, apiUrl, walletAddress, locked, offline]);

  // ── Called by DiaryUnlock after successful unlock/setup ───────────────────
  const onUnlocked = useCallback(() => {
    setLocked(false);
  }, []);

  const lock = useCallback(() => {
    lockDiary();
    setLocked(true);
    setNotes([]);
  }, []);

  // ── CRUD ──────────────────────────────────────────────────────────────────
  const addNote = useCallback(async ({ type, text, tags = [], walletRef = null }) => {
    const resolvedWallet = walletRef || walletAddress || null;

    if (offline) {
      const note = {
        id: Date.now().toString(), type, text, tags,
        walletAddress: resolvedWallet, walletRef: resolvedWallet,
        createdAt: Date.now(), editedAt: null,
        source: resolvedWallet ? 'wallet' : 'global',
      };
      const updated = [note, ...lsGet(userId)];
      lsSet(userId, updated);
      setNotes(prev => [note, ...prev]);
      return note;
    }

    try {
      const encryptedPayload = await encryptNote({ text, tags });
      const res  = await fetch(`${apiUrl}/api/diary/notes`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId, type,
          encrypted_payload: encryptedPayload,
          wallet_address: resolvedWallet,
        }),
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error);

      const note = {
        id: data.id, type, text, tags,
        walletAddress: resolvedWallet, walletRef: resolvedWallet,
        createdAt: Date.now(), editedAt: null,
        source: resolvedWallet ? 'wallet' : 'global',
      };
      setNotes(prev => [note, ...prev]);
      return note;
    } catch (err) {
      console.error('[useDiary] addNote:', err);
      setError('Failed to save note.');
      return null;
    }
  }, [userId, apiUrl, walletAddress, offline]);

  const updateNote = useCallback(async (noteId, { type, text, tags }) => {
    if (offline) {
      const updated = lsGet(userId).map(n =>
        n.id === noteId ? { ...n, type, text, tags, editedAt: Date.now() } : n
      );
      lsSet(userId, updated);
      setNotes(updated.filter(n => walletAddress ? n.walletAddress === walletAddress : true));
      return true;
    }
    try {
      const encryptedPayload = await encryptNote({ text, tags });
      const res  = await fetch(`${apiUrl}/api/diary/notes/${noteId}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, type, encrypted_payload: encryptedPayload }),
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error);
      setNotes(prev => prev.map(n =>
        n.id === noteId ? { ...n, type, text, tags, editedAt: Date.now() } : n
      ));
      return true;
    } catch (err) {
      console.error('[useDiary] updateNote:', err);
      setError('Failed to update note.');
      return false;
    }
  }, [userId, apiUrl, walletAddress, offline]);

  const deleteNote = useCallback(async (noteId) => {
    if (offline) {
      const updated = lsGet(userId).filter(n => n.id !== noteId);
      lsSet(userId, updated);
      setNotes(prev => prev.filter(n => n.id !== noteId));
      return true;
    }
    try {
      const res  = await fetch(`${apiUrl}/api/diary/notes/${noteId}`, {
        method: 'DELETE', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId }),
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error);
      setNotes(prev => prev.filter(n => n.id !== noteId));
      return true;
    } catch (err) {
      console.error('[useDiary] deleteNote:', err);
      setError('Failed to delete note.');
      return false;
    }
  }, [userId, apiUrl, offline]);

  // ── Lifecycle ─────────────────────────────────────────────────────────────
  useEffect(() => {
    initDone.current = false;
    setLocked(true);
    setNotes([]);
    setSaltB64(null);
    setVerificationToken(null);
    init();
  }, [userId]); // eslint-disable-line

  useEffect(() => {
    if (!locked) loadNotes();
  }, [locked, walletAddress]); // eslint-disable-line

  return {
    notes, loading, error, locked, isNew,
    saltB64, verificationToken,
    onUnlocked, lock,
    offline,
    addNote, updateNote, deleteNote,
    refresh: loadNotes,
  };
}

export function useGlobalDiary({ userId, apiUrl }) {
  return useDiary({ userId, apiUrl, walletAddress: null });
}