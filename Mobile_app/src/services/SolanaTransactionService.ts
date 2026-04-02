import { Connection, VersionedTransaction, PublicKey, Keypair, LAMPORTS_PER_SOL } from '@solana/web3.js';
import bs58 from 'bs58';

// ─── Network Configuration ─────────────────────────────────────────────────────
// Supports mainnet and devnet. Call SolanaTransactionService.setNetwork('devnet')
// before any transactions to switch (e.g., for testing).

export type SolanaNetwork = 'mainnet-beta' | 'devnet';

interface NetworkConfig {
  rpcUrl: string;
  jupiterApi: string;
  jitoBlockEngine: string | null; // JITO not available on devnet
  jitoTipAccounts: string[];
}

const NETWORK_CONFIGS: Record<SolanaNetwork, NetworkConfig> = {
  'mainnet-beta': {
    rpcUrl: process.env.QUICKNODE_WSS?.replace('wss://', 'https://')
      || 'https://api.mainnet-beta.solana.com',
    // Jupiter unified API — v6 (quote-api.jup.ag/v6) is deprecated
    jupiterApi: 'https://api.jup.ag',
    jitoBlockEngine: 'https://mainnet.block-engine.jito.wtf',
    // Official JITO tip accounts — tips go to one of these to incentivize bundle inclusion
    jitoTipAccounts: [
      '96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5',
      'HFqU5x63VTqvQss8hp11i4bVqkfRtQ7NmXwkiY8qHaR9',
      'Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY',
      'ADaUMid9yfUytqMBgopwjb2DTLSacUFR4qmvKq2N6Hoo',
      'DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh',
      'ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt',
      'DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL',
      '3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT',
    ],
  },
  devnet: {
    rpcUrl: process.env.DEVNET_RPC_URL || 'https://api.devnet.solana.com',
    // Jupiter supports devnet via the same unified API
    jupiterApi: 'https://api.jup.ag',
    jitoBlockEngine: null, // JITO bundles are mainnet-only
    jitoTipAccounts: [],
  },
};

const SOL_MINT = 'So11111111111111111111111111111111111111112';

// Default fetch timeout (15 seconds)
const FETCH_TIMEOUT_MS = 15_000;

// ─── Custom Error Types ─────────────────────────────────────────────────────────

export class SwapError extends Error {
  code: SwapErrorCode;
  details?: any;

  constructor(code: SwapErrorCode, message: string, details?: any) {
    super(message);
    this.name = 'SwapError';
    this.code = code;
    this.details = details;
  }
}

export enum SwapErrorCode {
  SLIPPAGE_EXCEEDED = 'SLIPPAGE_EXCEEDED',
  INSUFFICIENT_BALANCE = 'INSUFFICIENT_BALANCE',
  TRANSACTION_EXPIRED = 'TRANSACTION_EXPIRED',
  RPC_ERROR = 'RPC_ERROR',
  JUPITER_QUOTE_FAILED = 'JUPITER_QUOTE_FAILED',
  JUPITER_SWAP_FAILED = 'JUPITER_SWAP_FAILED',
  JITO_BUNDLE_FAILED = 'JITO_BUNDLE_FAILED',
  SIMULATION_FAILED = 'SIMULATION_FAILED',
  CONFIRMATION_TIMEOUT = 'CONFIRMATION_TIMEOUT',
  UNKNOWN = 'UNKNOWN',
}

interface SwapResult {
  success: boolean;
  signature?: string;
  quote?: any;
  error?: string;
  errorCode?: SwapErrorCode;
}

interface SimulationResult {
  success: boolean;
  logs?: string[];
  error?: any;
}

interface MevProtectionResult {
  method: string;
  bundleId?: string;
  signature?: string;
}

// ─── Helpers ────────────────────────────────────────────────────────────────────

