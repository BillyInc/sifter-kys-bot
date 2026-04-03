import notificationService from './NotificationService';
import { PublicKey, LAMPORTS_PER_SOL, VersionedTransaction } from '@solana/web3.js';
import DatabaseService from '../database/DatabaseService';
import SolanaTransactionService from './SolanaTransactionService';
// ─── Interfaces ───────────────────────────────────────────────────────────────

interface TokenSafety {
  safe: boolean;
  riskScore: number;
  reasons: string[];
  action: string;
}

interface SimulationResult {
  success: boolean;
  expectedOutput?: number;
  error?: string;
  logs?: string[];
}

interface ProtectionResult {
  success: boolean;
  reason?: string;
  details?: any;
  bundle?: any;
  executionPrice?: number;
  slippage?: number;
}

interface ProtectedBundle {
  tokenAddress: string;
  amount: number;
  slippage: number;
  gas: number;
  bundled: boolean;
  timestamp: number;
  /** Pre-fetched Jupiter quote for downstream execution. */
  quote?: any;
  /** Whether JITO MEV protection is available on the current network. */
  jitoAvailable: boolean;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const SOL_MINT = 'So11111111111111111111111111111111111111112';

/** Minimum liquidity (USD) to proceed with a trade. */
const MIN_LIQUIDITY_USD = 10_000;

/** Risk score threshold — trades with a score >= this are blocked. */
const RISK_THRESHOLD = 60;

// ─── Service ──────────────────────────────────────────────────────────────────

/**
 * Orchestrates all MEV / sniper protection layers before a trade is sent.
 *
 * Uses:
 * - Solana RPC (via SolanaTransactionService) for on-chain checks and simulation
 * - JITO bundle infrastructure (via SolanaTransactionService) for MEV protection
 * - Jupiter quote API for pre-trade simulation
 * - SolanaTracker API for liquidity and honeypot detection
 */
class UltimateProtection {

  // ── Main entry point ────────────────────────────────────────────────────────

  async protectTransaction(
    tokenAddress: string,
    amount: number,
    signal: any,
    extremeAnalysis: any,
  ): Promise<ProtectionResult> {
    console.log('\n🛡️ ULTIMATE PROTECTION ACTIVATED');

    // STEP 1: Pre-trade sniper / honeypot / rug-pull analysis
    const tokenSafety = await this.analyzeTokenBeforeBuy(tokenAddress, signal);
    if (!tokenSafety.safe) {
      console.log('❌ BLOCKED:', tokenSafety.reasons);
      return { success: false, reason: tokenSafety.action, details: tokenSafety };
    }

    // STEP 2: Simulate the swap transaction on-chain before committing real funds
    const simulation = await this.simulateTransaction(tokenAddress, amount, extremeAnalysis.slippage);
    if (!simulation.success) {
      console.log('❌ Simulation failed:', simulation.error);
      return { success: false, reason: 'SIMULATION_FAILED', details: simulation };
    }

    // STEP 3: Build a protected bundle backed by JITO infrastructure
    const bundle = await this.buildProtectedBundle(tokenAddress, amount, extremeAnalysis);

    console.log('✅ Protection complete — bundle ready');
    return {
      success: true,
      bundle,
      executionPrice: simulation.expectedOutput,
      slippage: extremeAnalysis.slippage,
    };
  }

  // ── STEP 1: Token Safety Analysis ───────────────────────────────────────────

