import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';
import DatabaseService from '../database/DatabaseService';
import apiClient from '../services/ApiClient';

// ── Price cache (module-level, shared across store calls) ──────────────
const priceCache: Record<string, { price: number; ts: number }> = {};
const PRICE_TTL = 30000; // 30 seconds

interface Settings {
  autoTradeEnabled: boolean;
  minBuyUsd: number;
  signalWindowSeconds: number;
  degradationDays: number;
  degradationMinRoi: number;
  autoReplaceWallets: boolean;
  [key: string]: any;
}

interface StoreState {
  user: any;
  userTier: string;
  tradingMode: string;
  portfolioTotal: number;
  tradingBalance: number;
  elite15: any[];
  watchlist: any[];
  activeTrades: any[];
  notifications: any[];
  settings: Settings;
  isLoading: boolean;
  error: string | null;
  totalPnl?: number;
  setUser: (user: any) => void;
  setUserTier: (tier: string) => void;
  setTradingMode: (mode: string) => Promise<void>;
  loadElite15: () => Promise<void>;
  refreshElite15: () => Promise<void>;
  loadWatchlist: () => Promise<void>;
  refreshWatchlist: () => Promise<void>;
  addToWatchlist: (walletAddress: string, autoReplace: boolean) => Promise<void>;
  removeFromWatchlist: (walletAddress: string) => Promise<void>;
  loadActiveTrades: () => Promise<void>;
  addTrade: (trade: any) => Promise<number>;
  updateTradeTP: (tradeId: number, tpLevel: number, sellAmount: number, price: number, usdValue: number, txSignature: string) => Promise<void>;
  closeTrade: (tradeId: number, finalPrice: number, finalUsd: number, txSignature: string) => Promise<void>;
  updateSettings: (newSettings: Partial<Settings>) => Promise<void>;
  loadNotifications: () => Promise<void>;
  refreshNotifications: () => Promise<void>;
  addNotification: (notification: any) => Promise<void>;
  markNotificationRead: (id: number) => Promise<void>;
  clearError: () => void;
  getCurrentPrice: (tokenAddress: string) => Promise<number>;
  refreshPrices: () => Promise<void>;
}

