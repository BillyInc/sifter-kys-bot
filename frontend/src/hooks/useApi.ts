import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

async function apiFetch(path: string, options?: RequestInit) {
  const res = await fetch(`${API_URL}${path}`, options);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

function authHeaders(token?: string, contentType = false): Record<string, string> {
  const h: Record<string, string> = {};
  if (token) h['Authorization'] = `Bearer ${token}`;
  if (contentType) h['Content-Type'] = 'application/json';
  return h;
}

export function useWatchlist(userId: string, token?: string) {
  return useQuery({
    queryKey: ['watchlist', userId],
    queryFn: () =>
      apiFetch(`/api/wallets/watchlist/table`, {
        headers: authHeaders(token),
      }),
    enabled: !!userId,
  });
}

export function useRefreshWallet(token?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (addr: string) =>
      apiFetch(`/api/wallets/watchlist/${addr}/refresh`, {
        method: 'POST',
        headers: authHeaders(token, true),
        body: JSON.stringify({ wallet_address: addr }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
    },
  });
}

export function useDeleteWallet(token?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (addr: string) =>
      apiFetch(`/api/wallets/watchlist/remove`, {
        method: 'POST',
        headers: authHeaders(token, true),
        body: JSON.stringify({ wallet_address: addr }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
    },
  });
}

export function useNotifications(userId: string, token?: string) {
  return useQuery({
    queryKey: ['notifications', userId],
    queryFn: () =>
      apiFetch(`/api/wallets/notifications?unread_only=false&limit=50`, {
        headers: authHeaders(token),
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

export function useElite100(userId: string, sortBy = 'score', isPremium = false) {
  return useQuery({
    queryKey: ['elite100', userId, sortBy],
    queryFn: () =>
      apiFetch(`/api/wallets/premium-elite-100?user_id=${userId}&sort_by=${sortBy}`),
    enabled: isPremium,
    staleTime: 5 * 60_000,
  });
}

export function useTop100Community(userId: string) {
  return useQuery({
    queryKey: ['top100community', userId],
    queryFn: () =>
      apiFetch(`/api/wallets/top-100-community?user_id=${userId}`),
    enabled: !!userId,
  });
}

export function useDashboardStats(userId: string) {
  return useQuery({
    queryKey: ['dashboardStats', userId],
    queryFn: () =>
      apiFetch(`/api/user/dashboard-stats?user_id=${userId}`),
    enabled: !!userId,
    staleTime: 30_000,
  });
}

export function useAnalysisHistory(userId: string, token?: string) {
  return useQuery({
    queryKey: ['history', userId],
    queryFn: () =>
      apiFetch(`/api/wallets/history?limit=50`, {
        headers: authHeaders(token),
      }),
    enabled: !!userId,
  });
}
