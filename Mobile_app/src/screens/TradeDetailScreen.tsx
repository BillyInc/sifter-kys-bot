import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Alert } from 'react-native';
import Icon from 'react-native-vector-icons/MaterialIcons';
import DatabaseService from '../database/DatabaseService';
import SafeButton from '../components/SafeButton';
import fortifiedAutoTrader from '../services/FortifiedAutoTrader';
import duplicatePrevention from '../services/DuplicatePrevention';

const TP_LABELS = ['5x', '10x', '20x', '30x'];
const TP_PERCENTS = ['25%', '25%', '25%', '25%'];

interface TradeDetailScreenProps {
  route: any;
  navigation: any;
}

const TradeDetailScreen: React.FC<TradeDetailScreenProps> = ({ route, navigation }) => {
  const { tradeId } = route.params;
  const [trade, setTrade] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);

  useEffect(() => { loadTrade(); }, []);

  const loadTrade = async () => {
    const db = await DatabaseService.init();
    const tRes = await db.executeSql('SELECT * FROM active_trades WHERE id = ?', [tradeId]);
    if (tRes[0].rows.length > 0) {
      const t = tRes[0].rows.item(0);
      t.triggering_wallets = JSON.parse(t.triggering_wallets);
      setTrade(t);
    }
    const hRes = await db.executeSql('SELECT * FROM trade_history WHERE trade_id = ? ORDER BY timestamp ASC', [tradeId]);
    const hist: any[] = [];
    for (let i = 0; i < hRes[0].rows.length; i++) hist.push(hRes[0].rows.item(i));
    setHistory(hist);
  };

  const handleManualSell = () => {
    Alert.alert('Sell Position', 'Sell your entire remaining position at market price?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sell', style: 'destructive',
        onPress: async () => {
          await fortifiedAutoTrader.executeSell(trade.token_address, trade.remaining_size, 0, 4, tradeId);
          navigation.goBack();
        }
      }
    ]);
  };

  if (!trade) return <View style={styles.loading}><Text>Loading…</Text></View>;

  const tpDone = [trade.tp1_executed, trade.tp2_executed, trade.tp3_executed, trade.tp4_executed];
  const totalSold = history.filter((h: any) => h.action.startsWith('sell')).reduce((s: number, h: any) => s + h.usd_value, 0);
  const costBasis = history.find((h: any) => h.action === 'buy')?.usd_value || trade.entry_size;
  const realizedPnl = totalSold - costBasis * (totalSold / (trade.entry_size || 1));

  return (
    <ScrollView style={styles.container}>
      {/* Header */}
      <View style={[styles.header, trade.signal_type === 'multi' ? styles.headerMega : trade.signal_type === 'double' ? styles.headerDouble : styles.headerSingle]}>
        <Text style={styles.symbol}>{trade.token_symbol}</Text>
        <Text style={styles.address}>{trade.token_address.slice(0, 12)}…</Text>
        <View style={styles.signalRow}>
          <Text style={styles.signalText}>{trade.wallet_count} wallet{trade.wallet_count > 1 ? 's' : ''} · {trade.signal_type}</Text>
          <Text style={styles.entryTime}>{new Date(trade.entry_time).toLocaleString()}</Text>
        </View>
      </View>

      {/* TP progress */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Take-Profit Progress</Text>
        {tpDone.map((done: boolean, i: number) => (
          <View key={i} style={[styles.tpRow, done && styles.tpDone]}>
            <View style={styles.tpLeft}>
              <Icon name={done ? 'check-circle' : 'radio-button-unchecked'} size={20} color={done ? '#4ade80' : '#ccc'} />
              <Text style={[styles.tpLabel, done && styles.tpLabelDone]}>TP{i + 1}: {TP_LABELS[i]}</Text>
            </View>
            <Text style={styles.tpPercent}>{TP_PERCENTS[i]} of remaining</Text>
          </View>
        ))}
      </View>

      {/* Position summary */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Position</Text>
        <View style={styles.row}><Text style={styles.rowLabel}>Entry Price</Text><Text style={styles.rowVal}>${trade.entry_price.toFixed(8)}</Text></View>
        <View style={styles.row}><Text style={styles.rowLabel}>Entry Size</Text><Text style={styles.rowVal}>${trade.entry_size.toFixed(2)}</Text></View>
        <View style={styles.row}><Text style={styles.rowLabel}>Remaining</Text><Text style={styles.rowVal}>${trade.remaining_size.toFixed(2)}</Text></View>
        <View style={styles.row}><Text style={styles.rowLabel}>Total Sold</Text><Text style={styles.rowVal}>${totalSold.toFixed(2)}</Text></View>
        <View style={styles.row}><Text style={styles.rowLabel}>Realized PnL</Text><Text style={[styles.rowVal, realizedPnl >= 0 ? styles.pos : styles.neg]}>{realizedPnl >= 0 ? '+' : ''}{realizedPnl.toFixed(2)}</Text></View>
      </View>

      {/* Signal wallets */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Signal Wallets</Text>
        {trade.triggering_wallets.map((w: string, i: number) => (
          <Text key={i} style={styles.wallet}>• {w.slice(0, 12)}…{w.slice(-8)}</Text>
        ))}
      </View>

      {/* Trade history */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>History</Text>
        {history.map((h: any, i: number) => (
          <View key={i} style={styles.histRow}>
            <View>
              <Text style={styles.histAction}>{h.action.replace('_', ' ').toUpperCase()}</Text>
              <Text style={styles.histTime}>{new Date(h.timestamp).toLocaleString()}</Text>
            </View>
            <Text style={styles.histVal}>${h.usd_value.toFixed(2)}</Text>
          </View>
        ))}
      </View>

      {/* Manual sell */}
      {trade.is_active ? (
        <View style={styles.actions}>
          <SafeButton
            onPress={handleManualSell}
            title="💰 Sell Position Now"
            loadingTitle="Executing sell..."
            style={styles.sellBtn}
            requireConfirmation
            confirmationTitle="Sell your entire remaining position at market price?"
            debounceMs={5000}
          />
        </View>
      ) : (
        <View style={styles.closedBanner}>
          <Icon name="check-circle" size={20} color="#4ade80" />
          <Text style={styles.closedText}>Position closed</Text>
        </View>
      )}

      <View style={{ height: 30 }} />
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f5f5f5' },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: { padding: 24 },
  headerMega: { backgroundColor: '#dc2626' },
  headerDouble: { backgroundColor: '#2563eb' },
  headerSingle: { backgroundColor: '#6366f1' },
  symbol: { fontSize: 28, fontWeight: 'bold', color: 'white' },
  address: { color: 'rgba(255,255,255,0.7)', marginTop: 4, fontSize: 13 },
  signalRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 8 },
  signalText: { color: 'rgba(255,255,255,0.9)', fontSize: 13 },
  entryTime: { color: 'rgba(255,255,255,0.7)', fontSize: 12 },
  card: { backgroundColor: 'white', marginHorizontal: 15, marginTop: 15, padding: 16, borderRadius: 12 },
  cardTitle: { fontSize: 15, fontWeight: '600', marginBottom: 12 },
  tpRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#f0f0f0' },
  tpDone: { opacity: 0.6 },
  tpLeft: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  tpLabel: { fontSize: 15, color: '#888' },
  tpLabelDone: { textDecorationLine: 'line-through', color: '#4ade80' },
  tpPercent: { fontSize: 13, color: '#888' },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#f9f9f9' },
  rowLabel: { color: '#666', fontSize: 14 },
  rowVal: { fontSize: 14, fontWeight: '500' },
  pos: { color: '#4ade80' },
  neg: { color: '#f87171' },
  wallet: { color: '#444', fontSize: 13, marginBottom: 6 },
  histRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#f9f9f9' },
  histAction: { fontSize: 13, fontWeight: '600' },
  histTime: { fontSize: 11, color: '#aaa', marginTop: 2 },
  histVal: { fontSize: 14, fontWeight: '500' },
  actions: { margin: 15 },
  sellBtn: { backgroundColor: '#dc2626' },
  closedBanner: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, margin: 15, padding: 14, backgroundColor: '#f0fdf4', borderRadius: 10 },
  closedText: { fontSize: 15, fontWeight: '600', color: '#166534' },
});

export default TradeDetailScreen;