/** fetch() with an AbortController timeout */
async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs: number = FETCH_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/** Classify a raw error into a SwapErrorCode */
function classifyError(error: any): SwapErrorCode {
  const msg = (error?.message || error?.toString() || '').toLowerCase();

  if (msg.includes('slippage') || msg.includes('exceeds desired slippage') || msg.includes('slippage tolerance')) {
    return SwapErrorCode.SLIPPAGE_EXCEEDED;
  }
  if (msg.includes('insufficient') || msg.includes('not enough') || msg.includes('0x1') /* insufficient funds */) {
    return SwapErrorCode.INSUFFICIENT_BALANCE;
  }
  if (msg.includes('blockhash not found') || msg.includes('block height exceeded') || msg.includes('expired')) {
    return SwapErrorCode.TRANSACTION_EXPIRED;
  }
  if (msg.includes('timeout') || msg.includes('timed out') || msg.includes('aborted')) {
    return SwapErrorCode.CONFIRMATION_TIMEOUT;
  }
  if (msg.includes('simulation failed') || msg.includes('simulate')) {
    return SwapErrorCode.SIMULATION_FAILED;
  }
  if (msg.includes('rpc') || msg.includes('429') || msg.includes('503') || msg.includes('connection refused')) {
    return SwapErrorCode.RPC_ERROR;
  }
  return SwapErrorCode.UNKNOWN;
}

// ─── Service ────────────────────────────────────────────────────────────────────

class SolanaTransactionService {
  private connection: Connection;
  private network: SolanaNetwork;
  private config: NetworkConfig;

  constructor() {
    this.network = 'mainnet-beta';
    this.config = NETWORK_CONFIGS['mainnet-beta'];
    this.connection = new Connection(this.config.rpcUrl, 'confirmed');
  }

  // ─── Network Switching ──────────────────────────────────────────────────────

  /**
   * Switch between mainnet-beta and devnet.
   * Call this before any transactions when testing.
   */
  setNetwork(network: SolanaNetwork): void {
    this.network = network;
    this.config = NETWORK_CONFIGS[network];
    this.connection = new Connection(this.config.rpcUrl, 'confirmed');
    console.log(`[SolanaTransactionService] Switched to ${network} (RPC: ${this.config.rpcUrl})`);
  }

  getNetwork(): SolanaNetwork {
    return this.network;
  }

  isDevnet(): boolean {
    return this.network === 'devnet';
  }

  getConnection(): Connection {
    return this.connection;
  }

  // ─── Jupiter DEX Integration ───────────────────────────────────────────

