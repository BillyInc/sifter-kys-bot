import WebSocket from 'react-native-websocket';
import BackgroundTimer from 'react-native-background-timer';
import DatabaseService from '../database/DatabaseService';
import notificationService from './NotificationService';

interface Trade {
  wallet: string;
  token: string;
  tokenSymbol: string;
  amount: number;
  usdValue: number;
  timestamp: any;
  txHash: string;
  source: string;
  side?: string;
  [key: string]: any;
}

interface SignalBuffer {
  wallets: Set<string>;
  totalUsd: number;
  firstSeen: number;
  lastSeen: number;
  walletCount: number;
  timer: ReturnType<typeof setTimeout> | null;
  executed: boolean;
  trades: Trade[];
}

interface SignalData {
  walletCount: number;
  totalUsd: number;
  wallets: string[];
  type: string;
  trades: Trade[];
  source?: string;
  receivedAt?: number;
  token?: string;
}

type OnSignalCallback = (signal: SignalData) => void;

class RealTimeMonitor {
  private ws: any;
  private pollingInterval: any;
  private top15Wallets: any[];
  private elite15Addresses: Set<string>;
  private signalBuffer: Map<string, SignalBuffer>;
  private BUFFER_WINDOW: number;
  private MIN_BUY_USD: number;
  private onSignalCallback: OnSignalCallback | null;
  private isRunning: boolean;
  private reconnectAttempts: number;
  private maxReconnectAttempts: number;

  constructor() {
    this.ws = null;
    this.pollingInterval = null;
    this.top15Wallets = [];
    this.elite15Addresses = new Set(); // Fast O(1) lookup for source detection
    this.signalBuffer = new Map();
    this.BUFFER_WINDOW = 15000;
    this.MIN_BUY_USD = 100;
    this.onSignalCallback = null;
    this.isRunning = false;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 20;
  }

  async start(wallets: any[], onSignal: OnSignalCallback): Promise<void> {
    this.top15Wallets = wallets;
    this.elite15Addresses = new Set(wallets.map((w: any) => w.wallet_address));
    this.onSignalCallback = onSignal;
    this.isRunning = true;

    this.MIN_BUY_USD = parseFloat(await DatabaseService.getSetting('min_buy_usd') || '100') || 100;
    this.BUFFER_WINDOW = parseInt(await DatabaseService.getSetting('signal_window_seconds') || '15') * 1000 || 15000;

    this.connectWebSocket();
    this.startPolling();
  }

  stop(): void {
    this.isRunning = false;
    if (this.ws) this.ws.close();
    if (this.pollingInterval) BackgroundTimer.clearInterval(this.pollingInterval);
  }

  async restart(): Promise<void> {
    this.stop();
    const elite15 = await DatabaseService.getElite15();
    if (this.onSignalCallback) {
      await this.start(elite15, this.onSignalCallback);
    }
  }

