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
import ErrorBoundary from './src/components/ErrorBoundary';
import { LogBox } from 'react-native';

LogBox.ignoreLogs(['new NativeEventEmitter']);

export default function App(): React.JSX.Element {
  useEffect(() => {
    const initialize = async () => {
      try {
        await initBackgroundServices();
        await setupNotifications();
      } catch (error) {
        console.error('App initialization failed:', error);
        // App still renders — services will retry on next background fetch
      }
    };
    initialize();
  }, []);

  return (
    <ErrorBoundary>
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
    </ErrorBoundary>
  );
}
