import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity, Alert, Dimensions } from 'react-native';
import Icon from 'react-native-vector-icons/MaterialIcons';
import { LineChart } from 'react-native-chart-kit';
import useStore from '../store/useStore';
import DatabaseService from '../database/DatabaseService';
import ModeSwitcher from '../components/ModeSwitcher';

const { width } = Dimensions.get('window');

interface DashboardScreenProps {
  navigation: any;
}

const DashboardScreen: React.FC<DashboardScreenProps> = ({ navigation }) => {
  const { portfolioTotal, tradingBalance, activeTrades, notifications, loadActiveTrades, loadNotifications, markNotificationRead } = useStore();
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [signals, setSignals] = useState<any[]>([]);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    await loadActiveTrades();
    await loadNotifications();
    await loadSignals();
  };

  const loadSignals = async () => {
    try {
      const db = await DatabaseService.init();
      const results = await db.executeSql('SELECT * FROM signals_buffer ORDER BY first_seen DESC LIMIT 5');
      const list: any[] = [];
      for (let i = 0; i < results[0].rows.length; i++) {
        const s = results[0].rows.item(i);
        s.wallets = JSON.parse(s.wallets);
        list.push(s);
      }
      setSignals(list);
    } catch {}
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  };

  const totalPnl = activeTrades.reduce((sum: number, t: any) => sum + (t.pnl || 0), 0);
  const pnlPercent = tradingBalance > 0 ? (totalPnl / tradingBalance) * 100 : 0;

  return (
    <ScrollView style={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>

      {/* Portfolio card */}
      <View style={styles.portfolioCard}>
        <Text style={styles.portfolioLabel}>Total Portfolio</Text>
        <Text style={styles.portfolioValue}>${portfolioTotal.toLocaleString()}</Text>
        <View style={styles.row}>
          <View>
            <Text style={styles.subLabel}>Trading (10%)</Text>
            <Text style={styles.subValue}>${tradingBalance.toLocaleString()}</Text>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Text style={styles.subLabel}>Total PnL</Text>
            <Text style={[styles.subValue, totalPnl >= 0 ? styles.pos : styles.neg]}>
              {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)} ({pnlPercent.toFixed(1)}%)
            </Text>
          </View>
        </View>
      </View>

      {/* Mode switcher (premium only) */}
      <ModeSwitcher />

      {/* Chart */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Portfolio Performance</Text>
        <LineChart
          data={{ labels: ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'], datasets: [{ data: [10000,10200,10100,10500,10800,10700,11000] }] }}
          width={width - 40} height={160}
          chartConfig={{ backgroundColor:'#fff', backgroundGradientFrom:'#fff', backgroundGradientTo:'#fff', decimalPlaces:0, color:(o=1)=>`rgba(99,102,241,${o})`, labelColor:(o=1)=>`rgba(0,0,0,${o})` }}
          bezier style={{ borderRadius: 12 }}
        />
      </View>

      {/* Active positions */}
      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Active Positions</Text>
          <TouchableOpacity onPress={() => navigation.navigate('Positions')}><Text style={styles.seeAll}>See All</Text></TouchableOpacity>
        </View>
        {activeTrades.slice(0, 3).map((trade: any) => (
          <TouchableOpacity key={trade.id} style={styles.tradeCard} onPress={() => navigation.navigate('TradeDetail', { tradeId: trade.id })}>
            <View style={styles.row}>
              <Text style={styles.tradeSymbol}>{trade.token_symbol}</Text>
              <Text style={[styles.tradePnl, (trade.pnl || 0) >= 0 ? styles.pos : styles.neg]}>
                {(trade.pnl || 0) >= 0 ? '+' : ''}{(trade.pnl || 0).toFixed(2)}
              </Text>
            </View>
            <View style={styles.row}>
              <Text style={styles.detail}>Entry: ${trade.entry_price.toFixed(8)}</Text>
              <Text style={styles.detail}>Size: ${trade.remaining_size.toFixed(2)}</Text>
            </View>
          </TouchableOpacity>
        ))}
        {activeTrades.length === 0 && <Text style={styles.empty}>No active positions</Text>}
      </View>

      {/* Live signals */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Live Signals</Text>
        {signals.map((s: any) => (
          <View key={s.token_address} style={styles.signalCard}>
            <View style={styles.row}>
              <Text style={styles.signalToken}>{s.token_address.slice(0, 10)}…</Text>
              <View style={[styles.badge, s.wallet_count >= 3 ? styles.megaBadge : s.wallet_count === 2 ? styles.dblBadge : styles.sglBadge]}>
                <Text style={styles.badgeText}>{s.wallet_count} wallet{s.wallet_count > 1 ? 's' : ''}</Text>
              </View>
            </View>
            <Text style={styles.signalAmount}>${s.total_usd.toFixed(0)} total</Text>
          </View>
        ))}
        {signals.length === 0 && <Text style={styles.empty}>Monitoring wallets…</Text>}
      </View>

      {/* Notifications */}
      {notifications.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Notifications</Text>
          {notifications.slice(0, 3).map((n: any) => (
            <TouchableOpacity key={n.id} style={styles.notifCard} onPress={() => markNotificationRead(n.id)}>
              <Text style={styles.notifTitle}>{n.title}</Text>
              <Text style={styles.notifBody}>{n.body}</Text>
            </TouchableOpacity>
          ))}
        </View>
      )}

      <View style={{ height: 20 }} />
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f5f5f5' },
  portfolioCard: { backgroundColor: '#6366f1', padding: 20, margin: 15, borderRadius: 16 },
  portfolioLabel: { color: 'rgba(255,255,255,0.8)', fontSize: 13 },
  portfolioValue: { color: 'white', fontSize: 32, fontWeight: 'bold', marginVertical: 4 },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  subLabel: { color: 'rgba(255,255,255,0.7)', fontSize: 12 },
  subValue: { color: 'white', fontSize: 17, fontWeight: '600' },
  pos: { color: '#4ade80' },
  neg: { color: '#f87171' },
  card: { backgroundColor: 'white', marginHorizontal: 15, marginBottom: 15, padding: 15, borderRadius: 12 },
  cardTitle: { fontSize: 15, fontWeight: '600', marginBottom: 10 },
  section: { marginHorizontal: 15, marginBottom: 20 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 },
  sectionTitle: { fontSize: 17, fontWeight: '600', marginBottom: 10 },
  seeAll: { color: '#6366f1', fontSize: 14 },
  tradeCard: { backgroundColor: 'white', padding: 14, borderRadius: 10, marginBottom: 8 },
  tradeSymbol: { fontSize: 16, fontWeight: '600' },
  tradePnl: { fontSize: 16, fontWeight: '600' },
  detail: { color: '#666', fontSize: 12, marginTop: 4 },
  signalCard: { backgroundColor: 'white', padding: 14, borderRadius: 10, marginBottom: 8 },
  signalToken: { fontSize: 15, fontWeight: '600' },
  signalAmount: { fontSize: 18, fontWeight: 'bold', marginTop: 4 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  megaBadge: { backgroundColor: '#fee2e2' },
  dblBadge: { backgroundColor: '#cffafe' },
  sglBadge: { backgroundColor: '#e0f2fe' },
  badgeText: { fontSize: 11, fontWeight: '600' },
  notifCard: { backgroundColor: 'white', padding: 12, borderRadius: 8, marginBottom: 6 },
  notifTitle: { fontSize: 13, fontWeight: '600' },
  notifBody: { color: '#666', fontSize: 12, marginTop: 2 },
  empty: { color: '#999', textAlign: 'center', padding: 20 },
});

export default DashboardScreen;
