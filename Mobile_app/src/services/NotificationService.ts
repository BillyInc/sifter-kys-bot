import PushNotification from 'react-native-push-notification';
import { Platform } from 'react-native';

export const setupNotifications = async (): Promise<void> => {
  if (Platform.OS === 'android') {
    const channels = [
      { channelId: 'signals',   channelName: 'Trading Signals',    importance: 4 },
      { channelId: 'trades',    channelName: 'Trade Executions',    importance: 4 },
      { channelId: 'watchlist', channelName: 'Watchlist Updates',   importance: 3 },
      { channelId: 'security',  channelName: 'Security Alerts',     importance: 5 },
      { channelId: 'system',    channelName: 'System Notifications', importance: 3 },
    ];
    channels.forEach(({ channelId, channelName, importance }) => {
      PushNotification.createChannel(
        { channelId, channelName, playSound: true, soundName: 'default', importance, vibrate: true } as any,
        () => {}
      );
    });
  }

  PushNotification.configure({
    onRegister: (token: any) => console.log('Push token:', token),

    onNotification: (notification: any) => {
      console.log('Notification received:', notification);
      notification.finish();
    },

    onAction: (notification: any) => {
      if (notification.action === 'Buy Again') {
        // Handle manual rebuy action from notification
        const { token } = notification.data || {};
        if (token) {
          import('./DuplicatePrevention').then(({ default: dp }) => dp.approveRebuy(token));
        }
      }
    },

    onRegistrationError: (err: any) => console.error(err.message),

    permissions: { alert: true, badge: true, sound: true },
    popInitialNotification: true,
    requestPermissions: true,
  });
};