const useStore = create<StoreState>()(
  persist(
    (set, get) => ({
      // ── User ──────────────────────────────────────────────
      user: null,
      userTier: 'free',       // 'free' | 'premium' — set from your web dashboard
      tradingMode: 'auto',    // 'auto' | 'manual' — premium users can toggle

      // ── Portfolio ─────────────────────────────────────────
      portfolioTotal: 10000,
      tradingBalance: 1000,

      // ── Trading data ──────────────────────────────────────
      elite15: [],
      watchlist: [],
      activeTrades: [],
      notifications: [],

      // ── Settings ──────────────────────────────────────────
      settings: {
        autoTradeEnabled: true,
        minBuyUsd: 100,
        signalWindowSeconds: 15,
        degradationDays: 7,
        degradationMinRoi: 5,
        autoReplaceWallets: true
      },

      // ── UI state ──────────────────────────────────────────
      isLoading: false,
      error: null,

      // ── User actions ──────────────────────────────────────
      setUser: (user: any) => {
        set({ user });
        // Pass auth token to API client when user logs in
        if (user?.access_token) {
          apiClient.setAuthToken(user.access_token);
        }
      },

      // Called when your web dashboard confirms upgrade
      setUserTier: (tier: string) => set({ userTier: tier }),

      // Premium users toggle auto ↔ manual instantly
      setTradingMode: async (mode: string) => {
        set({ tradingMode: mode });
        await DatabaseService.saveUserPreference('trading_mode', mode);
      },

      // ── Elite 15 ──────────────────────────────────────────
      loadElite15: async () => {
        set({ isLoading: true });
        try {
          const elite15 = await DatabaseService.getElite15();
          set({ elite15, isLoading: false });
        } catch (error: any) {
          set({ error: error.message, isLoading: false });
        }
      },

      // Fetch fresh Elite data from the backend API and sync to local DB
      refreshElite15: async () => {
        set({ isLoading: true });
        try {
          const data = await apiClient.getElite100();
          const wallets = data.wallets || data.elite_100 || data;
          if (Array.isArray(wallets) && wallets.length > 0) {
            await DatabaseService.syncElite15(wallets);
          }
          const elite15 = await DatabaseService.getElite15();
          set({ elite15, isLoading: false });
        } catch (error: any) {
          // Fall back to local data on API failure
          const elite15 = await DatabaseService.getElite15();
          set({ elite15, error: error.message, isLoading: false });
        }
      },

      // ── Watchlist ─────────────────────────────────────────
      loadWatchlist: async () => {
        const watchlist = await DatabaseService.getWatchlist();
        set({ watchlist });
      },

      // Fetch watchlist from backend API (enriched with scoring)
      refreshWatchlist: async () => {
        try {
          const data = await apiClient.getWatchlist();
          const wallets = data.watchlist || data;
          set({ watchlist: Array.isArray(wallets) ? wallets : [] });
        } catch (error: any) {
          // Fall back to local data
          const watchlist = await DatabaseService.getWatchlist();
          set({ watchlist, error: error.message });
        }
      },

      addToWatchlist: async (walletAddress: string, autoReplace: boolean) => {
        await DatabaseService.addToWatchlist(walletAddress, autoReplace);
        await get().loadWatchlist();
      },

      removeFromWatchlist: async (walletAddress: string) => {
        await DatabaseService.removeFromWatchlist(walletAddress);
        await get().loadWatchlist();
      },

      // ── Active trades ─────────────────────────────────────
      loadActiveTrades: async () => {
        const trades = await DatabaseService.getActiveTrades();
        let totalPnl = 0;
        for (const trade of trades) {
          const currentPrice = await get().getCurrentPrice(trade.token_address);
          if (currentPrice) {
            const currentValue = trade.remaining_size * (currentPrice / trade.entry_price);
            trade.currentValue = currentValue;
            trade.pnl = currentValue - trade.entry_size;
            totalPnl += trade.pnl;
          }
        }
        set({ activeTrades: trades, totalPnl });
      },

      addTrade: async (trade: any) => {
        const tradeId = await DatabaseService.addTrade(trade);
        await get().loadActiveTrades();
        return tradeId;
      },

      updateTradeTP: async (tradeId: number, tpLevel: number, sellAmount: number, price: number, usdValue: number, txSignature: string) => {
        await DatabaseService.updateTradeAfterTP(tradeId, tpLevel, sellAmount, price, usdValue, txSignature);
        await get().loadActiveTrades();
      },

      closeTrade: async (tradeId: number, finalPrice: number, finalUsd: number, txSignature: string) => {
        await DatabaseService.closeTrade(tradeId, finalPrice, finalUsd, txSignature);
        await get().loadActiveTrades();
      },

      // ── Settings ──────────────────────────────────────────
      updateSettings: async (newSettings: Partial<Settings>) => {
        const current = get().settings;
        const updated = { ...current, ...newSettings };
        for (const [key, value] of Object.entries(newSettings)) {
          await DatabaseService.setSetting(key, String(value));
        }
        set({ settings: updated as Settings });
        const portfolioTotal = parseFloat(await DatabaseService.getSetting('portfolio_total') || '10000') || 10000;
        const tradingPercent = parseFloat(await DatabaseService.getSetting('trading_percent') || '0.10') || 0.10;
        set({ portfolioTotal, tradingBalance: portfolioTotal * tradingPercent });
      },

      // ── Notifications ─────────────────────────────────────
      loadNotifications: async () => {
        const notifications = await DatabaseService.getUnreadNotifications();
        set({ notifications });
      },

      // Fetch notifications from backend API
      refreshNotifications: async () => {
        try {
          const data = await apiClient.getNotifications();
          const notifications = data.notifications || data;
          set({ notifications: Array.isArray(notifications) ? notifications : [] });
        } catch (error: any) {
          // Fall back to local data
          const notifications = await DatabaseService.getUnreadNotifications();
          set({ notifications, error: error.message });
        }
      },

      addNotification: async (notification: any) => {
        await DatabaseService.addNotification(notification);
        await get().loadNotifications();
      },

      markNotificationRead: async (id: number) => {
        await DatabaseService.markNotificationRead(id);
        await get().loadNotifications();
      },

      clearError: () => set({ error: null }),

      // ── Price oracle ──────────────────────────────────────
      getCurrentPrice: async (tokenAddress: string): Promise<number> => {
        const cached = priceCache[tokenAddress];
        if (cached && Date.now() - cached.ts < PRICE_TTL) return cached.price;

        // Attempt 1: SolanaTracker
        try {
          const res = await fetch(`https://data.solanatracker.io/tokens/${tokenAddress}`, {
            headers: { 'x-api-key': process.env.SOLANATRACKER_API_KEY || '' }
          });
          const data = await res.json();
          const price = data?.pools?.[0]?.price?.usd || 0;
          if (price > 0) {
            priceCache[tokenAddress] = { price, ts: Date.now() };
            return price;
          }
        } catch {
          // fall through to Birdeye
        }

        // Attempt 2: Birdeye fallback
        try {
          const res = await fetch(
            `https://public-api.birdeye.so/defi/price?address=${tokenAddress}`,
            { headers: { 'X-API-KEY': process.env.BIRDEYE_API_KEY || '' } }
          );
          const data = await res.json();
          const price = data?.data?.value || 0;
          if (price > 0) {
            priceCache[tokenAddress] = { price, ts: Date.now() };
            return price;
          }
        } catch {
          // fall through to cached
        }

        // Fallback: return stale cache or 0
        return cached?.price || 0;
      },

      // ── Batch refresh prices for all active positions ─────
      refreshPrices: async () => {
        const trades = get().activeTrades;
        const uniqueTokens = [...new Set(trades.map((t: any) => t.token_address))];
        await Promise.allSettled(
          uniqueTokens.map((addr: string) => get().getCurrentPrice(addr))
        );
        // Reload trades to recalculate PnL with fresh prices
        await get().loadActiveTrades();
      },
    }),
    {
      name: 'sifter-storage',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state: StoreState) => ({
        user: state.user,
        userTier: state.userTier,
        tradingMode: state.tradingMode,
        portfolioTotal: state.portfolioTotal,
        settings: state.settings
      })
    }
  )
);

export default useStore;