  /**
   * Get a swap quote from Jupiter.
   */
  async getSwapQuote(inputMint: string, outputMint: string, amountLamports: number, slippageBps: number = 100): Promise<any> {
    const params = new URLSearchParams({
      inputMint,
      outputMint,
      amount: amountLamports.toString(),
      slippageBps: slippageBps.toString(),
      onlyDirectRoutes: 'false',
    });
    const res = await fetchWithTimeout(`${this.config.jupiterApi}/quote?${params}`);
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new SwapError(
        SwapErrorCode.JUPITER_QUOTE_FAILED,
        `Jupiter quote failed (${res.status}): ${body}`,
        { status: res.status, body }
      );
    }
    return res.json();
  }

  /**
   * Get serialized swap transaction from Jupiter.
   */
  async getSwapTransaction(quoteResponse: any, userPublicKey: PublicKey): Promise<any> {
    const res = await fetchWithTimeout(`${this.config.jupiterApi}/swap`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        quoteResponse,
        userPublicKey: userPublicKey.toString(),
        wrapAndUnwrapSol: true,
        dynamicComputeUnitLimit: true,
        prioritizationFeeLamports: 'auto',
      }),
    });
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new SwapError(
        SwapErrorCode.JUPITER_SWAP_FAILED,
        `Jupiter swap tx failed (${res.status}): ${body}`,
        { status: res.status, body }
      );
    }
    return res.json();
  }

  /**
   * Execute a token buy (SOL → Token) via Jupiter.
   */
  async buyToken(privateKeyBase58: string, tokenAddress: string, amountSol: number, slippageBps: number = 100): Promise<SwapResult> {
    let keypair: Keypair | null = null;
    try {
      keypair = Keypair.fromSecretKey(bs58.decode(privateKeyBase58));
      const amountLamports = Math.floor(amountSol * LAMPORTS_PER_SOL);

      // Pre-flight: check balance (amount + ~0.01 SOL buffer for fees)
      const balance = await this.connection.getBalance(keypair.publicKey);
      if (balance < amountLamports + 10_000_000) {
        return {
          success: false,
          error: `Insufficient SOL balance: have ${(balance / LAMPORTS_PER_SOL).toFixed(4)}, need ~${((amountLamports + 10_000_000) / LAMPORTS_PER_SOL).toFixed(4)}`,
          errorCode: SwapErrorCode.INSUFFICIENT_BALANCE,
        };
      }

      // 1. Get quote
      const quote = await this.getSwapQuote(SOL_MINT, tokenAddress, amountLamports, slippageBps);

      // 2. Get swap transaction
      const { swapTransaction } = await this.getSwapTransaction(quote, keypair.publicKey);

      // 3. Deserialize, sign, and send
      const txBuf = Buffer.from(swapTransaction, 'base64');
      const transaction = VersionedTransaction.deserialize(txBuf);
      transaction.sign([keypair]);

      // 4. Fetch blockhash BEFORE sending so we can confirm against it
      const { blockhash, lastValidBlockHeight } = await this.connection.getLatestBlockhash('confirmed');

      const signature = await this.connection.sendRawTransaction(transaction.serialize(), {
        skipPreflight: false,
        preflightCommitment: 'confirmed',
        maxRetries: 3,
      });

      // 5. Confirm
      const confirmation = await this.connection.confirmTransaction(
        { signature, blockhash, lastValidBlockHeight },
        'confirmed'
      );

      if (confirmation.value.err) {
        const errMsg = JSON.stringify(confirmation.value.err);
        return {
          success: false,
          signature,
          error: `Transaction confirmed with error: ${errMsg}`,
          errorCode: classifyError(new Error(errMsg)),
        };
      }

      return { success: true, signature, quote };
    } catch (error: any) {
      console.error('buyToken failed:', error);
      const code = error instanceof SwapError ? error.code : classifyError(error);
      return { success: false, error: error.message, errorCode: code };
    } finally {
      keypair = null;
    }
  }

  /**
   * Execute a token sell (Token → SOL) via Jupiter.
   */
  async sellToken(privateKeyBase58: string, tokenAddress: string, tokenAmount: number, slippageBps: number = 150): Promise<SwapResult> {
    let keypair: Keypair | null = null;
    try {
      keypair = Keypair.fromSecretKey(bs58.decode(privateKeyBase58));

      // Higher default slippage for sells (150 bps) — selling memecoins often
      // hits thin order books and needs more room than buying.
      const quote = await this.getSwapQuote(tokenAddress, SOL_MINT, tokenAmount, slippageBps);
      const { swapTransaction } = await this.getSwapTransaction(quote, keypair.publicKey);

      const txBuf = Buffer.from(swapTransaction, 'base64');
      const transaction = VersionedTransaction.deserialize(txBuf);
      transaction.sign([keypair]);

      // Fetch blockhash BEFORE sending so we can confirm against it
      const { blockhash, lastValidBlockHeight } = await this.connection.getLatestBlockhash('confirmed');

      const signature = await this.connection.sendRawTransaction(transaction.serialize(), {
        skipPreflight: false,
        preflightCommitment: 'confirmed',
        maxRetries: 3,
      });

      const confirmation = await this.connection.confirmTransaction(
        { signature, blockhash, lastValidBlockHeight },
        'confirmed'
      );

      if (confirmation.value.err) {
        const errMsg = JSON.stringify(confirmation.value.err);
        return {
          success: false,
          signature,
          error: `Transaction confirmed with error: ${errMsg}`,
          errorCode: classifyError(new Error(errMsg)),
        };
      }

      return { success: true, signature, quote };
    } catch (error: any) {
      console.error('sellToken failed:', error);
      const code = error instanceof SwapError ? error.code : classifyError(error);
      return { success: false, error: error.message, errorCode: code };
    } finally {
      keypair = null;
    }
  }

  /**
   * Legacy wrapper — delegates to buyToken.
   */
  async sendSwapTransaction(privateKeyBase58: string, tokenAddress: string, amountSol: number): Promise<SwapResult> {
    return this.buyToken(privateKeyBase58, tokenAddress, amountSol);
  }

  // ─── JITO MEV Protection ───────────────────────────────────────────────

  /**
   * Send transaction as a JITO bundle for MEV protection.
   * JITO expects base58-encoded transactions in the bundle params array.
   * Returns the bundle ID on success, or null to signal fallback to regular RPC.
   */
  async sendJitoBundle(serializedTransaction: Uint8Array): Promise<string | null> {
    // JITO is mainnet-only
    if (!this.config.jitoBlockEngine) {
      console.log('[JITO] Not available on devnet, skipping');
      return null;
    }

    try {
      // JITO expects base58-encoded transactions (not base64)
      const base58Tx = bs58.encode(serializedTransaction);

      const bundlePayload = {
        jsonrpc: '2.0',
        id: 1,
        method: 'sendBundle',
        params: [[base58Tx]],
      };

      const res = await fetchWithTimeout(`${this.config.jitoBlockEngine}/api/v1/bundles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bundlePayload),
      });

      if (!res.ok) {
        const body = await res.text().catch(() => '');
        console.warn(`[JITO] Bundle submission failed (${res.status}): ${body}`);
        return null;
      }

      const data = await res.json();

      if (data.error) {
        console.warn('[JITO] Bundle RPC error:', data.error);
        return null;
      }

      return data.result;
    } catch (error: any) {
      console.warn('[JITO] Bundle error:', error.message);
      return null;
    }
  }

  /**
   * Get a random JITO tip account address for including a tip instruction.
   * Returns null on devnet (no JITO support).
   */
  getJitoTipAccount(): string | null {
    const accounts = this.config.jitoTipAccounts;
    if (accounts.length === 0) return null;
    return accounts[Math.floor(Math.random() * accounts.length)];
  }

  /**
   * Send with MEV protection -- tries JITO first, falls back to regular RPC.
   */
  async sendWithMevProtection(serializedTransaction: Uint8Array): Promise<MevProtectionResult> {
    const bundleId = await this.sendJitoBundle(serializedTransaction);

    if (bundleId) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      return { method: 'jito', bundleId };
    }

    const signature = await this.connection.sendRawTransaction(serializedTransaction, {
      skipPreflight: false,
      preflightCommitment: 'confirmed',
      maxRetries: 3,
    });

    return { method: 'rpc', signature };
  }

  // ─── Utility Methods ───────────────────────────────────────────────────

  /**
   * Simulate a transaction before sending.
   */
  async simulateTransaction(transaction: any): Promise<SimulationResult> {
    try {
      const result = await this.connection.simulateTransaction(transaction);
      return {
        success: !result.value.err,
        logs: result.value.logs || undefined,
        error: result.value.err,
      };
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  }

  /**
   * Get SOL balance for a wallet.
   */
  async getBalance(publicKeyString: string): Promise<number> {
    try {
      const pubkey = new PublicKey(publicKeyString);
      const balance = await this.connection.getBalance(pubkey);
      return balance / LAMPORTS_PER_SOL;
    } catch {
      return 0;
    }
  }

  /**
   * Get recent transaction signatures for a wallet.
   */
  async getRecentTransactions(publicKeyString: string, limit: number = 10): Promise<any[]> {
    try {
      const pubkey = new PublicKey(publicKeyString);
      return await this.connection.getSignaturesForAddress(pubkey, { limit });
    } catch {
      return [];
    }
  }
}

export default new SolanaTransactionService();
