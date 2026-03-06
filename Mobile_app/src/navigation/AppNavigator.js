import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createStackNavigator } from '@react-navigation/stack';
import Icon from 'react-native-vector-icons/MaterialIcons';

import DashboardScreen from '../screens/DashboardScreen';
import PositionsScreen from '../screens/PositionsScreen';
import Elite15Screen from '../screens/Elite15Screen';
import SettingsScreen from '../screens/SettingsScreen';
import WalletDetailScreen from '../screens/WalletDetailScreen';
import TradeDetailScreen from '../screens/TradeDetailScreen';
import ConnectWalletScreen from '../screens/ConnectWalletScreen';

const Tab = createBottomTabNavigator();
const Stack = createStackNavigator();

const DashboardStack = () => (
  <Stack.Navigator>
    <Stack.Screen name="DashboardMain" component={DashboardScreen} options={{ title: 'Dashboard' }} />
    <Stack.Screen name="TradeDetail" component={TradeDetailScreen} options={{ title: 'Trade Details' }} />
  </Stack.Navigator>
);

const PositionsStack = () => (
  <Stack.Navigator>
    <Stack.Screen name="PositionsMain" component={PositionsScreen} options={{ title: 'Active Trades' }} />
    <Stack.Screen name="TradeDetail" component={TradeDetailScreen} options={{ title: 'Trade Details' }} />
  </Stack.Navigator>
);

const EliteStack = () => (
  <Stack.Navigator>
    <Stack.Screen name="EliteMain" component={Elite15Screen} options={{ title: 'Elite 15' }} />
    <Stack.Screen name="WalletDetail" component={WalletDetailScreen} options={{ title: 'Wallet Details' }} />
  </Stack.Navigator>
);

const SettingsStack = () => (
  <Stack.Navigator>
    <Stack.Screen name="SettingsMain" component={SettingsScreen} options={{ title: 'Settings' }} />
    <Stack.Screen name="ConnectWallet" component={ConnectWalletScreen} options={{ title: 'Connect Wallet' }} />
  </Stack.Navigator>
);

const AppNavigator = () => (
  <Tab.Navigator
    screenOptions={({ route }) => ({
      tabBarIcon: ({ color, size }) => {
        const icons = { Dashboard: 'dashboard', Positions: 'trending-up', Elite: 'star', Settings: 'settings' };
        return <Icon name={icons[route.name]} size={size} color={color} />;
      },
      tabBarActiveTintColor: '#6366f1',
      tabBarInactiveTintColor: 'gray',
    })}
  >
    <Tab.Screen name="Dashboard" component={DashboardStack} options={{ headerShown: false }} />
    <Tab.Screen name="Positions" component={PositionsStack} options={{ headerShown: false }} />
    <Tab.Screen name="Elite" component={EliteStack} options={{ headerShown: false }} />
    <Tab.Screen name="Settings" component={SettingsStack} options={{ headerShown: false }} />
  </Tab.Navigator>
);

export default AppNavigator;
