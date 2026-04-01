import * as SecureStore from 'expo-secure-store';
import * as LocalAuthentication from 'expo-local-authentication';

interface WalletData {
  privateKey: string;
  address: string;
}

class SecureWalletService {
  private biometricAvailable: boolean;

  constructor() {
    this.biometricAvailable = false;
  }

  async init(): Promise<void> {
    const compatible = await LocalAuthentication.hasHardwareAsync();
    const enrolled = await LocalAuthentication.isEnrolledAsync();
    this.biometricAvailable = compatible && enrolled;
    if (__DEV__) console.log(`Biometric available: ${this.biometricAvailable}`);
  }

  async storeWallet(privateKey: string, walletAddress: string): Promise<void> {
    // Store full key in SecureStore with hardware-backed protection
    await SecureStore.setItemAsync('wallet_key', privateKey, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      requireAuthentication: true,  // Require biometric to access
    } as any);
    await SecureStore.setItemAsync('wallet_address', walletAddress);
    console.log('Wallet stored securely');
  }

  async retrieveWallet(): Promise<WalletData> {
    const auth = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Authenticate to trade',
      disableDeviceFallback: false
    });
    if (!auth.success) throw new Error('Authentication failed');

    const privateKey = await SecureStore.getItemAsync('wallet_key', {
      requireAuthentication: true,
    } as any);
    if (!privateKey) throw new Error('Wallet not found');

    const address = await SecureStore.getItemAsync('wallet_address');
    return { privateKey, address: address || '' };
  }

  async deleteWallet(): Promise<void> {
    await SecureStore.deleteItemAsync('wallet_key');
    await SecureStore.deleteItemAsync('wallet_address');
  }
}

export const secureWalletService = new SecureWalletService();
export default secureWalletService;
