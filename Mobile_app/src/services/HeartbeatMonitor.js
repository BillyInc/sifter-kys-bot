import BackgroundFetch from 'react-native-background-fetch';
import NetInfo from '@react-native-community/netinfo';
import AsyncStorage from '@react-native-async-storage/async-storage';
import PushNotification from 'react-native-push-notification';

class HeartbeatMonitor {
  constructor() {
    this.lastHeartbeat = Date.now();
    this.heartbeatInterval = 300000; // 5 min
    this.missedBeats = 0;
    this.healthCheckUrl = 'https://your-api.com/health';
    this.intervalId = null;
  }

  async start() {
    this.intervalId = setInterval(() => this.sendHeartbeat(), this.heartbeatInterval);
    setInterval(() => this.checkConnectivity(), 60000);

    BackgroundFetch.configure(
      { minimumFetchInterval: 15, stopOnTerminate: false, startOnBoot: true },
      async (taskId) => {
        await this.sendHeartbeat();
        BackgroundFetch.finish(taskId);
      }
    );
  }

  stop() {
    if (this.intervalId) clearInterval(this.intervalId);
  }

  async sendHeartbeat() {
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
    } catch (e) {
      this.handleMissedBeat(e.message);
    }
  }

  handleMissedBeat(reason) {
    this.missedBeats++;
    if (this.missedBeats >= 3) this.triggerDowntimeAlert(reason);
  }

  handleOffline() {
    PushNotification.localNotification({
      channelId: 'system', title: '📡 Offline Mode',
      message: 'No internet. Trades will queue locally.', importance: 'low'
    });
  }

  async triggerDowntimeAlert(reason) {
    PushNotification.localNotification({
      channelId: 'system', title: '⚠️ SYSTEM ALERT',
      message: `Monitor may be down: ${reason}`, importance: 'high', ongoing: true
    });
    await this.restartServices();
  }

  async restartServices() {
    try {
      const RealTimeMonitor = (await import('./RealTimeMonitor')).default;
      await RealTimeMonitor.restart();
      console.log('✅ Services restarted');
    } catch (e) {
      console.log('❌ Restart failed:', e);
    }
  }

  async checkConnectivity() {
    const network = await NetInfo.fetch();
    if (!network.isConnected) this.handleOffline();
  }

  async getDeviceId() {
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
