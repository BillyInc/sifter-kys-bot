import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Switch, TouchableOpacity, TextInput, Alert } from 'react-native';
import Icon from 'react-native-vector-icons/MaterialIcons';
import useStore from '../store/useStore';
import DatabaseService from '../database/DatabaseService';
import ModeSwitcher from '../components/ModeSwitcher';
import killSwitch from '../services/KillSwitch';

interface SettingsScreenProps {
  navigation: any;
}

interface SectionProps {
  title: string;
  children: React.ReactNode;
}

interface RowProps {
  label: string;
  children?: React.ReactNode;
  borderBottom?: boolean;
}

const SettingsScreen: React.FC<SettingsScreenProps> = ({ navigation }) => {
  const { settings, updateSettings, userTier, tradingMode, portfolioTotal } = useStore();
  const [portfolio, setPortfolio] = useState<string>(portfolioTotal.toString());
  const [minBuy, setMinBuy] = useState<string>(settings.minBuyUsd?.toString() || '100');
  const [autoReplace, setAutoReplace] = useState<boolean>(settings.autoReplaceWallets ?? true);
  const [walletAddress, setWalletAddress] = useState<string>('');
  const [walletConnected, setWalletConnected] = useState<boolean>(false);

  useEffect(() => { loadSettings(); }, []);

  const loadSettings = async () => {
    const addr = await DatabaseService.getSetting('wallet_address');
    const connected = await DatabaseService.getSetting('wallet_connected') === 'true';
    setWalletAddress(addr || '');
    setWalletConnected(connected);
  };

  const handleSavePortfolio = async () => {
    const val = parseFloat(portfolio);
    if (isNaN(val) || val <= 0) { Alert.alert('Invalid value'); return; }
    await DatabaseService.setSetting('portfolio_total', val.toString());
    await updateSettings({ portfolio_total: val } as any);
    Alert.alert('✅ Saved', `Portfolio set to $${val.toLocaleString()}`);
  };

  const handleKillSwitch = () => {
    Alert.alert(
      '🚨 Emergency Kill Switch',
      'This will immediately stop all trading and cancel pending orders.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'ACTIVATE', style: 'destructive', onPress: () => killSwitch.activateKillSwitch('Manual activation') }
      ]
    );
  };

  const handleSelfDestruct = () => {
    Alert.alert(
      '💥 Self-Destruct',
      'This will DELETE all local data including your wallet keys. THIS CANNOT BE UNDONE.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'DESTROY', style: 'destructive',
          onPress: () => {
            Alert.alert('Final Confirmation', 'Are you 100% sure?', [
              { text: 'Cancel', style: 'cancel' },
              { text: 'YES, DESTROY', style: 'destructive', onPress: () => killSwitch.emergencySelfDestruct() }
            ]);
          }
        }
      ]
    );
  };

  const Section: React.FC<SectionProps> = ({ title, children }) => (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.sectionCard}>{children}</View>
    </View>
  );

  const Row: React.FC<RowProps> = ({ label, children, borderBottom = true }) => (
    <View style={[styles.row, borderBottom && styles.rowBorder]}>{children ? <><Text style={styles.rowLabel}>{label}</Text>{children}</> : <Text style={styles.rowLabel}>{label}</Text>}</View>
  );

  return (
    <ScrollView style={styles.container}>

      {/* Account */}
      <Section title="Account">
        <Row label="Plan">
          <Text style={[styles.badge, userTier === 'premium' ? styles.premiumBadge : styles.freeBadge]}>
            {userTier === 'premium' ? '⭐ PREMIUM' : 'FREE'}
          </Text>
        </Row>
        <Row label="Wallet" borderBottom={false}>
          {walletConnected
            ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <Text style={styles.addr}>{walletAddress.slice(0, 8)}…{walletAddress.slice(-6)}</Text>
                <TouchableOpacity onPress={() => navigation.navigate('ConnectWallet')} style={styles.smallBtn}>
                  <Text style={styles.smallBtnText}>Change</Text>
                </TouchableOpacity>
              </View>
            : <TouchableOpacity style={styles.connectBtn} onPress={() => navigation.navigate('ConnectWallet')}>
                <Text style={styles.connectBtnText}>Connect Wallet</Text>
              </TouchableOpacity>
          }
        </Row>
      </Section>

      {/* Trading mode (premium only) */}
      {userTier === 'premium' && (
        <View style={{ marginBottom: 5 }}>
          <Text style={[styles.sectionTitle, { marginHorizontal: 15, marginBottom: 5 }]}>Trading Mode</Text>
          <ModeSwitcher />
        </View>
      )}

      {/* Portfolio */}
      <Section title="Portfolio">
        <Row label="Total Portfolio">
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <TextInput style={styles.input} value={portfolio} onChangeText={setPortfolio} keyboardType="numeric" />
            <TouchableOpacity onPress={handleSavePortfolio} style={styles.saveBtn}><Text style={styles.saveBtnText}>Save</Text></TouchableOpacity>
          </View>
        </Row>
        <Row label="Trading Balance (10%)" borderBottom={false}>
          <Text style={styles.value}>${(parseFloat(portfolio || '0') * 0.1).toFixed(0)}</Text>
        </Row>
      </Section>

      {/* Trade settings */}
      <Section title="Trade Settings">
        <Row label="Min signal amount ($)">
          <TextInput style={styles.input} value={minBuy} onChangeText={setMinBuy} keyboardType="numeric" onBlur={() => updateSettings({ minBuyUsd: parseFloat(minBuy) || 100 })} />
        </Row>
        <Row label="Auto-replace wallets" borderBottom={false}>
          <Switch value={autoReplace} onValueChange={(v: boolean) => { setAutoReplace(v); updateSettings({ autoReplaceWallets: v }); }} trackColor={{ true: '#6366f1', false: '#e5e7eb' }} />
        </Row>
      </Section>

      {/* Protection info */}
      <Section title="MEV Protection">
        <Row label="Encrypted Mempool"><Text style={styles.active}>✅ Active</Text></Row>
        <Row label="JITO Bundles"><Text style={styles.active}>✅ Active</Text></Row>
        <Row label="Sniper Defense"><Text style={styles.active}>✅ Active</Text></Row>
        <Row label="Base slippage"><Text style={styles.value}>15%</Text></Row>
        <Row label="Extreme slippage"><Text style={styles.value}>50%</Text></Row>
        <Row label="Panic slippage" borderBottom={false}><Text style={styles.value}>75%</Text></Row>
      </Section>

      {/* Danger zone */}
      <Section title="⚠️ Danger Zone">
        <TouchableOpacity style={styles.dangerBtn} onPress={handleKillSwitch}>
          <Icon name="power-settings-new" size={18} color="white" />
          <Text style={styles.dangerBtnText}>Emergency Kill Switch</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.dangerBtn, { backgroundColor: '#7f1d1d', marginTop: 8, marginBottom: 0 }]} onPress={handleSelfDestruct}>
          <Icon name="delete-forever" size={18} color="white" />
          <Text style={styles.dangerBtnText}>Self-Destruct (Delete All Data)</Text>
        </TouchableOpacity>
      </Section>

      <View style={{ height: 40 }} />
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f5f5f5' },
  section: { marginHorizontal: 15, marginBottom: 20 },
  sectionTitle: { fontSize: 13, fontWeight: '700', color: '#888', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8, marginTop: 16 },
  sectionCard: { backgroundColor: 'white', borderRadius: 12, overflow: 'hidden' },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 14 },
  rowBorder: { borderBottomWidth: 1, borderBottomColor: '#f0f0f0' },
  rowLabel: { fontSize: 15, color: '#333' },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12, fontSize: 12, fontWeight: '700', overflow: 'hidden' },
  premiumBadge: { backgroundColor: '#fef3c7', color: '#92400e' },
  freeBadge: { backgroundColor: '#f3f4f6', color: '#666' },
  addr: { fontSize: 13, color: '#666' },
  connectBtn: { backgroundColor: '#6366f1', paddingHorizontal: 14, paddingVertical: 7, borderRadius: 8 },
  connectBtnText: { color: 'white', fontSize: 13, fontWeight: '600' },
  smallBtn: { backgroundColor: '#f3f4f6', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 6 },
  smallBtnText: { fontSize: 12, color: '#333' },
  input: { borderWidth: 1, borderColor: '#e5e7eb', borderRadius: 8, padding: 8, width: 100, textAlign: 'right', fontSize: 14 },
  saveBtn: { backgroundColor: '#6366f1', paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8 },
  saveBtnText: { color: 'white', fontSize: 13, fontWeight: '600' },
  value: { fontSize: 14, color: '#6366f1', fontWeight: '600' },
  active: { fontSize: 13, color: '#4ade80', fontWeight: '600' },
  dangerBtn: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#dc2626', padding: 14, borderRadius: 10, margin: 4, marginBottom: 4 },
  dangerBtnText: { color: 'white', fontWeight: '600', fontSize: 15 },
});

export default SettingsScreen;
