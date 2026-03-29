// hooks/useRecents.js
// Manages recent analysis results via Supabase (permanent, cross-device).
// Replaces Redis 6hr TTL — results persist indefinitely, capped at 50 per user.
//
// FIXES APPLIED:
//   Fix 1 — Stray 's' after clearAll closing brace removed (syntax error)
//   Fix 2 — Switched from Redis /api/user/recents to Supabase /api/wallets/history
//            Results are now permanent, no TTL, accessible across sessions/devices.
//
// Schema required:
//   sifter.user_analysis_history (
//     id uuid pk, user_id uuid, result_type text,
//     label text, sublabel text, data jsonb, created_at timestamptz
//   )
//   + index on (user_id, created_at desc)
//   + auto-prune trigger keeping last 50 per user

import { useState, useEffect, useCallback } from 'react';

const MAX_RECENTS = 50;   // backend trigger also enforces this

export function buildRecentEntry({ label, sublabel, data, resultType }) {
  return {
    id:         `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    resultType,
    label,
    sublabel,
    timestamp:  Date.now(),
    data,
  };
}

export function useRecents({ apiUrl, userId, getAccessToken }) {
  // Note: panelKey removed — history is global per user, not scoped per panel.
  // If you need panel-scoped views, filter on resultType in the UI instead.

  const [recents, setRecents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  // ── Auth headers ────────────────────────────────────────────────────────────
  const authHeaders = useCallback(() => {
    const token = getAccessToken?.();
    return token
      ? { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' }
      : { 'Content-Type': 'application/json' };
  }, [getAccessToken]);

  // ── Load from Supabase via backend ──────────────────────────────────────────
  const loadRecents = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const res  = await fetch(
        `${apiUrl}/api/wallets/history?user_id=${userId}&limit=${MAX_RECENTS}`,
        { headers: authHeaders() }
      );
      const data = await res.json();
      if (data.success) {
        setRecents(data.recents || []);
      } else {
        setError(data.error || 'Failed to load history');
      }
    } catch (e) {
      console.error('[RECENTS] Load error:', e);
      setError('Could not reach server');
    } finally {
      setLoading(false);
    }
  }, [apiUrl, userId, authHeaders]);

  useEffect(() => {
    loadRecents();
  }, [loadRecents]);

  // ── Save result — persists to Supabase, no TTL ──────────────────────────────
  const saveResult = useCallback(async ({ label, sublabel, data, resultType }) => {
    const entry = buildRecentEntry({ label, sublabel, data, resultType });

    // Optimistic update — feels instant
    setRecents(prev => [entry, ...prev].slice(0, MAX_RECENTS));

    try {
      await fetch(`${apiUrl}/api/wallets/history`, {
        method:  'POST',
        headers: authHeaders(),
        body:    JSON.stringify({ user_id: userId, entry }),
      });
    } catch (e) {
      console.error('[RECENTS] Save error:', e);
      // Optimistic update stays visible even on network failure
    }
  }, [apiUrl, userId, authHeaders]);

  // ── Remove single entry ─────────────────────────────────────────────────────
  const removeResult = useCallback(async (id) => {
    setRecents(prev => prev.filter(r => r.id !== id)); // optimistic

    try {
      await fetch(`${apiUrl}/api/wallets/history/${id}`, {
        method:  'DELETE',
        headers: authHeaders(),
        body:    JSON.stringify({ user_id: userId }),
      });
    } catch (e) {
      console.error('[RECENTS] Remove error:', e);
      loadRecents(); // revert on failure
    }
  }, [apiUrl, userId, authHeaders, loadRecents]);

  // ── Clear all — FIX 1: stray 's' after closing brace removed ───────────────
  const clearAll = useCallback(async () => {
    setRecents([]); // optimistic

    try {
      await fetch(`${apiUrl}/api/wallets/history/all`, {
        method:  'DELETE',
        headers: authHeaders(),
        body:    JSON.stringify({ user_id: userId }),
      });
    } catch (e) {
      console.error('[RECENTS] Clear error:', e);
      loadRecents(); // revert on failure
    }
    // FIX 1: was `}s` here — the stray 's' caused a syntax error that
    // broke the entire hook silently in some bundlers
  }, [apiUrl, userId, authHeaders, loadRecents]);

  return {
    recents,
    loading,
    error,
    saveResult,
    removeResult,
    clearAll,
    refreshRecents: loadRecents,
  };
}