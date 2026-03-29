import { useQuery } from '@tanstack/react-query';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

async function apiFetch(path: string, options?: RequestInit) {
  const res = await fetch(`${API_URL}${path}`, options);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export function useWatchlist(userId: string, token?: string) {
  return useQuery({
    queryKey: ['watchlist', userId],
    queryFn: () =>
      apiFetch(`/api/wallets/watchlist/table`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }),
    enabled: !!userId,
  });
}

export function useNotifications(userId: string, token?: string) {
  return useQuery({
    queryKey: ['notifications', userId],
    queryFn: () =>
      apiFetch(`/api/wallets/notifications?unread_only=false&limit=50`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function useTrendingRunners(timeframe = '7d') {
  return useQuery({
    queryKey: ['trending', timeframe],
    queryFn: () =>
      apiFetch(
        `/api/wallets/trending/runners?timeframe=${timeframe}&min_multiplier=5&min_liquidity=10000&min_volume=50000`
      ),
    staleTime: 60_000,
  });
}

export function useElite100() {
  return useQuery({
    queryKey: ['elite100'],
    queryFn: () => apiFetch(`/api/wallets/elite-100`),
    staleTime: 5 * 60_000,
  });
}

export function useAnalysisHistory(userId: string, token?: string) {
  return useQuery({
    queryKey: ['history', userId],
    queryFn: () =>
      apiFetch(`/api/wallets/history?limit=50`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }),
    enabled: !!userId,
  });
}