  async analyzeTokenBeforeBuy(tokenAddress: string, _signal: any): Promise<TokenSafety> {
    try {
      const [liquidity, honeypot, mintInfo] = await Promise.all([
        this.checkLiquidity(tokenAddress),
        this.checkHoneypot(tokenAddress),
        this.checkMintAuthority(tokenAddress),
      ]);

      let riskScore = 0;
      const reasons: string[] = [];

      // Hard block: honeypot
      if (honeypot.isHoneypot) {
        return { safe: false, riskScore: 100, reasons: ['HONEYPOT DETECTED'], action: 'BLOCK - HONEYPOT' };
      }

      // Hard block: token account does not exist on-chain
      if (!mintInfo.exists) {
        return { safe: false, riskScore: 100, reasons: ['Token mint not found on-chain'], action: 'BLOCK - INVALID_TOKEN' };
      }

      // Mint authority still active — rug-pull risk
      if (!mintInfo.mintAuthorityRevoked) {
        riskScore += 30;
        reasons.push('Mint authority NOT revoked — supply inflation risk');
      }

      // Freeze authority active — tokens can be frozen
      if (mintInfo.freezeAuthorityActive) {
        riskScore += 20;
        reasons.push('Freeze authority active — tokens can be frozen');
      }

      // Liquidity checks
      if (!liquidity.locked) {
        riskScore += 35;
        reasons.push('Liquidity not locked');
      }

      if (liquidity.total < MIN_LIQUIDITY_USD) {
        riskScore += 40;
        reasons.push(`Very low liquidity: $${liquidity.total.toFixed(0)}`);
      }

      const isSafe = riskScore < RISK_THRESHOLD;
      return { safe: isSafe, riskScore, reasons, action: isSafe ? 'PROCEED' : 'BLOCK' };
    } catch (error: any) {
      console.warn('Token safety analysis error:', error.message);
      // Fail-open with a warning — a transient RPC error should not block every trade
      return { safe: true, riskScore: 0, reasons: ['Safety check unavailable — proceeding with caution'], action: 'PROCEED' };
    }
  }

  /**
   * Query on-chain mint account to verify the token exists and whether
   * mint / freeze authorities have been revoked.
   */
  private async checkMintAuthority(tokenAddress: string): Promise<{
    exists: boolean;
    mintAuthorityRevoked: boolean;
    freezeAuthorityActive: boolean;
  }> {
    try {
      const connection = SolanaTransactionService.getConnection();
      const mintPubkey = new PublicKey(tokenAddress);

      // getParsedAccountInfo returns parsed SPL token mint data
      const accountInfo = await connection.getParsedAccountInfo(mintPubkey);

      if (!accountInfo.value) {
        return { exists: false, mintAuthorityRevoked: false, freezeAuthorityActive: false };
      }

      const parsed = (accountInfo.value.data as any)?.parsed;
      if (!parsed || parsed.type !== 'mint') {
        // Account exists but is not a token mint
        return { exists: false, mintAuthorityRevoked: false, freezeAuthorityActive: false };
      }

      const info = parsed.info;
      return {
        exists: true,
        mintAuthorityRevoked: info.mintAuthority === null,
        freezeAuthorityActive: info.freezeAuthority !== null,
      };
    } catch {
      // If RPC fails, assume the worst for safety
      return { exists: true, mintAuthorityRevoked: false, freezeAuthorityActive: true };
    }
  }

  /**
   * Check liquidity via SolanaTracker API.
   */
  private async checkLiquidity(tokenAddress: string): Promise<{ total: number; locked: boolean; renounced: boolean }> {
    try {
      const res = await fetch(`https://api.solana-tracker.io/tokens/${tokenAddress}`);
      const data = await res.json();
      return {
        total: data.liquidity?.usd || 0,
        locked: data.lpLocked || false,
        renounced: data.mintAuthority === null,
      };
    } catch {
      return { total: 0, locked: false, renounced: false };
    }
  }

  /**
   * Check for honeypot characteristics via SolanaTracker security endpoint.
   */
  private async checkHoneypot(tokenAddress: string): Promise<{ isHoneypot: boolean }> {
    try {
      const res = await fetch(`https://api.solana-tracker.io/tokens/${tokenAddress}/security`);
      const data = await res.json();
      return { isHoneypot: data.honeypot || false };
    } catch {
      return { isHoneypot: false };
    }
  }

  // ── STEP 2: Transaction Simulation ──────────────────────────────────────────

