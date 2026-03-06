import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, Alert } from 'react-native';
import Icon from 'react-native-vector-icons/MaterialIcons';
import useStore from '../store/useStore';

const Elite15Screen = ({ navigation }) => {
  const { elite15, watchlist, loadElite15, loadWatchlist, addToWatchlist, removeFromWatchlist } = useStore();
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => { await loadElite15(); await loadWatchlist(); };
  const onRefresh = async () => { setRefreshing(true); await loadData(); setRefreshing(false); };

  const handleToggleWatchlist = (wallet) => {
    const inList = watchlist.some(w => w.wallet_address === wallet.wallet_address);
    const short = wallet.wallet_address.slice(0, 8);
    Alert.alert(
      inList ? 'Remove from Watchlist' : 'Add to Watchlist',
      `${inList ? 'Remove' : 'Add'} ${short}…?`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: inList ? 'Remove' : 'Add', style: inList ? 'destructive' : 'default',
          onPress: () => inList ? removeFromWatchlist(wallet.wallet_address) : addToWatchlist(wallet.wallet_address, true) }
      ]
    );
  };

  const tierColor = { S: '#fee2e2', A: '#cffafe', B: '#e0f2fe', C: '#f3e8ff', F: '#f5f5f5' };

  return (
    <ScrollView style={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>
      <View style={styles.header}>
        <Text style={styles.title}>Elite 15 Wallets</Text>
        <Text style={styles.subtitle}>These wallets feed the auto-trader</Text>
      </View>

      {elite15.map(wallet => {
        const inList = watchlist.some(w => w.wallet_address === wallet.wallet_address);
        const listStatus = watchlist.find(w => w.wallet_address === wallet.wallet_address)?.status;

        return (
          <TouchableOpacity key={wallet.wallet_address} style={[styles.card, inList && styles.cardWatched, listStatus === 'critical' && styles.cardCritical]}
            onPress={() => navigation.navigate('WalletDetail', { wallet })}>

            <View style={styles.cardHeader}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <Text style={styles.rank}>#{wallet.rank}</Text>
                {listStatus === 'critical' && <Icon name="error" size={16} color="#f87171" />}
                {listStatus === 'warning' && <Icon name="warning" size={16} color="#fbbf24" />}
                {listStatus === 'healthy' && <Icon name="check-circle" size={16} color="#4ade80" />}
              </View>
              <TouchableOpacity onPress={() => handleToggleWatchlist(wallet)} style={[styles.starBtn, inList && styles.starActive]}>
                <Icon name={inList ? 'star' : 'star-border'} size={22} color={inList ? '#fbbf24' : '#aaa'} />
              </TouchableOpacity>
            </View>

            <Text style={styles.address}>{wallet.wallet_address.slice(0, 12)}…{wallet.wallet_address.slice(-8)}</Text>

            <View style={styles.stats}>
              <View style={styles.stat}>
                <Text style={styles.statLabel}>Score</Text>
                <Text style={styles.statValue}>{wallet.professional_score.toFixed(1)}</Text>
              </View>
              <View style={styles.stat}>
                <Text style={styles.statLabel}>Tier</Text>
                <View style={[styles.tierBadge, { backgroundColor: tierColor[wallet.tier] || '#eee' }]}>
                  <Text style={styles.tierText}>{wallet.tier}</Text>
                </View>
              </View>
              <View style={styles.stat}>
                <Text style={styles.statLabel}>ROI 30d</Text>
                <Text style={styles.statValue}>{wallet.roi_30d.toFixed(1)}x</Text>
              </View>
            </View>

            <View style={styles.footer}>
              <View style={styles.footerItem}><Icon name="trending-up" size={13} color="#666" /><Text style={styles.footerText}>{wallet.runners_30d} runners</Text></View>
              <View style={styles.footerItem}><Icon name="check-circle" size={13} color="#666" /><Text style={styles.footerText}>{wallet.win_rate_7d.toFixed(1)}% WR</Text></View>
            </View>
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f5f5f5' },
  header: { padding: 20, backgroundColor: 'white', marginBottom: 8 },
  title: { fontSize: 20, fontWeight: 'bold' },
  subtitle: { color: '#666', marginTop: 4 },
  card: { backgroundColor: 'white', marginHorizontal: 15, marginBottom: 10, padding: 15, borderRadius: 12, elevation: 1 },
  cardWatched: { borderLeftWidth: 3, borderLeftColor: '#6366f1' },
  cardCritical: { borderLeftColor: '#f87171' },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  rank: { fontSize: 16, fontWeight: '600', color: '#6366f1' },
  starBtn: { padding: 4 },
  starActive: { backgroundColor: '#fef3c7', borderRadius: 20 },
  address: { fontSize: 14, fontWeight: '500', marginBottom: 10, color: '#333' },
  stats: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 10 },
  stat: { alignItems: 'center' },
  statLabel: { color: '#666', fontSize: 11, marginBottom: 3 },
  statValue: { fontSize: 16, fontWeight: '600' },
  tierBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 10 },
  tierText: { fontSize: 12, fontWeight: '700' },
  footer: { flexDirection: 'row', borderTopWidth: 1, borderTopColor: '#f0f0f0', paddingTop: 8 },
  footerItem: { flexDirection: 'row', alignItems: 'center', marginRight: 20 },
  footerText: { marginLeft: 4, color: '#666', fontSize: 12 },
});

export default Elite15Screen;
