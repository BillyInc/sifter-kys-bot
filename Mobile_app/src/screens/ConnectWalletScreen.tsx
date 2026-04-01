import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TextInput, Alert, ScrollView, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Keypair } from '@solana/web3.js';
import * as bs58 from 'bs58';
import DatabaseService from '../database/DatabaseService';
import secureWalletService from '../services/SecureWalletService';
import SafeButton from '../components/SafeButton';
import { useWalletAdapter } from '../hooks/useWalletAdapter';

interface ConnectWalletScreenProps {
  navigation: any;
}

const ConnectWalletScreen: React.FC<ConnectWalletScreenProps> = ({ navigation }) => {
  const [privateKey, setPrivateKey] = useState<string>('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [mode, setMode] = useState<'import' | 'create'>('import');
  const [connectedAddress, setConnectedAddress] = useState<string | null>(null);

  const { walletAddress, isConnecting, isConnected, connect, disconnect, loadPersistedWallet } = useWalletAdapter();

  useEffect(() => {
    loadPersistedWallet();
    // Also check DB for manually imported wallets
    DatabaseService.getSetting('wallet_address').then((addr: string | null) => {
      if (addr) setConnectedAddress(addr);
    });
  }, []);

  useEffect(() => {
    if (walletAddress) setConnectedAddress(walletAddress);
  }, [walletAddress]);

  // ── Wallet Adapter connect (Phantom / Solflare) ──────────────────────────
  const handleWalletAdapterConnect = async () => {
    try {
      const result = await connect();
      await DatabaseService.setSetting('wallet_address', result.address);
      await DatabaseService.setSetting('wallet_connected', 'true');
      await DatabaseService.setSetting('wallet_type', 'mobile-adapter');
      setConnectedAddress(result.address);
      Alert.alert('Wallet Connected', `Address: ${result.address.slice(0, 12)}...`, [
        { text: 'OK', onPress: () => navigation.goBack() }
      ]);
    } catch (error: any) {
      if (error.message?.includes('cancel')) {
        // User cancelled — do nothing
        return;
      }
      Alert.alert('Connection Failed', error.message || 'Could not connect to wallet app. Make sure Phantom or Solflare is installed.');
    }
  };

  // ── Manual private key import (advanced fallback) ────────────────────────
  const handleImport = async () => {
    if (!privateKey.trim()) { Alert.alert('Enter a private key'); return; }
    try {
      const decoded = bs58.decode(privateKey.trim());
      const keypair = Keypair.fromSecretKey(decoded);
      await secureWalletService.storeWallet(privateKey.trim(), keypair.publicKey.toString());
      await DatabaseService.setSetting('wallet_address', keypair.publicKey.toString());
      await DatabaseService.setSetting('wallet_connected', 'true');
      await DatabaseService.setSetting('wallet_type', 'manual-import');
      setConnectedAddress(keypair.publicKey.toString());
      Alert.alert('Wallet Connected', `Address: ${keypair.publicKey.toString().slice(0, 12)}...`, [
        { text: 'OK', onPress: () => navigation.goBack() }
      ]);
    } catch {
      Alert.alert('Invalid private key', 'Please check and try again.');
    }
  };

  const handleCreate = async () => {
    const keypair = Keypair.generate();
    const privKey = bs58.encode(keypair.secretKey);
    await secureWalletService.storeWallet(privKey, keypair.publicKey.toString());
    await DatabaseService.setSetting('wallet_address', keypair.publicKey.toString());
    await DatabaseService.setSetting('wallet_connected', 'true');
    await DatabaseService.setSetting('wallet_type', 'manual-import');
    setConnectedAddress(keypair.publicKey.toString());

    Alert.alert(
      'Wallet Created',
      `Address:\n${keypair.publicKey.toString()}\n\nSave your private key in a secure place:\n${privKey}\n\nYou CANNOT recover it later.`,
      [{ text: 'I saved it', onPress: () => navigation.goBack() }]
    );
  };

  const handleDisconnect = async () => {
    Alert.alert('Disconnect Wallet?', 'This removes your wallet from the app.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Disconnect', style: 'destructive',
        onPress: async () => {
          await disconnect();
          await secureWalletService.deleteWallet();
          await DatabaseService.setSetting('wallet_connected', 'false');
          await DatabaseService.setSetting('wallet_address', '');
          await DatabaseService.setSetting('wallet_type', '');
          setConnectedAddress(null);
          navigation.goBack();
        }
      }
    ]);
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.header}>
        <Text style={styles.icon}>🔐</Text>
        <Text style={styles.title}>Connect Wallet</Text>
        <Text style={styles.subtitle}>
          Connect your Solana wallet to start trading. Use your preferred wallet app for the most secure experience.
        </Text>
      </View>

      {/* Connected status */}
      {connectedAddress && (
        <View style={styles.connectedBanner}>
          <Text style={styles.connectedLabel}>Connected</Text>
          <Text style={styles.connectedAddress}>{connectedAddress.slice(0, 6)}...{connectedAddress.slice(-4)}</Text>
        </View>
      )}

      {/* Primary: Wallet Adapter connect */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Connect with Wallet App</Text>
        <Text style={styles.cardDesc}>
          Opens Phantom, Solflare, or another installed Solana wallet. Your private keys stay in your wallet app.
        </Text>
        <SafeButton
          onPress={handleWalletAdapterConnect}
          title={isConnecting ? 'Connecting...' : 'Connect Wallet'}
          loadingTitle="Connecting..."
          style={styles.primaryBtn}
          debounceMs={2000}
          disabled={isConnecting}
        />
        {isConnecting && <ActivityIndicator style={{ marginTop: 10 }} color="#6366f1" />}
        <Text style={styles.adapterNote}>
          Note: Wallet adapter connections require approval for each transaction. Auto-trading is not available in this mode.
        </Text>
      </View>

      {/* Advanced: Manual import (collapsible) */}
      <TouchableOpacity
        style={styles.advancedToggle}
        onPress={() => setShowAdvanced(!showAdvanced)}
      >
        <Text style={styles.advancedToggleText}>
          {showAdvanced ? 'Hide' : 'Show'} Advanced: Import Key
        </Text>
        <Text style={styles.chevron}>{showAdvanced ? '▲' : '▼'}</Text>
      </TouchableOpacity>

      {showAdvanced && (
        <>
          {/* Mode tabs */}
          <View style={styles.tabs}>
            {(['import', 'create'] as const).map((m) => (
              <TouchableOpacity key={m} style={[styles.tab, mode === m && styles.activeTab]} onPress={() => setMode(m)}>
                <Text style={[styles.tabText, mode === m && styles.activeTabText]}>
                  {m === 'import' ? 'Import Existing' : 'Create New'}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {mode === 'import' ? (
            <View style={styles.card}>
              <Text style={styles.label}>Private Key (base58)</Text>
              <TextInput
                style={styles.keyInput}
                value={privateKey}
                onChangeText={setPrivateKey}
                placeholder="Enter your Solana private key"
                secureTextEntry
                multiline
                numberOfLines={3}
                autoCapitalize="none"
                autoCorrect={false}
              />
              <SafeButton
                onPress={handleImport}
                title="Import Wallet"
                loadingTitle="Encrypting..."
                style={styles.actionBtn}
                requireConfirmation
                confirmationTitle="Import this private key? Make sure you trust this device."
                debounceMs={3000}
              />
              <Text style={styles.importWarning}>
                Importing a private key enables auto-trading but stores key material on this device. Only use on a device you fully trust.
              </Text>
            </View>
          ) : (
            <View style={styles.card}>
              <Text style={styles.createInfo}>
                A new Solana wallet will be created and stored securely on this device. You will receive your private key — write it down somewhere safe.
              </Text>
              <SafeButton
                onPress={handleCreate}
                title="Generate New Wallet"
                loadingTitle="Generating..."
                style={styles.actionBtn}
                debounceMs={3000}
              />
            </View>
          )}
        </>
      )}

      {/* Disconnect */}
      {connectedAddress && (
        <TouchableOpacity style={styles.disconnectBtn} onPress={handleDisconnect}>
          <Text style={styles.disconnectText}>Disconnect Wallet</Text>
        </TouchableOpacity>
      )}

      <View style={styles.securityNote}>
        <Text style={styles.noteIcon}>🛡️</Text>
        <Text style={styles.noteText}>
          Your wallet connection is managed by your wallet app. Private keys never touch Sifter KYS.
        </Text>
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f5f5f5' },
  content: { padding: 20 },
  header: { alignItems: 'center', marginBottom: 24 },
  icon: { fontSize: 48, marginBottom: 12 },
  title: { fontSize: 22, fontWeight: 'bold' },
  subtitle: { textAlign: 'center', color: '#666', marginTop: 8, lineHeight: 20 },
  connectedBanner: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: '#ecfdf5', borderWidth: 1, borderColor: '#6ee7b7',
    borderRadius: 10, padding: 14, marginBottom: 16,
  },
  connectedLabel: { color: '#059669', fontWeight: '700', fontSize: 14 },
  connectedAddress: { color: '#065f46', fontFamily: 'monospace', fontSize: 13 },
  card: { backgroundColor: 'white', borderRadius: 12, padding: 16, marginBottom: 16 },
  cardTitle: { fontSize: 16, fontWeight: '700', color: '#1f2937', marginBottom: 6 },
  cardDesc: { color: '#6b7280', fontSize: 13, lineHeight: 20, marginBottom: 14 },
  primaryBtn: { backgroundColor: '#6366f1' },
  adapterNote: { color: '#9ca3af', fontSize: 11, marginTop: 10, lineHeight: 16, textAlign: 'center' },
  advancedToggle: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: 14, paddingHorizontal: 4, marginBottom: 8,
  },
  advancedToggleText: { color: '#6366f1', fontWeight: '600', fontSize: 14 },
  chevron: { color: '#6366f1', fontSize: 12 },
  tabs: { flexDirection: 'row', backgroundColor: '#e5e7eb', borderRadius: 10, padding: 3, marginBottom: 20 },
  tab: { flex: 1, paddingVertical: 10, borderRadius: 8, alignItems: 'center' },
  activeTab: { backgroundColor: 'white' },
  tabText: { color: '#666', fontWeight: '500' },
  activeTabText: { color: '#6366f1', fontWeight: '700' },
  label: { fontSize: 14, fontWeight: '600', marginBottom: 8, color: '#333' },
  keyInput: { borderWidth: 1, borderColor: '#e5e7eb', borderRadius: 8, padding: 12, fontSize: 13, fontFamily: 'monospace', marginBottom: 16, minHeight: 80, textAlignVertical: 'top' },
  actionBtn: { backgroundColor: '#6366f1' },
  importWarning: { color: '#d97706', fontSize: 11, marginTop: 10, lineHeight: 16 },
  createInfo: { color: '#666', lineHeight: 22, marginBottom: 16 },
  disconnectBtn: { alignItems: 'center', padding: 14, borderWidth: 1, borderColor: '#f87171', borderRadius: 10, marginBottom: 16 },
  disconnectText: { color: '#f87171', fontWeight: '600' },
  securityNote: { flexDirection: 'row', backgroundColor: '#f0fdf4', padding: 14, borderRadius: 10, alignItems: 'flex-start', gap: 10 },
  noteIcon: { fontSize: 18 },
  noteText: { flex: 1, color: '#166534', fontSize: 13, lineHeight: 20 },
});

export default ConnectWalletScreen;
