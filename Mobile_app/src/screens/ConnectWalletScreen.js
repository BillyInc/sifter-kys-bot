import React, { useState } from 'react';
import { View, Text, StyleSheet, TextInput, Alert, ScrollView, TouchableOpacity } from 'react-native';
import { Keypair } from '@solana/web3.js';
import * as bs58 from 'bs58';
import DatabaseService from '../database/DatabaseService';
import secureWalletService from '../services/SecureWalletService';
import SafeButton from '../components/SafeButton';

const ConnectWalletScreen = ({ navigation }) => {
  const [privateKey, setPrivateKey] = useState('');
  const [mode, setMode] = useState('import'); // 'import' | 'create'

  const handleImport = async () => {
    if (!privateKey.trim()) { Alert.alert('Enter a private key'); return; }
    try {
      const decoded = bs58.decode(privateKey.trim());
      const keypair = Keypair.fromSecretKey(decoded);
      await secureWalletService.storeWallet(privateKey.trim(), keypair.publicKey.toString());
      await DatabaseService.setSetting('wallet_address', keypair.publicKey.toString());
      await DatabaseService.setSetting('wallet_connected', 'true');
      Alert.alert('✅ Wallet Connected', `Address: ${keypair.publicKey.toString().slice(0, 12)}…`, [
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

    Alert.alert(
      '✅ Wallet Created',
      `Address:\n${keypair.publicKey.toString()}\n\n⚠️ Save your private key in a secure place:\n${privKey}\n\nYou CANNOT recover it later.`,
      [{ text: 'I saved it', onPress: () => navigation.goBack() }]
    );
  };

  const handleDisconnect = async () => {
    Alert.alert('Disconnect Wallet?', 'This removes your wallet from the app.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Disconnect', style: 'destructive',
        onPress: async () => {
          await secureWalletService.deleteWallet();
          await DatabaseService.setSetting('wallet_connected', 'false');
          await DatabaseService.setSetting('wallet_address', '');
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
        <Text style={styles.subtitle}>Your private key is encrypted on-device only. It never leaves your phone.</Text>
      </View>

      {/* Mode tabs */}
      <View style={styles.tabs}>
        {['import', 'create'].map(m => (
          <TouchableOpacity key={m} style={[styles.tab, mode === m && styles.activeTab]} onPress={() => setMode(m)}>
            <Text style={[styles.tabText, mode === m && styles.activeTabText]}>{m === 'import' ? 'Import Existing' : 'Create New'}</Text>
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
            title="🔐 Import Wallet"
            loadingTitle="Encrypting..."
            style={styles.actionBtn}
            requireConfirmation
            confirmationTitle="Import this private key? Make sure you trust this device."
            debounceMs={3000}
          />
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.createInfo}>
            A new Solana wallet will be created and stored securely on this device. You will receive your private key — write it down somewhere safe.
          </Text>
          <SafeButton
            onPress={handleCreate}
            title="✨ Generate New Wallet"
            loadingTitle="Generating..."
            style={styles.actionBtn}
            debounceMs={3000}
          />
        </View>
      )}

      <TouchableOpacity style={styles.disconnectBtn} onPress={handleDisconnect}>
        <Text style={styles.disconnectText}>Disconnect Wallet</Text>
      </TouchableOpacity>

      <View style={styles.securityNote}>
        <Text style={styles.noteIcon}>🛡️</Text>
        <Text style={styles.noteText}>
          Your private key is split and stored using device-only encryption. Biometric authentication is required for every transaction.
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
  tabs: { flexDirection: 'row', backgroundColor: '#e5e7eb', borderRadius: 10, padding: 3, marginBottom: 20 },
  tab: { flex: 1, paddingVertical: 10, borderRadius: 8, alignItems: 'center' },
  activeTab: { backgroundColor: 'white' },
  tabText: { color: '#666', fontWeight: '500' },
  activeTabText: { color: '#6366f1', fontWeight: '700' },
  card: { backgroundColor: 'white', borderRadius: 12, padding: 16, marginBottom: 16 },
  label: { fontSize: 14, fontWeight: '600', marginBottom: 8, color: '#333' },
  keyInput: { borderWidth: 1, borderColor: '#e5e7eb', borderRadius: 8, padding: 12, fontSize: 13, fontFamily: 'monospace', marginBottom: 16, minHeight: 80, textAlignVertical: 'top' },
  actionBtn: { backgroundColor: '#6366f1' },
  createInfo: { color: '#666', lineHeight: 22, marginBottom: 16 },
  disconnectBtn: { alignItems: 'center', padding: 14, borderWidth: 1, borderColor: '#f87171', borderRadius: 10, marginBottom: 16 },
  disconnectText: { color: '#f87171', fontWeight: '600' },
  securityNote: { flexDirection: 'row', backgroundColor: '#f0fdf4', padding: 14, borderRadius: 10, alignItems: 'flex-start', gap: 10 },
  noteIcon: { fontSize: 18 },
  noteText: { flex: 1, color: '#166534', fontSize: 13, lineHeight: 20 },
});

export default ConnectWalletScreen;
