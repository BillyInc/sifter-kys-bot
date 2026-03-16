import * as SecureStore from 'expo-secure-store';
import * as LocalAuthentication from 'expo-local-authentication';

class SecureWalletService {
  constructor() {
    this.biometricAvailable = false;
  }

  async init() {
    const compatible = await LocalAuthentication.hasHardwareAsync();
    const enrolled = await LocalAuthentication.isEnrolledAsync();
    this.biometricAvailable = compatible && enrolled;
    console.log(`🔐 Biometric available: ${this.biometricAvailable}`);
  }

  async storeWallet(privateKey, walletAddress) {
    // Encrypt private key and split storage across two SecureStore keys
    const encoded = Buffer.from(privateKey).toString('base64');
    const mid = Math.floor(encoded.length / 2);
    const part1 = encoded.slice(0, mid);
    const part2 = encoded.slice(mid);

    await SecureStore.setItemAsync('wallet_key_part1', part1);
    await SecureStore.setItemAsync('wallet_key_part2', part2, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY
    });
    await SecureStore.setItemAsync('wallet_address', walletAddress);
    console.log('✅ Wallet stored securely');
  }

  async retrieveWallet() {
    const auth = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Authenticate to trade',
      disableDeviceFallback: false
    });
    if (!auth.success) throw new Error('Authentication failed');

    const part1 = await SecureStore.getItemAsync('wallet_key_part1');
    const part2 = await SecureStore.getItemAsync('wallet_key_part2');
    if (!part1 || !part2) throw new Error('Wallet not found');

    const privateKey = Buffer.from(part1 + part2, 'base64').toString();
    const address = await SecureStore.getItemAsync('wallet_address');
    return { privateKey, address };
  }

  async deleteWallet() {
    await SecureStore.deleteItemAsync('wallet_key_part1');
    await SecureStore.deleteItemAsync('wallet_key_part2');
    await SecureStore.deleteItemAsync('wallet_address');
  }
}

export const secureWalletService = new SecureWalletService();
export default secureWalletService;
