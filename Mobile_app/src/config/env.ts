/**
 * Centralized environment configuration for the mobile app.
 *
 * Reads from process.env (populated via .env / Expo Constants) and
 * provides sensible production defaults so the app works out of the box.
 */

import type { SolanaNetwork } from '../services/SolanaTransactionService';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function envBool(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined || value === '') return fallback;
  return value === 'true' || value === '1';
}

// ---------------------------------------------------------------------------
// Exported config
// ---------------------------------------------------------------------------

export const config = {
  /** Base URL for the KYS backend API. */
  API_URL: process.env.API_BASE_URL || 'https://sifter-kys.duckdns.org',

  /** Solana network: 'mainnet-beta' or 'devnet'. */
  NETWORK: (process.env.SOLANA_NETWORK || 'mainnet-beta') as SolanaNetwork,

  /** When true, the app starts in devnet mode (overrides NETWORK to 'devnet'). */
  DEVNET_MODE: envBool(process.env.DEVNET_MODE, false),

  /** QuickNode WebSocket endpoint (optional, used for mainnet RPC). */
  QUICKNODE_WSS: process.env.QUICKNODE_WSS || '',

  /** Devnet RPC URL override. */
  DEVNET_RPC_URL: process.env.DEVNET_RPC_URL || '',
} as const;

/**
 * Resolved Solana network — if DEVNET_MODE is enabled it takes precedence
 * over the NETWORK value.
 */
export function resolvedNetwork(): SolanaNetwork {
  return config.DEVNET_MODE ? 'devnet' : config.NETWORK;
}

export default config;
