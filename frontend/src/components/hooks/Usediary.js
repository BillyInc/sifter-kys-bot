/**
 * useDiary.js — optimistic fast open
 *
 * Speed strategy:
 *  1. Check sessionStorage SYNCHRONOUSLY on first render (no await, no network)
 *     → if key exists: initialized=true, locked=false immediately
 *     → diary renders instantly, notes load in background
 *  2. Salt fetch + notes fetch fire IN PARALLEL (not sequentially)
 *  3. No spinner for returning users in the same tab session
 *
 * First-time / locked users still go through the normal flow.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  isDiaryUnlocked,
  lockDiary,
  encryptNote,
  decryptNotes,
} from './Diaryencryption';

const LS_FALLBACK      = 'diary_fallback_';
const SESSION_KEY_NAME = 'diary_enc_key_b64'; // must match Diaryencryption.js

function lsGet(userId) {
  try { return JSON.parse(localStorage.getItem(LS_FALLBACK + userId) || '[]'); }
  catch { return []; }
}
function lsSet(userId, notes) {
  try { localStorage.setItem(LS_FALLBACK + userId, JSON.stringify(notes)); }
  catch (_) {}
}

/** Synchronous — just peeks at sessionStorage, no crypto */
function hasSessionKey() {
  try { return !!sessionStorage.getItem(SESSION_KEY_NAME); }
  catch { return false; }
}

/** Full async check with timeout fallback */
async function safeIsDiaryUnlocked() {
  try {
    return !!(await Promise.race([
      isDiaryUnlocked(),
      new Promise(resolve => setTimeout(() => resolve(false), 2000)),
    ]));
  } catch {
    return false;
  }
}

function makeApi(apiUrlRef) {
  const hdrs = { Accept: 'application/json', 'Content-Type': 'application/json' };
  const base = { credentials: 'include', mode: 'cors' };

  async function go(url, init = {}) {
    const res = await fetch(url, { ...base, headers: hdrs, ...init });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `HTTP ${res.status}`);
    return res.json();
  }

  return {
    getSalt:    (uid)                    => go(`${apiUrlRef.current}/api/diary/salt?user_id=${uid}`),
    getNotes:   (uid, wallet = null)     => go(`${apiUrlRef.current}/api/diary/notes?user_id=${uid}${wallet ? `&wallet_address=${wallet}` : ''}`),
    createNote: (uid, type, enc, wallet) => go(`${apiUrlRef.current}/api/diary/notes`, { method: 'POST', body: JSON.stringify({ user_id: uid, type, encrypted_payload: enc, wallet_address: wallet }) }),
    updateNote: (nid, uid, type, enc)   => go(`${apiUrlRef.current}/api/diary/notes/${nid}`, { method: 'PUT',  body: JSON.stringify({ user_id: uid, type, encrypted_payload: enc }) }),
    deleteNote: (nid, uid)              => go(`${apiUrlRef.current}/api/diary/notes/${nid}`, { method: 'DELETE', body: JSON.stringify({ user_id: uid }) }),
  };
}

