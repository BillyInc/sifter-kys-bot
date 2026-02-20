// hooks/useRecentResults.js
import { useState, useEffect, useCallback } from 'react';

const MAX_RECENT = 10;

/**
 * Persists recent analysis results per panel type using window.storage.
 * panelKey: 'analyze' | 'trending' | 'discovery'
 */
export function useRecentResults(panelKey) {
  const storageKey = `recent_results:${panelKey}`;
  const [recents, setRecents] = useState([]);
  const [loading, setLoading] = useState(true);

  // Load on mount
  useEffect(() => {
    (async () => {
      try {
        const result = await window.storage.get(storageKey);
        if (result?.value) {
          setRecents(JSON.parse(result.value));
        }
      } catch {
        // key doesn't exist yet — fine
      } finally {
        setLoading(false);
      }
    })();
  }, [storageKey]);

  const saveResult = useCallback(async ({ label, sublabel, data, resultType }) => {
    const entry = {
      id:         Date.now(),
      label,       // e.g. "PEPE • 11 wallets"
      sublabel,    // e.g. "General Analysis"
      resultType,
      data,
      timestamp:  Date.now(),
    };

    setRecents(prev => {
      const updated = [entry, ...prev.filter(r => r.id !== entry.id)].slice(0, MAX_RECENT);
      window.storage.set(storageKey, JSON.stringify(updated)).catch(() => {});
      return updated;
    });
  }, [storageKey]);

  const removeResult = useCallback(async (id) => {
    setRecents(prev => {
      const updated = prev.filter(r => r.id !== id);
      window.storage.set(storageKey, JSON.stringify(updated)).catch(() => {});
      return updated;
    });
  }, [storageKey]);

  const clearAll = useCallback(async () => {
    setRecents([]);
    window.storage.delete(storageKey).catch(() => {});
  }, [storageKey]);

  return { recents, loading, saveResult, removeResult, clearAll };
}