import React, { useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, Alert } from 'react-native';
import Icon from 'react-native-vector-icons/MaterialIcons';
import useStore from '../store/useStore';
import fortifiedAutoTrader from '../services/FortifiedAutoTrader';
import duplicatePrevention from '../services/DuplicatePrevention';

interface PositionsScreenProps {
  navigation: any;
}

const PositionsScreen: React.FC<PositionsScreenProps> = ({ navigation }) => {
  const { activeTrades, loadActiveTrades } = useStore();
  const [refreshing, setRefreshing] = React.useState<boolean>(false);

  useEffect(() => { loadActiveTrades(); }, []);

  const onRefresh = async () => { setRefreshing(true); await loadActiveTrades(); setRefreshing(false); };

  const getTPProgress = (trade: any): number =>
    [trade.tp1_executed, trade.tp2_executed, trade.tp3_executed, trade.tp4_executed].filter(Boolean).length;

  const handleRebuy = (trade: any) => {
    Alert.alert(
      '🔄 Buy Again?',
      `You already have a position in ${trade.token_symbol}. Are you sure you want to buy again?\n\nThis overrides the automatic duplicate protection.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Yes, Buy Again',
          style: 'destructive',
          onPress: async () => {
            await duplicatePrevention.approveRebuy(trade.token_address);
            Alert.alert('Override set', 'Next signal for this token will execute once.');
          }
        }
      ]
    );
  };

  return (
    <ScrollView style={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>
      {activeTrades.length === 0 ? (
        <View style={styles.empty}>
          <Icon name="trending-up" size={60} color="#ccc" />
          <Text style={styles.emptyText}>No active positions</Text>
          <Text style={styles.emptySub}>Signals appear here when trades execute</Text>
        </View>
      ) : (
        activeTrades.map((trade: any) => {
          const multiplier = trade.currentValue && trade.entry_size > 0
            ? trade.currentValue / trade.entry_size : 1;
          const progress = getTPProgress(trade);
          const nextTP = progress === 0 ? '5x' : progress === 1 ? '10x' : progress === 2 ? '20x' : '30x';

          return (
            <TouchableOpacity key={trade.id} style={styles.card} onPress={() => navigation.navigate('TradeDetail', { tradeId: trade.id })}>
              <View style={styles.header}>
                <View>
                  <Text style={styles.symbol}>{trade.token_symbol}</Text>
                  <View style={styles.badge}>
                    <Text style={styles.badgeText}>{trade.signal_type} · {trade.wallet_count} wallets</Text>
                  </View>
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  <Text style={[styles.pnl, (trade.pnl || 0) >= 0 ? styles.pos : styles.neg]}>
                    {(trade.pnl || 0) >= 0 ? '+' : ''}{(trade.pnl || 0).toFixed(2)}
                  </Text>
                  <Text style={styles.multiplier}>{multiplier.toFixed(2)}x</Text>
                </View>
              </View>

              {/* TP progress bar */}
              <View style={{ marginBottom: 12 }}>
                <View style={styles.progressBar}>
                  {[1, 2, 3, 4].map((l: number) => (
                    <View key={l} style={[styles.seg, l <= progress ? styles.segDone : styles.segPending]} />
                  ))}
                </View>
                <Text style={styles.progressText}>TP {progress}/4 · Next: {nextTP}</Text>
              </View>

              <View style={styles.details}>
                <View><Text style={styles.detailLabel}>Entry</Text><Text style={styles.detailValue}>${trade.entry_price.toFixed(8)}</Text></View>
                <View><Text style={styles.detailLabel}>Remaining</Text><Text style={styles.detailValue}>${trade.remaining_size.toFixed(2)}</Text></View>
              </View>

              <TouchableOpacity style={styles.rebuyBtn} onPress={() => handleRebuy(trade)}>
                <Text style={styles.rebuyText}>🔄 Buy Again (Manual Override)</Text>
              </TouchableOpacity>
            </TouchableOpacity>
          );
        })
      )}
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f5f5f5' },
  empty: { alignItems: 'center', paddingTop: 100 },
  emptyText: { fontSize: 18, fontWeight: '600', color: '#666', marginTop: 20 },
  emptySub: { color: '#999', marginTop: 8 },
  card: { backgroundColor: 'white', margin: 15, marginBottom: 8, padding: 15, borderRadius: 12, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 },
  header: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 12 },
  symbol: { fontSize: 18, fontWeight: 'bold' },
  badge: { backgroundColor: '#e0f2fe', paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10, marginTop: 4, alignSelf: 'flex-start' },
  badgeText: { fontSize: 11, color: '#0369a1' },
  pnl: { fontSize: 18, fontWeight: 'bold' },
  multiplier: { fontSize: 13, color: '#666', marginTop: 2 },
  pos: { color: '#4ade80' },
  neg: { color: '#f87171' },
  progressBar: { flexDirection: 'row', height: 5, borderRadius: 3, overflow: 'hidden', marginBottom: 4 },
  seg: { flex: 1, marginHorizontal: 1, borderRadius: 2 },
  segDone: { backgroundColor: '#4ade80' },
  segPending: { backgroundColor: '#e5e7eb' },
  progressText: { fontSize: 12, color: '#666' },
  details: { flexDirection: 'row', justifyContent: 'space-between', paddingTop: 10, borderTopWidth: 1, borderTopColor: '#f0f0f0', marginBottom: 10 },
  detailLabel: { color: '#666', fontSize: 12 },
  detailValue: { fontSize: 14, fontWeight: '500', marginTop: 2 },
  rebuyBtn: { borderWidth: 1, borderColor: '#6366f1', borderRadius: 8, padding: 10, alignItems: 'center' },
  rebuyText: { color: '#6366f1', fontSize: 13, fontWeight: '600' },
});

export default PositionsScreen;
