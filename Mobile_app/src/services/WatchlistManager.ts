import DatabaseService from '../database/DatabaseService';
import PushNotification from 'react-native-push-notification';

interface DegradationRules {
  days: number;
  minROI: number;
  minRunners: number;
}

interface DegradationAlert {
  severity: string;
  message: string;
}

class WatchlistManager {
  private checkInterval: ReturnType<typeof setInterval> | null;
  private degradationRules: DegradationRules;

  constructor() {
    this.checkInterval = null;
    this.degradationRules = { days: 7, minROI: 5, minRunners: 3 };
  }

  async start(): Promise<void> {
    this.degradationRules.days = parseInt(await DatabaseService.getSetting('degradation_days') || '7') || 7;
    this.degradationRules.minROI = parseFloat(await DatabaseService.getSetting('degradation_min_roi') || '5') || 5;
    this.checkInterval = setInterval(() => this.checkAllWallets(), 6 * 60 * 60 * 1000);
    this.checkAllWallets();
  }

  stop(): void {
    if (this.checkInterval) clearInterval(this.checkInterval);
  }

  async checkAllWallets(): Promise<void> {
    console.log('🔍 Checking watchlist for degradation...');
    const watchlist = await DatabaseService.getWatchlist();
    const autoReplace = await DatabaseService.getSetting('auto_replace_wallets') === 'true';
    for (const wallet of watchlist) {
      await this.checkWallet(wallet, autoReplace);
    }
  }

  async checkWallet(wallet: any, autoReplace: boolean): Promise<void> {
    const alerts: DegradationAlert[] = [];
    let status = 'healthy';

    if (wallet.last_trade_time) {
      const daysSince = (Date.now() - new Date(wallet.last_trade_time).getTime()) / 86400000;
      if (daysSince > this.degradationRules.days) {
        alerts.push({ severity: 'yellow', message: `No activity for ${Math.round(daysSince)} days` });
        status = 'warning';
      }
    } else {
      alerts.push({ severity: 'orange', message: 'No trading history' });
      status = 'warning';
    }

    if (wallet.roi_30d < this.degradationRules.minROI) {
      alerts.push({ severity: 'red', message: `30d ROI ${wallet.roi_30d.toFixed(1)}x below floor` });
      status = 'critical';
    }

    if (wallet.runners_30d < this.degradationRules.minRunners) {
      alerts.push({ severity: 'orange', message: `Only ${wallet.runners_30d} runners in 30d` });
      if (status !== 'critical') status = 'warning';
    }

    await DatabaseService.updateWatchlistStatus(wallet.wallet_address, status, alerts);

    if (status === 'critical') {
      autoReplace
        ? await this.autoReplaceWallet(wallet)
        : await this.suggestReplacement(wallet);
    }
  }

  async autoReplaceWallet(degradedWallet: any): Promise<void> {
    const elite15 = await DatabaseService.getElite15();
    const watchlist = await DatabaseService.getWatchlist();
    const watchlistAddresses = new Set(watchlist.map((w: any) => w.wallet_address));

    const candidates = elite15
      .filter((w: any) => !watchlistAddresses.has(w.wallet_address) && w.tier === degradedWallet.tier && w.professional_score > degradedWallet.professional_score)
      .sort((a: any, b: any) => b.professional_score - a.professional_score);

    if (candidates.length > 0) {
      const replacement = candidates[0];
      await DatabaseService.removeFromWatchlist(degradedWallet.wallet_address);
      await DatabaseService.addToWatchlist(replacement.wallet_address, true);

      PushNotification.localNotification({
        channelId: 'watchlist',
        title: '🔄 Wallet Auto-Replaced',
        message: `${degradedWallet.wallet_address.slice(0, 8)} → ${replacement.wallet_address.slice(0, 8)}`,
        data: { type: 'replacement', degraded: degradedWallet.wallet_address, replacement: replacement.wallet_address }
      } as any);

      DatabaseService.addNotification({
        type: 'replacement',
        title: 'Wallet Auto-Replaced',
        body: `${degradedWallet.wallet_address.slice(0, 8)} replaced with ${replacement.wallet_address.slice(0, 8)}`,
        data: { degraded: degradedWallet.wallet_address, replacement: replacement.wallet_address }
      });
    }
  }

  async suggestReplacement(degradedWallet: any): Promise<void> {
    const elite15 = await DatabaseService.getElite15();
    const watchlist = await DatabaseService.getWatchlist();
    const watchlistAddresses = new Set(watchlist.map((w: any) => w.wallet_address));

    const candidates = elite15
      .filter((w: any) => !watchlistAddresses.has(w.wallet_address) && w.tier === degradedWallet.tier)
      .slice(0, 3);

    if (candidates.length > 0) {
      PushNotification.localNotification({
        channelId: 'watchlist',
        title: '⚠️ Wallet Degraded',
        message: `${degradedWallet.wallet_address.slice(0, 8)} needs replacement`,
        data: { type: 'replacement_suggestion', degraded: degradedWallet.wallet_address, candidates: candidates.map((c: any) => c.wallet_address) }
      } as any);
    }
  }
}

export const watchlistManager = new WatchlistManager();
export default watchlistManager;
