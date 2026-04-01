import BackgroundFetch from 'react-native-background-fetch';
import DatabaseService from '../database/DatabaseService';
import RealTimeMonitor from './RealTimeMonitor';
import fortifiedAutoTrader from './FortifiedAutoTrader';
import watchlistManager from './WatchlistManager';
import apiClient from './ApiClient';

export const initBackgroundServices = async () => {
  BackgroundFetch.configure(
    {
      minimumFetchInterval: 15,
      stopOnTerminate: false,
      startOnBoot: true,
      enableHeadless: true,
      requiredNetworkType: BackgroundFetch.NETWORK_TYPE_ANY,
    },
    async (taskId) => {
      console.log('[BackgroundFetch] task:', taskId);
      await syncElite15();
      await watchlistManager.checkAllWallets();
      BackgroundFetch.finish(taskId);
    },
    (error) => console.log('[BackgroundFetch] error:', error)
  );

  // Initialize auto-trader with current user
  const userId = await DatabaseService.getSetting('user_id') || 'local';
  await fortifiedAutoTrader.initialize(userId);

  // Start real-time wallet monitor → feeds signals into auto-trader
  const elite15 = await DatabaseService.getElite15();
  await RealTimeMonitor.start(elite15, (signal) => {
    fortifiedAutoTrader.processSignal(signal);
  });

  // Start watchlist degradation checks
  await watchlistManager.start();

  console.log('✅ Background services initialized');
};

export const syncElite15 = async () => {
  try {
    const data = await apiClient.getElite100();

    // The backend returns enriched data; extract the wallets array
    const wallets = data.wallets || data.elite_100 || data;
    if (Array.isArray(wallets) && wallets.length > 0) {
      await DatabaseService.syncElite15(wallets);
      console.log(`✅ Synced Elite 15 via API (${wallets.length} wallets)`);
    } else {
      console.log('⚠️ Elite 100 API returned no wallets');
    }
  } catch (e) {
    console.error('Elite 15 sync failed:', e.message);

    // Fallback to direct Supabase if API is unreachable
    try {
      const supabaseUrl = process.env.SUPABASE_URL;
      const supabaseKey = process.env.SUPABASE_ANON_KEY;

      if (!supabaseUrl || !supabaseKey) return;

      const response = await fetch(
        `${supabaseUrl}/rest/v1/elite_15?select=*&order=rank.asc`,
        {
          headers: {
            apikey: supabaseKey,
            Authorization: `Bearer ${supabaseKey}`,
            'Content-Type': 'application/json'
          }
        }
      );

      if (response.ok) {
        const fallbackData = await response.json();
        await DatabaseService.syncElite15(fallbackData);
        console.log(`✅ Synced Elite 15 via Supabase fallback (${fallbackData.length} wallets)`);
      }
    } catch (fallbackErr) {
      console.error('Elite 15 fallback sync also failed:', fallbackErr);
    }
  }
};
