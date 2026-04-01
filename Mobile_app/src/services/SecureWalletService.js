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
    console.log(`Biometric available: ${this.biometricAvailable}`);
  }

  async storeWallet(privateKey, walletAddress) {
    // Store full key in SecureStore with hardware-backed protection
    await SecureStore.setItemAsync('wallet_key', privateKey, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      requireAuthentication: true,  // Require biometric to access
    });
    await SecureStore.setItemAsync('wallet_address', walletAddress);
    console.log('Wallet stored securely');
  }

  async retrieveWallet() {
    const auth = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Authenticate to trade',
      disableDeviceFallback: false
    });
    if (!auth.success) throw new Error('Authentication failed');

    const privateKey = await SecureStore.getItemAsync('wallet_key', {
      requireAuthentication: true,
    });
    if (!privateKey) throw new Error('Wallet not found');

    const address = await SecureStore.getItemAsync('wallet_address');
    return { privateKey, address };
  }

  async deleteWallet() {
    await SecureStore.deleteItemAsync('wallet_key');
    await SecureStore.deleteItemAsync('wallet_address');
  }
}

export const secureWalletService = new SecureWalletService();
export default secureWalletService;
