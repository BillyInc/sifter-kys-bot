import notificationService from './NotificationService';
import DatabaseService from '../database/DatabaseService';

interface Provider {
  name: string;
  ws: WebSocket | null;
  active: boolean;
  url: string | null;
}

class RedundantMonitor {
  private providers: Provider[];
  private currentProvider: number;
  private onMessage: ((data: any) => void) | null;

  constructor() {
    this.providers = [
      { name: 'SolanaTracker', ws: null, active: false, url: 'wss://data.solanatracker.io/ws' },
      { name: 'Helius',        ws: null, active: false, url: null }, // Set from API key
      { name: 'QuickNode',     ws: null, active: false, url: null }  // Set from env
    ];
    this.currentProvider = 0;
    this.onMessage = null;
  }

  async start(onMessage: (data: any) => void): Promise<void> {
    this.onMessage = onMessage;

    const heliusKey = await DatabaseService.getSetting('api_key_helius');
    if (heliusKey) this.providers[1].url = `wss://rpc.helius.xyz/?api-key=${heliusKey}`;

    await this.connectProvider(0);
    setTimeout(() => this.connectProvider(1), 5000);
    setInterval(() => this.checkProviderHealth(), 30000);
  }

  async connectProvider(index: number): Promise<void> {
    const provider = this.providers[index];
    if (!provider.url) return;

    try {
      provider.ws = new WebSocket(provider.url);
      provider.ws.onmessage = (event: any) => {
        if (index === this.currentProvider && this.onMessage) {
          this.onMessage(event.data);
        }
      };
      provider.ws.onerror = () => this.handleProviderFailure(index);
      provider.ws.onclose = () => { provider.active = false; };
      provider.active = true;
      console.log(`✅ Connected to ${provider.name}`);
    } catch {
      provider.active = false;
      console.log(`❌ Failed to connect to ${provider.name}`);
    }
  }

  handleProviderFailure(index: number): void {
    this.providers[index].active = false;
    if (index !== this.currentProvider) return;

    for (let i = 0; i < this.providers.length; i++) {
      if (i !== index && this.providers[i].active) {
        this.switchProvider(i);
        return;
      }
    }
    this.triggerTotalFailure();
  }

  switchProvider(newIndex: number): void {
    this.currentProvider = newIndex;
    notificationService.showSystemNotification('Provider Switched', `Now using ${this.providers[newIndex].name}`);
  }

  triggerTotalFailure(): void {
    notificationService.showSecurityAlert('No data feeds available -- trading paused');
  }

  checkProviderHealth(): void {
    this.providers.forEach((p, i) => {
      if (!p.active && p.url) this.connectProvider(i);
    });
  }
}

export const redundantMonitor = new RedundantMonitor();
export default redundantMonitor;