  /**
   * Simulate the swap via Jupiter quote + Solana RPC `simulateTransaction`.
   *
   * Flow:
   * 1. Get a Jupiter quote (SOL -> token) to obtain the expected output amount.
   * 2. If a serialized swap transaction is available, simulate it against the
   *    RPC to catch on-chain failures (insufficient balance, program errors)
   *    before sending real funds.
   * 3. Fall back to quote-only validation if simulation RPC is unavailable.
   */
  async simulateTransaction(tokenAddress: string, amountSol: number, slippage: number): Promise<SimulationResult> {
    try {
      const amountLamports = Math.floor(amountSol * LAMPORTS_PER_SOL);
      const slippageBps = Math.round((slippage || 0.01) * 10_000);

      // 1. Get Jupiter quote — this validates the route exists and gives expected output
      const quote = await SolanaTransactionService.getSwapQuote(
        SOL_MINT,
        tokenAddress,
        amountLamports,
        slippageBps,
      );

      if (!quote || !quote.outAmount) {
        return { success: false, error: 'No swap route available on Jupiter' };
      }

      const expectedOutput = parseFloat(quote.outAmount);

      // 2. Attempt full on-chain simulation if we can build a transaction
      //    This requires a wallet public key — use a read-only approach by
      //    fetching the stored wallet address (not the private key).
      try {
        const walletAddress = await DatabaseService.getSetting('wallet_address');
        if (walletAddress) {
          const userPubkey = new PublicKey(walletAddress);
          const swapData = await SolanaTransactionService.getSwapTransaction(quote, userPubkey);

          if (swapData?.swapTransaction) {
            const txBuf = Buffer.from(swapData.swapTransaction, 'base64');
            const transaction = VersionedTransaction.deserialize(txBuf);

            const simResult = await SolanaTransactionService.simulateTransaction(transaction);

            if (!simResult.success) {
              return {
                success: false,
                error: `On-chain simulation failed: ${JSON.stringify(simResult.error)}`,
                logs: simResult.logs,
              };
            }

            return { success: true, expectedOutput, logs: simResult.logs };
          }
        }
      } catch (simError: any) {
        // Simulation RPC error is non-fatal — fall through to quote-only check
        console.warn('On-chain simulation unavailable, using quote-only validation:', simError.message);
      }

      // 3. Quote-only validation passed (route exists, output is non-zero)
      return { success: true, expectedOutput };
    } catch (error: any) {
      return { success: false, error: `Simulation error: ${error.message}` };
    }
  }

  /**
   * Simulate an already-built Transaction object via direct RPC.
   * Use this when you have a full transaction (e.g., from Jupiter SDK).
   */
  async simulateRawTransaction(transaction: any): Promise<any> {
    return SolanaTransactionService.simulateTransaction(transaction);
  }

  // ── STEP 3: Protected Bundle ────────────────────────────────────────────────

  /**
   * Build a protected bundle descriptor that downstream execution
   * (FortifiedAutoTrader.sendProtectedBundle) will use.
   *
   * On mainnet: signals that the trade should be routed through JITO for
   * MEV protection. The JITO tip account is selected here so the executor
   * can include a tip instruction if desired.
   *
   * On devnet: JITO is unavailable, so `jitoAvailable` is false and the
   * executor will fall back to standard RPC submission.
   */
  async buildProtectedBundle(
    tokenAddress: string,
    amount: number,
    extremeAnalysis: any,
  ): Promise<ProtectedBundle> {
    // Pre-fetch a Jupiter quote so downstream execution can skip the quote step
    // if the bundle is consumed quickly (within the same blockhash window).
    let quote: any = null;
    try {
      const amountLamports = Math.floor(amount * LAMPORTS_PER_SOL);
      const slippageBps = Math.round((extremeAnalysis.slippage || 0.01) * 10_000);
      quote = await SolanaTransactionService.getSwapQuote(
        SOL_MINT,
        tokenAddress,
        amountLamports,
        slippageBps,
      );
    } catch (err: any) {
      // Non-fatal — the executor will re-fetch if needed
      console.warn('Pre-fetch quote for bundle failed:', err.message);
    }

    const jitoTipAccount = SolanaTransactionService.getJitoTipAccount();

    return {
      tokenAddress,
      amount,
      slippage: extremeAnalysis.slippage,
      gas: extremeAnalysis.gas,
      bundled: true,
      timestamp: Date.now(),
      quote,
      jitoAvailable: jitoTipAccount !== null,
    };
  }

