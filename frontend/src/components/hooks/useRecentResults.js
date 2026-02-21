// hooks/useRecents.js
// Manages recent analysis results via Redis-backed API (6hr TTL, cross-device).
// Scoped by panelKey ('analyze' | 'trending' | 'discovery') so each panel
// maintains its own recent list independently.

import { useState, useEffect, useCallback } from 'react';

const MAX_RECENTS = 10;

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

export function useRecents({ apiUrl, userId, getAccessToken, panelKey }) {
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

  // ── Panel-scoped user id ────────────────────────────────────────────────────
  // Appending panelKey to userId scopes recents per panel on the backend
  const scopedUserId = panelKey ? `${userId}:${panelKey}` : userId;

  // ── Load from API ───────────────────────────────────────────────────────────
  const loadRecents = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const res  = await fetch(`${apiUrl}/api/user/recents?user_id=${scopedUserId}`, {
        headers: authHeaders(),
      });
      const data = await res.json();
      if (data.success) {
        setRecents(data.recents || []);
      } else {
        setError(data.error || 'Failed to load recents');
      }
    } catch (e) {
      console.error('[RECENTS] Load error:', e);
      setError('Could not reach server');
    } finally {
      setLoading(false);
    }
  }, [apiUrl, scopedUserId, authHeaders, userId]);

  useEffect(() => {
    loadRecents();
  }, [loadRecents]);

  // ── Add entry ───────────────────────────────────────────────────────────────
  const saveResult = useCallback(async ({ label, sublabel, data, resultType }) => {
    const entry = buildRecentEntry({ label, sublabel, data, resultType });

    // Optimistic update — feels instant
    setRecents(prev => [entry, ...prev].slice(0, MAX_RECENTS));

    try {
      await fetch(`${apiUrl}/api/user/recents`, {
        method:  'POST',
        headers: authHeaders(),
        body:    JSON.stringify({ user_id: scopedUserId, entry }),
      });
    } catch (e) {
      console.error('[RECENTS] Add error:', e);
      // Optimistic update stays — user sees result either way
    }
  }, [apiUrl, scopedUserId, authHeaders]);

  // ── Remove single entry ─────────────────────────────────────────────────────
  const removeResult = useCallback(async (id) => {
    setRecents(prev => prev.filter(r => r.id !== id)); // optimistic

    try {
      await fetch(`${apiUrl}/api/user/recents/${id}`, {
        method:  'DELETE',
        headers: authHeaders(),
        body:    JSON.stringify({ user_id: scopedUserId }),
      });
    } catch (e) {
      console.error('[RECENTS] Remove error:', e);
      loadRecents(); // revert on failure
    }
  }, [apiUrl, scopedUserId, authHeaders, loadRecents]);

  // ── Clear all ───────────────────────────────────────────────────────────────
  const clearAll = useCallback(async () => {
    setRecents([]); // optimistic

    try {
      await fetch(`${apiUrl}/api/user/recents`, {
        method:  'DELETE',
        headers: authHeaders(),
        body:    JSON.stringify({ user_id: scopedUserId }),
      });
    } catch (e) {
      console.error('[RECENTS] Clear error:', e);
      loadRecents(); // revert on failure
    }s
  }, [apiUrl, scopedUserId, authHeaders, loadRecents]);

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