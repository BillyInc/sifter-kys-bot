import { Connection, Transaction, PublicKey, Keypair, LAMPORTS_PER_SOL } from '@solana/web3.js';
import bs58 from 'bs58';

// Prefer QuickNode WSS env var (converted to HTTPS), fall back to public RPC
const RPC_URL = process.env.QUICKNODE_WSS?.replace('wss://', 'https://')
  || 'https://api.mainnet-beta.solana.com';

class SolanaTransactionService {
  constructor() {
    this.connection = new Connection(RPC_URL, 'confirmed');
  }

  /**
   * Send a token swap transaction.
   *
   * TODO: Replace placeholder with real DEX swap instructions.
   *       - Jupiter: https://station.jup.ag/docs/apis/swap-api
   *       - Raydium: https://docs.raydium.io/raydium/
   *       The current implementation builds an empty transaction as a
   *       structural foundation. Actual swap logic (route fetching,
   *       instruction building) depends on the chosen DEX aggregator.
   */
  async sendSwapTransaction(privateKeyBase58, tokenAddress, amountSol) {
    try {
      const keypair = Keypair.fromSecretKey(bs58.decode(privateKeyBase58));

      // Get recent blockhash
      const { blockhash, lastValidBlockHeight } = await this.connection.getLatestBlockhash();

      // TODO: Build real swap instruction via Jupiter/Raydium SDK here.
      // The transaction object is ready to receive swap instructions.
      const transaction = new Transaction({
        recentBlockhash: blockhash,
        feePayer: keypair.publicKey,
      });

      // Sign and send
      transaction.sign(keypair);
      const signature = await this.connection.sendRawTransaction(
        transaction.serialize(),
        { skipPreflight: false, preflightCommitment: 'confirmed' }
      );

      // Confirm with blockhash-based strategy
      await this.connection.confirmTransaction({
        signature, blockhash, lastValidBlockHeight
      }, 'confirmed');

      return { success: true, signature };
    } catch (error) {
      console.error('SolanaTransactionService.sendSwapTransaction failed:', error);
      return { success: false, error: error.message };
    }
  }

  /**
   * Simulate a transaction before sending (MEV / pre-flight check).
   */
  async simulateTransaction(transaction) {
    try {
      const result = await this.connection.simulateTransaction(transaction);
      return {
        success: !result.value.err,
        logs: result.value.logs,
        error: result.value.err,
      };
    } catch (error) {
      console.error('SolanaTransactionService.simulateTransaction failed:', error);
      return { success: false, error: error.message };
    }
  }

  /**
   * Get SOL balance for a wallet.
   */
  async getBalance(publicKeyString) {
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
  async getRecentTransactions(publicKeyString, limit = 10) {
    try {
      const pubkey = new PublicKey(publicKeyString);
      const signatures = await this.connection.getSignaturesForAddress(pubkey, { limit });
      return signatures;
    } catch {
      return [];
    }
  }
}

export default new SolanaTransactionService();
