import BackgroundFetch from 'react-native-background-fetch';
import DatabaseService from '../database/DatabaseService';
import RealTimeMonitor from './RealTimeMonitor';
import fortifiedAutoTrader from './FortifiedAutoTrader';
import watchlistManager from './WatchlistManager';

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
    const supabaseUrl = process.env.SUPABASE_URL;
    const supabaseKey = process.env.SUPABASE_ANON_KEY;

    if (!supabaseUrl || !supabaseKey) {
      console.log('⚠️ Supabase credentials not configured');
      return;
    }

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
      const data = await response.json();
      await DatabaseService.syncElite15(data);
      console.log(`✅ Synced Elite 15 (${data.length} wallets)`);
    }
  } catch (e) {
    console.error('Elite 15 sync failed:', e);
  }
};
