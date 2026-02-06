import { useMemo, useCallback } from 'react';
import { ConnectionProvider, WalletProvider } from '@solana/wallet-adapter-react';
import { WalletModalProvider } from '@solana/wallet-adapter-react-ui';
import { WalletAdapterNetwork } from '@solana/wallet-adapter-base';
import { WalletConnectWalletAdapter } from '@solana/wallet-adapter-walletconnect';
import { clusterApiUrl } from '@solana/web3.js';

// Import default wallet adapter styles
import '@solana/wallet-adapter-react-ui/styles.css';

export function WalletContextProvider({ children }) {
  // Use mainnet for production
  const network = WalletAdapterNetwork.Mainnet;
  const endpoint = useMemo(() => clusterApiUrl(network), [network]);

  // Configure wallets
  // Note: Phantom, Solflare, Backpack, Coinbase, and other wallets that
  // support Wallet Standard are auto-detected and don't need explicit adapters
  const wallets = useMemo(
    () => [
      // WalletConnect for mobile/cross-device support
      new WalletConnectWalletAdapter({
        network,
        options: {
          relayUrl: 'wss://relay.walletconnect.com',
          // Get project ID from https://dashboard.reown.com
          projectId: import.meta.env.VITE_WALLETCONNECT_PROJECT_ID || '',
          metadata: {
            name: 'Sifter KYS',
            description: 'Sifter KYS - Token Analysis Tool',
            url: window.location.origin,
            icons: [`${window.location.origin}/icon.png`],
          },
        },
      }),
    ],
    [network]
  );

  // Error handler
  const onError = useCallback((error, adapter) => {
    console.error('Wallet error:', error.name, error.message);
    if (adapter) {
      console.error('Adapter:', adapter.name);
    }
  }, []);

  return (
    <ConnectionProvider endpoint={endpoint}>
      <WalletProvider
        wallets={wallets}
        onError={onError}
        autoConnect={true}
        localStorageKey="sifter_wallet_adapter"
      >
        <WalletModalProvider>
          {children}
        </WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
}
