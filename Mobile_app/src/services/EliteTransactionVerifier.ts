// Two checks only — anything more is overengineering for Elite 15 monitoring.
// 1. Did the wallet SIGN the transaction? (Prevents airdrop false signals)
// 2. Did they SPEND at least $100?       (Ensures real conviction)

interface VerificationResult {
  valid: boolean;
  reason: string;
  message?: string;
  usdSpent?: number;
  token?: string | null;
  timestamp?: any;
}

interface Transfer {
  from: string;
  to: string;
  token: string;
  amount: number;
}

interface Transaction {
  signers?: string[];
  transfers?: Transfer[];
  timestamp?: any;
}

class EliteTransactionVerifier {
  private MIN_SPEND_USD: number;

  constructor() {
    this.MIN_SPEND_USD = 100;
  }

  async verifyEliteBuy(transaction: Transaction, walletAddress: string): Promise<VerificationResult> {
    console.log('\n🔍 Verifying Elite 15 transaction...');

    // ── CHECK 1: Did THEY sign it? ─────────────────────────────────────────────
    const isSigner = transaction.signers?.includes(walletAddress);
    if (!isSigner) {
      console.log('❌ FAIL: Wallet did NOT sign — this is an AIRDROP');
      return {
        valid: false,
        reason: 'airdrop',
        message: 'Wallet did not authorize this transaction'
      };
    }
    console.log('✅ Wallet SIGNED the transaction');

    // ── CHECK 2: Did they SPEND at least $100? ─────────────────────────────────
    const solSpent = this.calculateSolSpent(transaction, walletAddress);
    const usdSpent = solSpent * await this.getSolPrice();

    if (usdSpent < this.MIN_SPEND_USD) {
      console.log(`❌ FAIL: Only spent $${usdSpent.toFixed(2)} (need $${this.MIN_SPEND_USD})`);
      return {
        valid: false,
        reason: 'low_spend',
        message: `Only spent $${usdSpent.toFixed(2)} — minimum is $${this.MIN_SPEND_USD}`
      };
    }
    console.log(`✅ Wallet spent $${usdSpent.toFixed(2)}`);

    return {
      valid: true,
      reason: 'valid_buy',
      usdSpent,
      token: this.getTokenAddress(transaction),
      timestamp: transaction.timestamp
    };
  }

  calculateSolSpent(transaction: Transaction, walletAddress: string): number {
    let solSpent = 0;
    for (const transfer of transaction.transfers || []) {
      if (transfer.from === walletAddress && transfer.token === 'SOL' && transfer.amount > 0) {
        solSpent += transfer.amount;
      }
    }
    return solSpent;
  }

  async getSolPrice(): Promise<number> {
    try {
      const res = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd');
      const data = await res.json();
      return data.solana?.usd || 150;
    } catch {
      return 150; // Fallback
    }
  }

  getTokenAddress(transaction: Transaction): string | null {
    for (const transfer of transaction.transfers || []) {
      if (transfer.token !== 'SOL' && transfer.to === transaction.signers?.[0]) {
        return transfer.token;
      }
    }
    return null;
  }
}

export const eliteVerifier = new EliteTransactionVerifier();
export default eliteVerifier;
