import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';
import DatabaseService from '../database/DatabaseService';

// ── Price cache (module-level, shared across store calls) ──────────────
const priceCache = {};
const PRICE_TTL = 30000; // 30 seconds

const useStore = create(
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
      setUser: (user) => set({ user }),

      // Called when your web dashboard confirms upgrade
      setUserTier: (tier) => set({ userTier: tier }),

      // Premium users toggle auto ↔ manual instantly
      setTradingMode: async (mode) => {
        set({ tradingMode: mode });
        await DatabaseService.saveUserPreference('trading_mode', mode);
      },

      // ── Elite 15 ──────────────────────────────────────────
      loadElite15: async () => {
        set({ isLoading: true });
        try {
          const elite15 = await DatabaseService.getElite15();
          set({ elite15, isLoading: false });
        } catch (error) {
          set({ error: error.message, isLoading: false });
        }
      },

      // ── Watchlist ─────────────────────────────────────────
      loadWatchlist: async () => {
        const watchlist = await DatabaseService.getWatchlist();
        set({ watchlist });
      },

      addToWatchlist: async (walletAddress, autoReplace) => {
        await DatabaseService.addToWatchlist(walletAddress, autoReplace);
        await get().loadWatchlist();
      },

      removeFromWatchlist: async (walletAddress) => {
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

      addTrade: async (trade) => {
        const tradeId = await DatabaseService.addTrade(trade);
        await get().loadActiveTrades();
        return tradeId;
      },

      updateTradeTP: async (tradeId, tpLevel, sellAmount, price, usdValue, txSignature) => {
        await DatabaseService.updateTradeAfterTP(tradeId, tpLevel, sellAmount, price, usdValue, txSignature);
        await get().loadActiveTrades();
      },

      closeTrade: async (tradeId, finalPrice, finalUsd, txSignature) => {
        await DatabaseService.closeTrade(tradeId, finalPrice, finalUsd, txSignature);
        await get().loadActiveTrades();
      },

      // ── Settings ──────────────────────────────────────────
      updateSettings: async (newSettings) => {
        const current = get().settings;
        const updated = { ...current, ...newSettings };
        for (const [key, value] of Object.entries(newSettings)) {
          await DatabaseService.setSetting(key, value.toString());
        }
        set({ settings: updated });
        const portfolioTotal = parseFloat(await DatabaseService.getSetting('portfolio_total')) || 10000;
        const tradingPercent = parseFloat(await DatabaseService.getSetting('trading_percent')) || 0.10;
        set({ portfolioTotal, tradingBalance: portfolioTotal * tradingPercent });
      },

      // ── Notifications ─────────────────────────────────────
      loadNotifications: async () => {
        const notifications = await DatabaseService.getUnreadNotifications();
        set({ notifications });
      },

      addNotification: async (notification) => {
        await DatabaseService.addNotification(notification);
        await get().loadNotifications();
      },

      markNotificationRead: async (id) => {
        await DatabaseService.markNotificationRead(id);
        await get().loadNotifications();
      },

      clearError: () => set({ error: null }),

      // ── Price oracle ──────────────────────────────────────
      getCurrentPrice: async (tokenAddress) => {
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
        const uniqueTokens = [...new Set(trades.map(t => t.token_address))];
        await Promise.allSettled(
          uniqueTokens.map(addr => get().getCurrentPrice(addr))
        );
        // Reload trades to recalculate PnL with fresh prices
        await get().loadActiveTrades();
      },
    }),
    {
      name: 'sifter-storage',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({
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
