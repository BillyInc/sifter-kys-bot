import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

// ── Channel IDs ─────────────────────────────────────────────────────────────
export const CHANNELS = {
  TRADES: 'trades',
  SECURITY: 'security',
  SIGNALS: 'signals',
  WATCHLIST: 'watchlist',
  SYSTEM: 'system',
} as const;

type ChannelId = (typeof CHANNELS)[keyof typeof CHANNELS];

// ── Types ───────────────────────────────────────────────────────────────────
export interface TradeNotificationDetails {
  tokenSymbol?: string;
  tokenAddress?: string;
  amount?: number;
  walletCount?: number;
  txid?: string;
  tpLevel?: number;
  multiplier?: string;
  slippage?: number;
  reason?: string;
  [key: string]: unknown;
}

export type TradeNotificationType =
  | 'buy_executed'
  | 'sell_executed'
  | 'tp_hit'
  | 'trade_failed'
  | 'panic_mode'
  | 'protection_blocked'
  | 'mode_changed'
  | 'queued_executed';

export interface SignalNotificationData {
  token?: string;
  walletCount?: number;
  totalUsd?: number;
  note?: string;
  suggestedAmount?: number;
  signal?: unknown;
  [key: string]: unknown;
}

// ── Notification Service ────────────────────────────────────────────────────
class NotificationService {
  private _initialized = false;

  /**
   * Request permissions, configure handler, and set up Android notification
   * channels. Call once at app startup.
   */
  async initialize(): Promise<void> {
    if (this._initialized) return;

    try {
      // Request permissions (iOS will prompt, Android auto-grants)
      const { status: existing } = await Notifications.getPermissionsAsync();
      let finalStatus = existing;
      if (existing !== 'granted') {
        const { status } = await Notifications.requestPermissionsAsync();
        finalStatus = status;
      }
      if (finalStatus !== 'granted') {
        console.warn('Notification permissions not granted');
      }

      // Configure how notifications appear when the app is in the foreground
      Notifications.setNotificationHandler({
        handleNotification: async () => ({
          shouldShowAlert: true,
          shouldPlaySound: true,
          shouldSetBadge: false,
          shouldShowBanner: true,
          shouldShowList: true,
        }),
      });

      // Android notification channels
      if (Platform.OS === 'android') {
        await this.createAndroidChannels();
      }

      this._initialized = true;
      console.log('Notification service initialized');
    } catch (error) {
      console.error('Notification initialization failed:', error);
    }
  }

  // ── Trade notifications ─────────────────────────────────────────────────
  showTradeNotification(type: TradeNotificationType, details: TradeNotificationDetails = {}): void {
    try {
      const { title, body } = this.buildTradeContent(type, details);
      this.schedule({
        title,
        body,
        channelId: CHANNELS.TRADES,
        data: { type, ...details },
      });
    } catch (_) {
      // fire-and-forget
    }
  }

  // ── Security alerts ─────────────────────────────────────────────────────
  showSecurityAlert(message: string, data: Record<string, unknown> = {}): void {
    try {
      this.schedule({
        title: 'Security Alert',
        body: message,
        channelId: CHANNELS.SECURITY,
        priority: Notifications.AndroidNotificationPriority.MAX,
        data: { type: 'security', ...data },
      });
    } catch (_) {
      // fire-and-forget
    }
  }

  // ── Signal notifications ────────────────────────────────────────────────
  showSignalNotification(signal: SignalNotificationData): void {
    try {
      const walletCount = signal.walletCount ?? 0;
      const title =
        walletCount >= 3
          ? 'MEGA SIGNAL'
          : walletCount === 2
            ? 'DOUBLE SIGNAL'
            : 'SIGNAL';

      const tokenSlice = signal.token?.slice(0, 8) ?? '???';
      const suggested = signal.suggestedAmount != null ? ` | $${signal.suggestedAmount.toFixed(0)} suggested` : '';
      const note = signal.note ? ` -- ${signal.note}` : '';

      this.schedule({
        title,
        body: `${tokenSlice}${suggested}${note}`,
        channelId: CHANNELS.SIGNALS,
        data: { type: 'manual_signal', signal, suggestedAmount: signal.suggestedAmount },
      });
    } catch (_) {
      // fire-and-forget
    }
  }

  // ── Watchlist notifications ─────────────────────────────────────────────
  showWatchlistNotification(title: string, body: string, data: Record<string, unknown> = {}): void {
    try {
      this.schedule({
        title,
        body,
        channelId: CHANNELS.WATCHLIST,
        data: { type: 'watchlist', ...data },
      });
    } catch (_) {
      // fire-and-forget
    }
  }

