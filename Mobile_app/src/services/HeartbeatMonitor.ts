import BackgroundFetch from 'react-native-background-fetch';
import NetInfo from '@react-native-community/netinfo';
import AsyncStorage from '@react-native-async-storage/async-storage';
import PushNotification from 'react-native-push-notification';

class HeartbeatMonitor {
  private lastHeartbeat: number;
  private heartbeatInterval: number;
  private missedBeats: number;
  private healthCheckUrl: string;
  private intervalId: ReturnType<typeof setInterval> | null;
  private connectivityCheckId: ReturnType<typeof setInterval> | null;

  constructor() {
    this.lastHeartbeat = Date.now();
    this.heartbeatInterval = 300000; // 5 min
    this.missedBeats = 0;
    this.healthCheckUrl = `${process.env.API_BASE_URL || 'https://sifter-kys.duckdns.org'}/health`;
    this.intervalId = null;
    this.connectivityCheckId = null;
  }

  async start(): Promise<void> {
    this.intervalId = setInterval(() => this.sendHeartbeat(), this.heartbeatInterval);
    this.connectivityCheckId = setInterval(() => this.checkConnectivity(), 60000);

    BackgroundFetch.configure(
      { minimumFetchInterval: 15, stopOnTerminate: false, startOnBoot: true },
      async (taskId: string) => {
        await this.sendHeartbeat();
        BackgroundFetch.finish(taskId);
      }
    );
  }

  stop(): void {
    if (this.intervalId) clearInterval(this.intervalId);
    if (this.connectivityCheckId) clearInterval(this.connectivityCheckId);
  }

  async sendHeartbeat(): Promise<void> {
    try {
      const network = await NetInfo.fetch();
      if (!network.isConnected) { this.handleOffline(); return; }

      const response = await fetch(this.healthCheckUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deviceId: await this.getDeviceId(), timestamp: Date.now() })
      });

      if (response.ok) {
        this.lastHeartbeat = Date.now();
        this.missedBeats = 0;
      } else {
        this.handleMissedBeat('Server error');
      }
    } catch (e: any) {
      this.handleMissedBeat(e.message);
    }
  }

  handleMissedBeat(reason: string): void {
    this.missedBeats++;
    if (this.missedBeats >= 3) this.triggerDowntimeAlert(reason);
  }

  handleOffline(): void {
    PushNotification.localNotification({
      channelId: 'system', title: '📡 Offline Mode',
      message: 'No internet. Trades will queue locally.', importance: 'low'
    } as any);
  }

  async triggerDowntimeAlert(reason: string): Promise<void> {
    PushNotification.localNotification({
      channelId: 'system', title: '⚠️ SYSTEM ALERT',
      message: `Monitor may be down: ${reason}`, importance: 'high', ongoing: true
    } as any);
    await this.restartServices();
  }

  async restartServices(): Promise<void> {
    try {
      const RealTimeMonitor = (await import('./RealTimeMonitor')).default;
      await RealTimeMonitor.restart();
      console.log('✅ Services restarted');
    } catch (e) {
      console.log('❌ Restart failed:', e);
    }
  }

  async checkConnectivity(): Promise<void> {
    const network = await NetInfo.fetch();
    if (!network.isConnected) this.handleOffline();
  }

  async getDeviceId(): Promise<string> {
    let id = await AsyncStorage.getItem('device_id');
    if (!id) {
      id = Math.random().toString(36).slice(2) + Date.now().toString(36);
      await AsyncStorage.setItem('device_id', id);
    }
    return id;
  }
}

export const heartbeatMonitor = new HeartbeatMonitor();
export default heartbeatMonitor;
