import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import useStore from '../store/useStore';
import fortifiedAutoTrader from '../services/FortifiedAutoTrader';

// Only renders for premium users. Free users never see this component.
const ModeSwitcher = () => {
  const { userTier, tradingMode, setTradingMode } = useStore();
  const [switching, setSwitching] = useState(false);

  if (userTier !== 'premium') return null;

  const handleSwitch = async (mode) => {
    if (mode === tradingMode || switching) return;
    setSwitching(true);
    await fortifiedAutoTrader.setTradingMode(mode);
    await setTradingMode(mode);
    setSwitching(false);
  };

  const isAuto = tradingMode === 'auto';

  return (
    <View style={styles.container}>
      <Text style={styles.label}>Trading Mode</Text>

      <View style={styles.row}>
        <TouchableOpacity
          style={[styles.btn, isAuto && styles.activeBtn]}
          onPress={() => handleSwitch('auto')}
          disabled={switching}
        >
          <Text style={[styles.btnIcon]}>{isAuto ? '🤖' : '🤖'}</Text>
          <Text style={[styles.btnTitle, isAuto && styles.activeBtnTitle]}>AUTO</Text>
          <Text style={[styles.btnDesc, isAuto && styles.activeBtnDesc]}>Bot trades Elite 15</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.btn, !isAuto && styles.activeBtn]}
          onPress={() => handleSwitch('manual')}
          disabled={switching}
        >
          <Text style={styles.btnIcon}>👤</Text>
          <Text style={[styles.btnTitle, !isAuto && styles.activeBtnTitle]}>MANUAL</Text>
          <Text style={[styles.btnDesc, !isAuto && styles.activeBtnDesc]}>You control all trades</Text>
        </TouchableOpacity>
      </View>

      <View style={[styles.statusCard, !isAuto && styles.manualCard]}>
        {isAuto ? (
          <>
            <Text style={styles.statusTitle}>✅ Auto-trader ACTIVE</Text>
            <Text style={styles.statusSub}>Watching Elite 15 — executes automatically</Text>
          </>
        ) : (
          <>
            <Text style={styles.statusTitle}>👤 Manual mode ACTIVE</Text>
            <Text style={styles.statusSub}>Notifications for all signals — you decide</Text>
          </>
        )}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { padding: 15, backgroundColor: '#f8f9fa', borderRadius: 12, margin: 15 },
  label: { fontSize: 13, color: '#888', marginBottom: 10, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5 },
  row: { flexDirection: 'row', gap: 10 },
  btn: { flex: 1, padding: 14, borderRadius: 10, backgroundColor: 'white', borderWidth: 1.5, borderColor: '#e5e7eb', alignItems: 'center' },
  activeBtn: { backgroundColor: '#6366f1', borderColor: '#6366f1' },
  btnIcon: { fontSize: 22, marginBottom: 4 },
  btnTitle: { fontWeight: 'bold', fontSize: 14, color: '#333' },
  activeBtnTitle: { color: 'white' },
  btnDesc: { fontSize: 11, color: '#888', marginTop: 2, textAlign: 'center' },
  activeBtnDesc: { color: 'rgba(255,255,255,0.8)' },
  statusCard: { marginTop: 12, padding: 12, backgroundColor: '#e3f2fd', borderRadius: 8 },
  manualCard: { backgroundColor: '#fff3e0' },
  statusTitle: { fontSize: 14, fontWeight: '600', marginBottom: 3 },
  statusSub: { fontSize: 12, color: '#666' },
});

export default ModeSwitcher;
