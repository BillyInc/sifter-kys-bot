import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert } from 'react-native';
import Icon from 'react-native-vector-icons/MaterialIcons';
import useStore from '../store/useStore';

const WalletDetailScreen = ({ route }) => {
  const { wallet } = route.params;
  const { watchlist, addToWatchlist, removeFromWatchlist } = useStore();
  const inList = watchlist.some(w => w.wallet_address === wallet.wallet_address);

  const handleToggle = () => {
    Alert.alert(
      inList ? 'Remove from Watchlist' : 'Add to Watchlist',
      inList ? 'Remove this wallet?' : 'Add this wallet to your watchlist?',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: inList ? 'Remove' : 'Add', onPress: () => inList ? removeFromWatchlist(wallet.wallet_address) : addToWatchlist(wallet.wallet_address, true) }
      ]
    );
  };

  const Stat = ({ label, value, color }) => (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={[styles.statValue, color && { color }]}>{value}</Text>
    </View>
  );

  return (
    <ScrollView style={styles.container}>
      {/* Hero */}
      <View style={styles.hero}>
        <Text style={styles.heroRank}>#{wallet.rank}</Text>
        <Text style={styles.heroAddress}>{wallet.wallet_address.slice(0, 16)}…{wallet.wallet_address.slice(-12)}</Text>
        <View style={[styles.tierBadge, wallet.tier === 'S' ? styles.sTier : styles.aTier]}>
          <Text style={styles.tierText}>{wallet.tier}-TIER · {wallet.professional_score.toFixed(1)}</Text>
        </View>

        <TouchableOpacity style={[styles.watchBtn, inList && styles.watchBtnActive]} onPress={handleToggle}>
          <Icon name={inList ? 'star' : 'star-border'} size={18} color={inList ? '#fbbf24' : 'white'} />
          <Text style={[styles.watchBtnText, inList && { color: '#fbbf24' }]}>
            {inList ? 'In Watchlist' : 'Add to Watchlist'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Stats grid */}
      <View style={styles.statsGrid}>
        <Stat label="ROI 30d" value={`${wallet.roi_30d.toFixed(1)}x`} color="#4ade80" />
        <Stat label="Runners" value={wallet.runners_30d} />
        <Stat label="Win Rate 7d" value={`${wallet.win_rate_7d.toFixed(1)}%`} />
        <Stat label="Consistency" value={wallet.consistency_score?.toFixed(1) || '—'} />
      </View>

      {/* Last activity */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Activity</Text>
        {wallet.last_trade_time ? (
          <View style={styles.row}>
            <Icon name="access-time" size={16} color="#666" />
            <Text style={styles.rowText}>Last trade: {new Date(wallet.last_trade_time).toLocaleDateString()}</Text>
          </View>
        ) : (
          <Text style={styles.noData}>No recent activity recorded</Text>
        )}
      </View>

      {/* Watchlist status */}
      {inList && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Watchlist Status</Text>
          {(() => {
            const w = watchlist.find(x => x.wallet_address === wallet.wallet_address);
            const statusColor = w?.status === 'healthy' ? '#4ade80' : w?.status === 'warning' ? '#fbbf24' : '#f87171';
            return (
              <>
                <View style={styles.row}>
                  <View style={[styles.dot, { backgroundColor: statusColor }]} />
                  <Text style={styles.rowText}>{w?.status || 'unknown'}</Text>
                </View>
                {w?.degradation_alerts && JSON.parse(w.degradation_alerts).map((a, i) => (
                  <Text key={i} style={styles.alert}>⚠️ {a.message}</Text>
                ))}
              </>
            );
          })()}
        </View>
      )}
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f5f5f5' },
  hero: { backgroundColor: '#6366f1', padding: 24, alignItems: 'center' },
  heroRank: { color: 'rgba(255,255,255,0.7)', fontSize: 14, marginBottom: 4 },
  heroAddress: { color: 'white', fontSize: 13, fontWeight: '500', marginBottom: 10, textAlign: 'center' },
  tierBadge: { paddingHorizontal: 14, paddingVertical: 5, borderRadius: 20, marginBottom: 16 },
  sTier: { backgroundColor: '#fef3c7' },
  aTier: { backgroundColor: '#cffafe' },
  tierText: { fontWeight: '700', fontSize: 13 },
  watchBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.6)', paddingHorizontal: 20, paddingVertical: 10, borderRadius: 25 },
  watchBtnActive: { backgroundColor: 'rgba(255,255,255,0.15)' },
  watchBtnText: { color: 'white', fontWeight: '600' },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', backgroundColor: 'white', margin: 15, borderRadius: 12, overflow: 'hidden' },
  stat: { width: '50%', padding: 16, borderBottomWidth: 1, borderRightWidth: 1, borderColor: '#f0f0f0', alignItems: 'center' },
  statLabel: { fontSize: 12, color: '#888', marginBottom: 4 },
  statValue: { fontSize: 20, fontWeight: 'bold' },
  card: { backgroundColor: 'white', marginHorizontal: 15, marginBottom: 15, padding: 16, borderRadius: 12 },
  cardTitle: { fontSize: 15, fontWeight: '600', marginBottom: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  rowText: { color: '#666', fontSize: 14 },
  noData: { color: '#aaa', fontStyle: 'italic' },
  dot: { width: 10, height: 10, borderRadius: 5 },
  alert: { color: '#92400e', fontSize: 13, marginTop: 6 },
});

export default WalletDetailScreen;
