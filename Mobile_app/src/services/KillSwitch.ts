import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import PushNotification from 'react-native-push-notification';
import DatabaseService from '../database/DatabaseService';

class KillSwitch {
  private checkInterval: ReturnType<typeof setInterval> | null;

  constructor() {
    this.checkInterval = null;
  }

  async start(): Promise<void> {
    this.checkInterval = setInterval(() => this.checkStatus(), 60000);
  }

  stop(): void {
    if (this.checkInterval) clearInterval(this.checkInterval);
  }

  async checkStatus(): Promise<void> {
    try {
      const userId = await AsyncStorage.getItem('user_id');
      const deviceId = await this.getDeviceId();
      const baseUrl = process.env.API_BASE_URL || 'https://sifter-kys.duckdns.org';
      const response = await fetch(`${baseUrl}/kill-switch/status`, {
        headers: { 'device-id': deviceId, 'user-id': userId || '' }
      });
      const { killEnabled, reason } = await response.json();
      if (killEnabled) await this.activateKillSwitch(reason);
    } catch {
      // Server unreachable — don't stop trading on network errors
    }
  }

  async isEnabled(): Promise<boolean> {
    const paused = await AsyncStorage.getItem('trading_paused');
    return paused === 'true';
  }

  async activateKillSwitch(reason?: string): Promise<void> {
    await AsyncStorage.setItem('trading_paused', 'true');
    PushNotification.localNotification({
      channelId: 'security',
      title: '🚨 EMERGENCY KILL SWITCH ACTIVATED',
      message: reason || 'Trading paused for security',
      importance: 'high', priority: 'high'
    } as any);
    await AsyncStorage.multiRemove(['user_token', 'session_id']);
    console.log(`🚨 Kill switch activated: ${reason}`);
  }

  async deactivate(): Promise<void> {
    await AsyncStorage.setItem('trading_paused', 'false');
    console.log('✅ Kill switch deactivated');
  }

  async emergencySelfDestruct(): Promise<void> {
    await AsyncStorage.clear();
    try {
      await SecureStore.deleteItemAsync('wallet_key_part1');
      await SecureStore.deleteItemAsync('wallet_key_part2');
      await SecureStore.deleteItemAsync('wallet_address');
    } catch {}
    console.log('💥 Self-destruct complete');
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

export const killSwitch = new KillSwitch();
export default killSwitch;