  // ── System notifications ────────────────────────────────────────────────
  showSystemNotification(title: string, body: string, data: Record<string, unknown> = {}): void {
    try {
      this.schedule({
        title,
        body,
        channelId: CHANNELS.SYSTEM,
        data: { type: 'system', ...data },
      });
    } catch (_) {
      // fire-and-forget
    }
  }

  // ── Notification action listener (e.g. "Buy Again" from duplicate prevention) ──
  addResponseListener(handler: (response: Notifications.NotificationResponse) => void): Notifications.EventSubscription {
    return Notifications.addNotificationResponseReceivedListener(handler);
  }

  // ── Internals ───────────────────────────────────────────────────────────
  private schedule(opts: {
    title: string;
    body: string;
    channelId: ChannelId;
    priority?: Notifications.AndroidNotificationPriority;
    data?: Record<string, unknown>;
  }): void {
    Notifications.scheduleNotificationAsync({
      content: {
        title: opts.title,
        body: opts.body,
        sound: 'default',
        priority: opts.priority ?? Notifications.AndroidNotificationPriority.HIGH,
        data: opts.data ?? {},
        ...(Platform.OS === 'android' ? { channelId: opts.channelId } : {}),
      },
      trigger: null, // immediate
    }).catch((err) => {
      if (__DEV__) console.warn('Failed to schedule notification:', err);
    });
  }

  private async createAndroidChannels(): Promise<void> {
    const channels: Array<{
      id: ChannelId;
      name: string;
      importance: Notifications.AndroidImportance;
    }> = [
      { id: CHANNELS.SIGNALS, name: 'Trading Signals', importance: Notifications.AndroidImportance.HIGH },
      { id: CHANNELS.TRADES, name: 'Trade Executions', importance: Notifications.AndroidImportance.HIGH },
      { id: CHANNELS.WATCHLIST, name: 'Watchlist Updates', importance: Notifications.AndroidImportance.DEFAULT },
      { id: CHANNELS.SECURITY, name: 'Security Alerts', importance: Notifications.AndroidImportance.MAX },
      { id: CHANNELS.SYSTEM, name: 'System Notifications', importance: Notifications.AndroidImportance.DEFAULT },
    ];

    for (const ch of channels) {
      await Notifications.setNotificationChannelAsync(ch.id, {
        name: ch.name,
        importance: ch.importance,
        vibrationPattern: [0, 250, 250, 250],
        sound: 'default',
        enableVibrate: true,
      });
    }
  }

  private buildTradeContent(type: TradeNotificationType, d: TradeNotificationDetails): { title: string; body: string } {
    switch (type) {
      case 'buy_executed':
        return {
          title: 'Trade Executed',
          body: `${d.tokenSymbol ?? '???'}: $${(d.amount ?? 0).toFixed(0)} | ${d.walletCount ?? 0} wallets | Protected`,
        };
      case 'sell_executed':
        return {
          title: 'Sell Executed',
          body: `${d.tokenSymbol ?? d.tokenAddress?.slice(0, 8) ?? '???'} sold`,
        };
      case 'tp_hit':
        return {
          title: `TP${d.tpLevel} Hit!`,
          body: `${d.tokenAddress?.slice(0, 8) ?? '???'}: sold at ${d.multiplier ?? `TP${d.tpLevel}`}`,
        };
      case 'trade_failed':
        return {
          title: 'Trade Failed',
          body: d.reason ?? 'Unknown error',
        };
      case 'panic_mode':
        return {
          title: 'PANIC MODE',
          body: `Executing with ${d.slippage != null ? (d.slippage * 100).toFixed(0) : '?'}% slippage`,
        };
      case 'protection_blocked':
        return {
          title: 'PROTECTION BLOCKED TRADE',
          body: d.reason ?? '',
        };
      case 'mode_changed':
        return {
          title: 'Trading Mode Changed',
          body: d.reason ?? 'Mode updated',
        };
      case 'queued_executed':
        return {
          title: 'Queued Trade Executed',
          body: d.reason ?? 'Offline trade has been submitted',
        };
      default:
        return { title: 'Trade Update', body: 'Check your trades' };
    }
  }
}

const notificationService = new NotificationService();
export default notificationService;

// Backward-compatible export used in App.tsx
export const setupNotifications = () => notificationService.initialize();