  // ── Post-Trade Analysis ─────────────────────────────────────────────────────

  /**
   * Analyze a completed trade for sandwich attacks and other MEV extraction.
   * Uses Helius enhanced transaction API when available, falls back gracefully.
   */
  async analyzeTradeAfterExecution(txHash: string, tokenAddress: string): Promise<any[]> {
    console.log('Post-trade analysis...');
    try {
      const apiKey = await DatabaseService.getSetting('api_key_helius');

      // Try Helius enhanced transaction API first
      if (apiKey) {
        const res = await fetch(
          `https://api.helius.xyz/v0/transactions/${txHash}`,
          { headers: { 'Authorization': `Bearer ${apiKey}` } },
        );
        if (res.ok) {
          const tx = await res.json();
          return this.extractSniperData(tx, txHash, tokenAddress);
        }
      }

      // Fallback: inspect surrounding transactions via Solana RPC
      // Look at the block for potential sandwich patterns
      const connection = SolanaTransactionService.getConnection();
      const txInfo = await connection.getTransaction(txHash, {
        maxSupportedTransactionVersion: 0,
      });

      if (!txInfo?.slot) return [];

      // Get the block to look for sandwich patterns
      const block = await connection.getBlock(txInfo.slot, {
        maxSupportedTransactionVersion: 0,
        transactionDetails: 'signatures',
      });

      if (!block) return [];

      // Find our transaction's position in the block
      const txIndex = block.signatures.indexOf(txHash);
      if (txIndex < 0) return [];

      // Simple sandwich detection: if the same account transacted immediately
      // before and after ours, that is suspicious.
      const snipers: any[] = [];
      if (txIndex > 0 && txIndex < block.signatures.length - 1) {
        const beforeSig = block.signatures[txIndex - 1];
        const afterSig = block.signatures[txIndex + 1];

        const [beforeTx, afterTx] = await Promise.all([
          connection.getTransaction(beforeSig, { maxSupportedTransactionVersion: 0 }),
          connection.getTransaction(afterSig, { maxSupportedTransactionVersion: 0 }),
        ]);

        if (beforeTx && afterTx) {
          const beforeAccounts = beforeTx.transaction.message.getAccountKeys().keySegments().flat().map(k => k.toString());
          const afterAccounts = afterTx.transaction.message.getAccountKeys().keySegments().flat().map(k => k.toString());

          // Accounts appearing in both adjacent transactions (excluding system programs)
          const suspicious = beforeAccounts.filter(
            (a: string) => afterAccounts.includes(a) && !a.startsWith('11111111') && !a.startsWith('Token'),
          );

          for (const wallet of suspicious) {
            snipers.push({ wallet, type: 'POTENTIAL_SANDWICH' });
            await DatabaseService.addToSniperBlacklist(wallet, 'POTENTIAL_SANDWICH', txHash, tokenAddress);
          }
        }
      }

      if (snipers.length > 0) {
        notificationService.showSecurityAlert(`${snipers.length} wallet(s) attempted to sandwich your trade`);
      }

      return snipers;
    } catch (error: any) {
      console.warn('Post-trade analysis failed:', error.message);
      return [];
    }
  }

  /**
   * Extract sniper/sandwich data from a Helius enhanced transaction response.
   */
  private async extractSniperData(tx: any, txHash: string, tokenAddress: string): Promise<any[]> {
    const snipers: any[] = [];

    if (tx.sandwichDetected) {
      for (const attacker of tx.attackers || []) {
        snipers.push({ wallet: attacker.wallet, type: 'SANDWICH' });
        await DatabaseService.addToSniperBlacklist(attacker.wallet, 'SANDWICH', txHash, tokenAddress);
      }
    }

    if (snipers.length > 0) {
      notificationService.showSecurityAlert(`${snipers.length} wallet(s) attempted to sandwich your trade`);
    }

    return snipers;
  }
}

export const ultimateProtection = new UltimateProtection();
export default ultimateProtection;