export function useDiary({ userId, apiUrl, walletAddress = null }) {
  // ── Optimistic initial state ───────────────────────────────────────────────
  // Read sessionStorage synchronously — this is the key to instant open.
  // If the key is there we can skip the locked/spinner state entirely.
  const optimistic = hasSessionKey();

  const [notes, setNotes]                         = useState([]);
  const [loading, setLoading]                     = useState(true);
  const [error, setError]                         = useState(null);
  const [locked, setLocked]                       = useState(!optimistic);
  const [isNew, setIsNew]                         = useState(optimistic ? false : null);
  const [saltB64, setSaltB64]                     = useState(null);
  const [verificationToken, setVerificationToken] = useState(null);
  const [offline, setOffline]                     = useState(false);
  const [initialized, setInitialized]             = useState(optimistic);

  const mounted      = useRef(true);
  const loadNotesRef = useRef(null);
  const apiUrlRef    = useRef(apiUrl);
  const api          = useRef(makeApi(apiUrlRef)).current;
  apiUrlRef.current  = apiUrl;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const safe = (fn) => { if (mounted.current) fn(); };

  // ── Init effect ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!userId) return;
    let cancelled = false;

    (async () => {
      if (optimistic) {
        // Fast path: session key found synchronously.
        // Fire salt + notes fetches IN PARALLEL — don't wait for salt before notes.
        console.log('[useDiary] fast path: optimistic unlock');
        try {
          const [saltData, notesData] = await Promise.all([
            api.getSalt(userId),
            api.getNotes(userId, walletAddress),
          ]);
          if (cancelled) return;

          // If the server says this is a new user (race condition / account reset),
          // fall back to showing the setup screen
          if (saltData.is_new) {
            safe(() => {
              setSaltB64(null);
              setVerificationToken(null);
              setIsNew(true);
              setLocked(true);
              setLoading(false);
            });
            return;
          }

          const decrypted = await decryptNotes(notesData.notes);
          if (cancelled) return;

          safe(() => {
            setSaltB64(saltData.salt_b64);
            setVerificationToken(saltData.verification_token);
            setIsNew(false);
            setNotes(decrypted);
            setLoading(false);
          });

        } catch (err) {
          if (cancelled) return;
          console.warn('[useDiary] fast path error (offline?):', err.message);
          // Offline — show local notes
          const local = lsGet(userId).filter(n =>
            walletAddress ? n.walletAddress === walletAddress : true
          );
          safe(() => {
            setOffline(true);
            setNotes(local);
            setIsNew(false);
            setLoading(false);
          });
        }

      } else {
        // Slow path: no session key — need to check properly
        console.log('[useDiary] slow path: no session key');
        safe(() => {
          setLoading(true);
          setError(null);
          setInitialized(false);
          setLocked(true);
          setIsNew(null);
          setNotes([]);
        });

        try {
          const data = await api.getSalt(userId);
          if (cancelled) return;

          safe(() => {
            setSaltB64(data.salt_b64);
            setVerificationToken(data.verification_token);
            setIsNew(data.is_new);
          });

          if (data.is_new) {
            safe(() => { setLocked(true); setLoading(false); setInitialized(true); });
            return;
          }

          const alreadyUnlocked = await safeIsDiaryUnlocked();
          if (cancelled) return;

          safe(() => {
            setLocked(!alreadyUnlocked);
            setLoading(false);
            setInitialized(true);
          });

        } catch (err) {
          if (cancelled) return;
          const alreadyUnlocked = await safeIsDiaryUnlocked();
          if (cancelled) return;
          safe(() => {
            setOffline(true);
            setError(err.message);
            setLocked(!alreadyUnlocked);
            setIsNew(false);
            setLoading(false);
            setInitialized(true);
          });
        }
      }
    })();

    return () => { cancelled = true; };
  }, [userId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Load notes after unlock (slow path only) ───────────────────────────────
  useEffect(() => {
    if (!initialized || locked || !userId || optimistic) return;
    let cancelled = false;

    const loadNotes = async () => {
      safe(() => { setLoading(true); setError(null); });

      if (offline) {
        const local = lsGet(userId).filter(n =>
          walletAddress ? n.walletAddress === walletAddress : true
        );
        if (!cancelled) safe(() => { setNotes(local); setLoading(false); });
        return;
      }

      try {
        const data      = await api.getNotes(userId, walletAddress);
        const decrypted = await decryptNotes(data.notes);
        if (!cancelled) safe(() => { setNotes(decrypted); setLoading(false); });
      } catch (err) {
        console.error('[useDiary] loadNotes:', err);
        if (!cancelled) {
          safe(() => { setError('Failed to load notes.'); setLoading(false); });
          const local = lsGet(userId);
          if (local.length) safe(() => setNotes(local));
        }
      }
    };

    loadNotesRef.current = loadNotes;
    loadNotes();
    return () => { cancelled = true; };
  }, [initialized, locked, userId, walletAddress, offline]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── onUnlocked ─────────────────────────────────────────────────────────────
  const onUnlocked = useCallback((newSaltData = null) => {
    console.log('[useDiary] onUnlocked');
    if (newSaltData) {
      safe(() => {
        setSaltB64(newSaltData.saltB64);
        setVerificationToken(newSaltData.verificationToken);
        setIsNew(false);
      });
    }
    safe(() => setLocked(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const lock = useCallback(() => {
    lockDiary();
    safe(() => { setLocked(true); setNotes([]); });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = useCallback(() => {
    if (loadNotesRef.current) loadNotesRef.current();
  }, []);

  // ── CRUD ──────────────────────────────────────────────────────────────────
  const addNote = useCallback(async ({ type, text, tags = [], walletRef = null }) => {
    const w = walletRef || walletAddress || null;
    if (offline) {
      const note = { id: Date.now().toString(), type, text, tags, walletAddress: w, walletRef: w, createdAt: Date.now(), editedAt: null, source: w ? 'wallet' : 'global' };
      lsSet(userId, [note, ...lsGet(userId)]);
      safe(() => setNotes(prev => [note, ...prev]));
      return note;
    }
    try {
      const enc  = await encryptNote({ text, tags });
      const data = await api.createNote(userId, type, enc, w);
      const note = { id: data.id, type, text, tags, walletAddress: w, walletRef: w, createdAt: Date.now(), editedAt: null, source: w ? 'wallet' : 'global' };
      safe(() => setNotes(prev => [note, ...prev]));
      return note;
    } catch (err) {
      console.error('[useDiary] addNote:', err);
      safe(() => setError('Failed to save note.'));
      return null;
    }
  }, [userId, walletAddress, offline]); // eslint-disable-line react-hooks/exhaustive-deps

  const updateNote = useCallback(async (noteId, { type, text, tags }) => {
    if (offline) {
      const updated = lsGet(userId).map(n => n.id === noteId ? { ...n, type, text, tags, editedAt: Date.now() } : n);
      lsSet(userId, updated);
      safe(() => setNotes(updated.filter(n => walletAddress ? n.walletAddress === walletAddress : true)));
      return true;
    }
    try {
      await api.updateNote(noteId, userId, type, await encryptNote({ text, tags }));
      safe(() => setNotes(prev => prev.map(n => n.id === noteId ? { ...n, type, text, tags, editedAt: Date.now() } : n)));
      return true;
    } catch (err) {
      console.error('[useDiary] updateNote:', err);
      safe(() => setError('Failed to update note.'));
      return false;
    }
  }, [userId, walletAddress, offline]); // eslint-disable-line react-hooks/exhaustive-deps

  const deleteNote = useCallback(async (noteId) => {
    if (offline) {
      lsSet(userId, lsGet(userId).filter(n => n.id !== noteId));
      safe(() => setNotes(prev => prev.filter(n => n.id !== noteId)));
      return true;
    }
    try {
      await api.deleteNote(noteId, userId);
      safe(() => setNotes(prev => prev.filter(n => n.id !== noteId)));
      return true;
    } catch (err) {
      console.error('[useDiary] deleteNote:', err);
      safe(() => setError('Failed to delete note.'));
      return false;
    }
  }, [userId, offline]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Loading stub — only for slow path (no session key) ────────────────────
  if (!initialized && userId) {
    return {
      notes: [], loading: true, error: null,
      locked: true, isNew: null,
      saltB64: null, verificationToken: null,
      onUnlocked, lock,
      offline: false,
      addNote: async () => null, updateNote: async () => false,
      deleteNote: async () => false, refresh: () => {},
    };
  }

  return {
    notes, loading, error,
    locked, isNew, saltB64, verificationToken,
    onUnlocked, lock, offline,
    addNote, updateNote, deleteNote, refresh,
  };
}

export function useGlobalDiary({ userId, apiUrl }) {
  return useDiary({ userId, apiUrl, walletAddress: null });
}