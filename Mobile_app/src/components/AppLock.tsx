import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, Modal, TextInput, StyleSheet } from 'react-native';
import * as LocalAuthentication from 'expo-local-authentication';
import * as Crypto from 'expo-crypto';
import AsyncStorage from '@react-native-async-storage/async-storage';

const hashPin = async (pin: string): Promise<string> => {
  return await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, pin);
};

interface AppLockProps {
  children: React.ReactNode;
}

const AppLock: React.FC<AppLockProps> = ({ children }) => {
  const [isLocked, setIsLocked] = useState<boolean>(true);
  const [pin, setPin] = useState<string>('');
  const [attempts, setAttempts] = useState<number>(0);
  const [lockoutUntil, setLockoutUntil] = useState<number | null>(null);

  // Load persisted lockout state on mount
  useEffect(() => {
    (async () => {
      try {
        const savedAttempts = await AsyncStorage.getItem('pin_attempts');
        const savedLockout = await AsyncStorage.getItem('pin_lockout_until');
        if (savedAttempts) setAttempts(parseInt(savedAttempts, 10));
        if (savedLockout) {
          const until = parseInt(savedLockout, 10);
          if (Date.now() < until) {
            setLockoutUntil(until);
          } else {
            // Lockout expired — clear persisted state
            await AsyncStorage.multiRemove(['pin_attempts', 'pin_lockout_until']);
          }
        }
      } catch {}
    })();
  }, []);

  useEffect(() => {
    checkLockStatus();
  }, []);

  const checkLockStatus = async () => {
    const locked = await AsyncStorage.getItem('app_locked');
    // First launch or explicitly unlocked → auto-attempt biometric
    if (locked !== 'true') {
      setIsLocked(false);
    } else {
      handleBiometricAuth();
    }
  };

  const handleBiometricAuth = async () => {
    const compatible = await LocalAuthentication.hasHardwareAsync();
    const enrolled = await LocalAuthentication.isEnrolledAsync();
    if (!compatible || !enrolled) return;

    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Unlock Sifter',
      fallbackLabel: 'Use PIN',
      disableDeviceFallback: false,
    });

    if (result.success) {
      setIsLocked(false);
      await AsyncStorage.setItem('app_locked', 'false');
    }
  };

  const handlePinAuth = async () => {
    if (lockoutUntil && Date.now() < lockoutUntil) {
      const mins = Math.ceil((lockoutUntil - Date.now()) / 60000);
      alert(`Too many attempts. Try again in ${mins} minute(s).`);
      return;
    }

    const storedPinHash = await AsyncStorage.getItem('user_pin_hash');
    const pinHash = await hashPin(pin);

    if (!storedPinHash) {
      // No PIN set — first time, save the hash of this PIN
      await AsyncStorage.setItem('user_pin_hash', pinHash);
      setIsLocked(false);
      await AsyncStorage.setItem('app_locked', 'false');
      return;
    }

    if (pinHash === storedPinHash) {
      setIsLocked(false);
      setAttempts(0);
      setLockoutUntil(null);
      await AsyncStorage.multiRemove(['pin_attempts', 'pin_lockout_until']);
      await AsyncStorage.setItem('app_locked', 'false');
    } else {
      const newAttempts = attempts + 1;
      setAttempts(newAttempts);
      setPin('');
      if (newAttempts >= 5) {
        const until = Date.now() + 15 * 60000;
        setLockoutUntil(until);
        setAttempts(0);
        await AsyncStorage.setItem('pin_lockout_until', until.toString());
        await AsyncStorage.setItem('pin_attempts', '0');
        alert('Too many failed attempts. Locked for 15 minutes.');
      } else {
        await AsyncStorage.setItem('pin_attempts', newAttempts.toString());
        alert(`Incorrect PIN. ${5 - newAttempts} attempt(s) remaining.`);
      }
    }
  };

  if (!isLocked) return <>{children}</>;

  return (
    <Modal visible={isLocked} animationType="slide">
      <View style={styles.container}>
        <Text style={styles.icon}>🔒</Text>
        <Text style={styles.title}>Sifter Locked</Text>

        <TouchableOpacity style={styles.biometricButton} onPress={handleBiometricAuth}>
          <Text style={styles.biometricText}>Use Face ID / Fingerprint</Text>
        </TouchableOpacity>

        <Text style={styles.or}>or</Text>

        <TextInput
          style={styles.pinInput}
          placeholder="Enter PIN"
          value={pin}
          onChangeText={setPin}
          secureTextEntry
          maxLength={6}
          keyboardType="numeric"
        />

        <TouchableOpacity style={styles.pinButton} onPress={handlePinAuth}>
          <Text style={styles.pinButtonText}>Unlock with PIN</Text>
        </TouchableOpacity>

        {lockoutUntil && (
          <Text style={styles.lockoutText}>
            Locked until {new Date(lockoutUntil).toLocaleTimeString()}
          </Text>
        )}
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 30, backgroundColor: '#fff' },
  icon: { fontSize: 60, marginBottom: 16 },
  title: { fontSize: 24, fontWeight: 'bold', marginBottom: 32 },
  biometricButton: { backgroundColor: '#6366f1', padding: 16, borderRadius: 10, width: '100%', alignItems: 'center', marginBottom: 12 },
  biometricText: { color: 'white', fontWeight: '600', fontSize: 16 },
  or: { color: '#999', marginVertical: 12 },
  pinInput: { borderWidth: 1, borderColor: '#ddd', padding: 14, width: '100%', borderRadius: 10, textAlign: 'center', fontSize: 22, letterSpacing: 8, marginBottom: 12 },
  pinButton: { backgroundColor: '#333', padding: 16, borderRadius: 10, width: '100%', alignItems: 'center' },
  pinButtonText: { color: 'white', fontWeight: '600', fontSize: 16 },
  lockoutText: { color: '#ef4444', marginTop: 16 },
});

export default AppLock;
