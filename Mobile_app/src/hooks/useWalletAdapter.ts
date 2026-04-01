import { transact, Web3MobileWallet } from '@solana-mobile/mobile-wallet-adapter-protocol-web3js';
import { Connection, PublicKey, Transaction, VersionedTransaction } from '@solana/web3.js';
import { useCallback, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

const APP_IDENTITY = {
  name: 'Sifter KYS',
  uri: 'https://sifter-kys-web.duckdns.org',
};

const RPC_URL = process.env.QUICKNODE_WSS?.replace('wss://', 'https://') || 'https://api.mainnet-beta.solana.com';

export function useWalletAdapter() {
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);

  const connect = useCallback(async (cluster: string = 'mainnet-beta') => {
    setIsConnecting(true);
    try {
      const result = await transact(async (wallet: Web3MobileWallet) => {
        const authResult = await wallet.authorize({
          cluster: `solana:${cluster}`,
          identity: APP_IDENTITY,
        });
        return authResult;
      });

      const address = new PublicKey(result.accounts[0].address).toBase58();
      setWalletAddress(address);
      setAuthToken(result.auth_token);

      // Persist
      await AsyncStorage.setItem('wallet_address', address);
      await AsyncStorage.setItem('wallet_auth_token', result.auth_token);
      await AsyncStorage.setItem('wallet_type', 'mobile-adapter');

      return { address, authToken: result.auth_token };
    } catch (error: any) {
      throw error;
    } finally {
      setIsConnecting(false);
    }
  }, []);

  const signAndSendTransaction = useCallback(async (transaction: Transaction | VersionedTransaction) => {
    if (!authToken) throw new Error('Wallet not connected');

    const connection = new Connection(RPC_URL, 'confirmed');

    return await transact(async (wallet: Web3MobileWallet) => {
      await wallet.authorize({
        cluster: 'solana:mainnet-beta',
        identity: APP_IDENTITY,
        auth_token: authToken,
      });

      const signedTxs = await wallet.signTransactions([transaction as any]);
      const signature = await connection.sendRawTransaction(signedTxs[0].serialize());
      await connection.confirmTransaction(signature, 'confirmed');
      return signature;
    });
  }, [authToken]);

  const disconnect = useCallback(async () => {
    setWalletAddress(null);
    setAuthToken(null);
    await AsyncStorage.multiRemove(['wallet_address', 'wallet_auth_token', 'wallet_type']);
  }, []);

  // Load persisted state on init
  const loadPersistedWallet = useCallback(async () => {
    const address = await AsyncStorage.getItem('wallet_address');
    const token = await AsyncStorage.getItem('wallet_auth_token');
    if (address && token) {
      setWalletAddress(address);
      setAuthToken(token);
    }
  }, []);

  return {
    walletAddress,
    isConnecting,
    isConnected: !!walletAddress,
    connect,
    disconnect,
    signAndSendTransaction,
    loadPersistedWallet,
  };
}
