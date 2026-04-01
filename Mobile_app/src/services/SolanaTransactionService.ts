import { Connection, VersionedTransaction, PublicKey, Keypair, LAMPORTS_PER_SOL } from '@solana/web3.js';
import bs58 from 'bs58';

// Prefer QuickNode WSS env var (converted to HTTPS), fall back to public RPC
const RPC_URL = process.env.QUICKNODE_WSS?.replace('wss://', 'https://')
  || 'https://api.mainnet-beta.solana.com';

const JUPITER_API = 'https://quote-api.jup.ag/v6';
const SOL_MINT = 'So11111111111111111111111111111111111111112';

// JITO block engine for MEV-protected bundle submission
const JITO_BLOCK_ENGINE = 'https://mainnet.block-engine.jito.wtf';

interface SwapResult {
  success: boolean;
  signature?: string;
  quote?: any;
  error?: string;
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

class SolanaTransactionService {
  private connection: Connection;

  constructor() {
    this.connection = new Connection(RPC_URL, 'confirmed');
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
    const res = await fetch(`${JUPITER_API}/quote?${params}`);
    if (!res.ok) throw new Error(`Jupiter quote failed: ${res.status}`);
    return res.json();
  }

  /**
   * Get serialized swap transaction from Jupiter.
   */
  async getSwapTransaction(quoteResponse: any, userPublicKey: PublicKey): Promise<any> {
    const res = await fetch(`${JUPITER_API}/swap`, {
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
    if (!res.ok) throw new Error(`Jupiter swap failed: ${res.status}`);
    return res.json();
  }

  /**
   * Execute a token buy (SOL → Token) via Jupiter.
   */
  async buyToken(privateKeyBase58: string, tokenAddress: string, amountSol: number): Promise<SwapResult> {
    let keypair: Keypair | null = null;
    try {
      keypair = Keypair.fromSecretKey(bs58.decode(privateKeyBase58));
      const amountLamports = Math.floor(amountSol * LAMPORTS_PER_SOL);

      // 1. Get quote
      const quote = await this.getSwapQuote(SOL_MINT, tokenAddress, amountLamports);

      // 2. Get swap transaction
      const { swapTransaction } = await this.getSwapTransaction(quote, keypair.publicKey);

      // 3. Deserialize, sign, and send
      const txBuf = Buffer.from(swapTransaction, 'base64');
      const transaction = VersionedTransaction.deserialize(txBuf);
      transaction.sign([keypair]);

      const signature = await this.connection.sendRawTransaction(transaction.serialize(), {
        skipPreflight: false,
        preflightCommitment: 'confirmed',
        maxRetries: 3,
      });

      // 4. Confirm
      const { blockhash, lastValidBlockHeight } = await this.connection.getLatestBlockhash();
      await this.connection.confirmTransaction({ signature, blockhash, lastValidBlockHeight }, 'confirmed');

      return { success: true, signature, quote };
    } catch (error: any) {
      console.error('buyToken failed:', error);
      return { success: false, error: error.message };
    } finally {
      keypair = null;
    }
  }

  /**
   * Execute a token sell (Token → SOL) via Jupiter.
   */
  async sellToken(privateKeyBase58: string, tokenAddress: string, tokenAmount: number): Promise<SwapResult> {
    let keypair: Keypair | null = null;
    try {
      keypair = Keypair.fromSecretKey(bs58.decode(privateKeyBase58));

      const quote = await this.getSwapQuote(tokenAddress, SOL_MINT, tokenAmount);
      const { swapTransaction } = await this.getSwapTransaction(quote, keypair.publicKey);

      const txBuf = Buffer.from(swapTransaction, 'base64');
      const transaction = VersionedTransaction.deserialize(txBuf);
      transaction.sign([keypair]);

      const signature = await this.connection.sendRawTransaction(transaction.serialize(), {
        skipPreflight: false,
        preflightCommitment: 'confirmed',
        maxRetries: 3,
      });

      const { blockhash, lastValidBlockHeight } = await this.connection.getLatestBlockhash();
      await this.connection.confirmTransaction({ signature, blockhash, lastValidBlockHeight }, 'confirmed');

      return { success: true, signature, quote };
    } catch (error: any) {
      console.error('sellToken failed:', error);
      return { success: false, error: error.message };
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
   */
  async sendJitoBundle(serializedTransaction: Uint8Array): Promise<string | null> {
    try {
      const bundlePayload = {
        jsonrpc: '2.0',
        id: 1,
        method: 'sendBundle',
        params: [[
          Buffer.from(serializedTransaction).toString('base64')
        ]],
      };

      const res = await fetch(`${JITO_BLOCK_ENGINE}/api/v1/bundles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bundlePayload),
      });

      if (!res.ok) {
        console.warn('JITO bundle failed, falling back to regular RPC');
        return null;
      }

      const data = await res.json();
      return data.result;
    } catch (error: any) {
      console.warn('JITO bundle error:', error.message);
      return null;
    }
  }

  /**
   * Send with MEV protection — tries JITO first, falls back to regular RPC.
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