  connectWebSocket(): void {
    try {
      this.ws = new WebSocket('wss://data.solanatracker.io/ws');

      this.ws.onopen = () => {
        console.log('🔌 WebSocket connected');
        this.reconnectAttempts = 0;
        this.top15Wallets.forEach((wallet: any) => {
          if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
              type: 'subscribe',
              channel: 'wallet-trades',
              wallet: wallet.wallet_address
            }));
          }
        });
      };

      this.ws.onmessage = (event: any) => {
        if (!this.isRunning) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'trade' && data.side === 'buy') {
            this.handleNewTrade({
              wallet: data.wallet,
              token: data.tokenAddress,
              tokenSymbol: data.tokenSymbol,
              amount: data.amount,
              usdValue: data.usdValue,
              timestamp: data.timestamp,
              txHash: data.signature,
              source: 'websocket'
            });
          }
        } catch (e) {
          console.error('WebSocket message error:', e);
        }
      };

      this.ws.onerror = () => console.log('WebSocket error');
      this.ws.onclose = () => {
        if (this.isRunning && this.reconnectAttempts < this.maxReconnectAttempts) {
          const delay = Math.min(5000 * Math.pow(1.5, this.reconnectAttempts), 60000);
          this.reconnectAttempts++;
          setTimeout(() => this.connectWebSocket(), delay);
        }
      };
    } catch (e) {
      console.log('WebSocket failed, polling only:', e);
    }
  }

  startPolling(): void {
    this.pollingInterval = BackgroundTimer.setInterval(async () => {
      if (!this.isRunning) return;
      for (const wallet of this.top15Wallets) {
        try {
          const trades = await this.fetchRecentTrades(wallet.wallet_address, 60);
          for (const trade of trades) {
            if (trade.side === 'buy' && trade.usdValue >= this.MIN_BUY_USD) {
              this.handleNewTrade({
                wallet: wallet.wallet_address,
                token: trade.tokenAddress,
                tokenSymbol: trade.tokenSymbol,
                amount: trade.amount,
                usdValue: trade.usdValue,
                timestamp: trade.timestamp,
                txHash: trade.signature,
                source: 'polling'
              });
            }
          }
        } catch (e) {
          console.error(`Polling failed for ${wallet.wallet_address}:`, e);
        }
      }
    }, 5000);
  }

  async fetchRecentTrades(wallet: string, secondsBack: number): Promise<any[]> {
    try {
      const apiKey = await DatabaseService.getSetting('api_key_solanatracker');
      if (!apiKey) return [];
      const response = await fetch(
        `https://data.solanatracker.io/trades/${wallet}?from=${Date.now() - secondsBack * 1000}`,
        { headers: { 'x-api-key': apiKey } }
      );
      const data = await response.json();
      return data.trades || [];
    } catch {
      return [];
    }
  }

  handleNewTrade(trade: Trade): void {
    const { token, wallet, usdValue } = trade;
    if (__DEV__) console.log(`💰 Buy: ${wallet.slice(0, 8)} bought $${usdValue} of ${token.slice(0, 8)}`);

    let buffer = this.signalBuffer.get(token);

    if (!buffer) {
      buffer = {
        wallets: new Set([wallet]),
        totalUsd: usdValue,
        firstSeen: Date.now(),
        lastSeen: Date.now(),
        walletCount: 1,
        timer: null,
        executed: false,
        trades: [trade]
      };
      this.signalBuffer.set(token, buffer);

      DatabaseService.saveSignalBuffer(token, {
        wallets: [wallet], total_usd: usdValue,
        first_seen: new Date(), last_seen: new Date(),
        wallet_count: 1, expires_at: new Date(Date.now() + this.BUFFER_WINDOW)
      });

      buffer.timer = setTimeout(() => {
        if (this.signalBuffer.has(token) && !this.signalBuffer.get(token)!.executed) {
          const signal = this.signalBuffer.get(token)!;
          if (signal.walletCount === 1) {
            this.emitSignal(token, {
              walletCount: 1, totalUsd: signal.totalUsd,
              wallets: Array.from(signal.wallets), type: 'single', trades: signal.trades
            });
            this.signalBuffer.delete(token);
            DatabaseService.deleteSignalBuffer(token);
          }
        }
      }, this.BUFFER_WINDOW);

    } else {
      if (!buffer.wallets.has(wallet)) {
        buffer.wallets.add(wallet);
        buffer.totalUsd += usdValue;
        buffer.walletCount = buffer.wallets.size;
        buffer.lastSeen = Date.now();
        buffer.trades.push(trade);

        DatabaseService.saveSignalBuffer(token, {
          wallets: Array.from(buffer.wallets), total_usd: buffer.totalUsd,
          first_seen: new Date(buffer.firstSeen), last_seen: new Date(),
          wallet_count: buffer.walletCount, expires_at: new Date(Date.now() + this.BUFFER_WINDOW)
        });

        // 3+ wallets → execute immediately
        if (buffer.walletCount >= 3 && !buffer.executed) {
          if (buffer.timer) clearTimeout(buffer.timer);
          buffer.executed = true;
          this.emitSignal(token, {
            walletCount: buffer.walletCount, totalUsd: buffer.totalUsd,
            wallets: Array.from(buffer.wallets), type: 'multi', trades: buffer.trades
          });
          this.signalBuffer.delete(token);
          DatabaseService.deleteSignalBuffer(token);

        } else if (buffer.walletCount === 2 && !buffer.executed) {
          const timeSinceFirst = Date.now() - buffer.firstSeen;
          if (buffer.timer) clearTimeout(buffer.timer);
          buffer.timer = setTimeout(() => {
            if (this.signalBuffer.has(token) && !this.signalBuffer.get(token)!.executed) {
              const s = this.signalBuffer.get(token)!;
              this.emitSignal(token, {
                walletCount: 2, totalUsd: s.totalUsd,
                wallets: Array.from(s.wallets), type: 'double', trades: s.trades
              });
              this.signalBuffer.delete(token);
              DatabaseService.deleteSignalBuffer(token);
            }
          }, Math.max(0, this.BUFFER_WINDOW - timeSinceFirst));
        }
      }
    }
  }

  // Determine if a wallet is in the Elite 15
  isElite15Wallet(walletAddress: string): boolean {
    return this.elite15Addresses.has(walletAddress);
  }

  emitSignal(token: string, signalData: SignalData): void {
    if (!this.onSignalCallback) return;

    // Tag the signal source so FortifiedAutoTrader can route correctly
    const source = this.isElite15Wallet(signalData.wallets[0])
      ? 'elite15'
      : 'watchlist';

    this.onSignalCallback({
      token,
      ...signalData,
      source,       // ← 'elite15' triggers auto-trade; 'watchlist' → notification only
      receivedAt: Date.now()
    });

    this.sendPushNotification(signalData);
  }

  sendPushNotification(signal: SignalData): void {
    let title: string, body: string;
    if (signal.walletCount >= 3) {
      title = '🔥🔥🔥 MEGA SIGNAL';
      body = `${signal.walletCount} wallets bought $${signal.totalUsd.toFixed(0)} - 40% position!`;
    } else if (signal.walletCount === 2) {
      title = '🚀 DOUBLE WALLET SIGNAL';
      body = `2 wallets bought $${signal.totalUsd.toFixed(0)} - 10% position`;
    } else {
      title = '🔔 SINGLE WALLET SIGNAL';
      body = `1 wallet bought $${signal.totalUsd.toFixed(0)} - 30% initial`;
    }

    notificationService.showSignalNotification({
      token: signal.token,
      walletCount: signal.walletCount,
      totalUsd: signal.totalUsd,
      signal,
    });

    DatabaseService.addNotification({ type: 'signal', title, body: body, data: signal });
  }
}

export default new RealTimeMonitor();
