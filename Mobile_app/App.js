import React, { useEffect } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { DatabaseProvider } from './src/database/DatabaseProvider';
import { StoreProvider } from './src/store/StoreProvider';
import AppNavigator from './src/navigation/AppNavigator';
import { initBackgroundServices } from './src/services/BackgroundService';
import { setupNotifications } from './src/services/NotificationService';
import AppLock from './src/components/AppLock';
import { LogBox } from 'react-native';

LogBox.ignoreLogs(['new NativeEventEmitter']);

export default function App() {
  useEffect(() => {
    const initialize = async () => {
      await initBackgroundServices();
      await setupNotifications();
    };
    initialize();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <DatabaseProvider>
          <StoreProvider>
            <AppLock>
              <NavigationContainer>
                <AppNavigator />
              </NavigationContainer>
            </AppLock>
          </StoreProvider>
        </DatabaseProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
