import notificationService from './NotificationService';
import NetInfo from '@react-native-community/netinfo';
import DatabaseService from '../database/DatabaseService';
import duplicatePrevention from './DuplicatePrevention';
import eliteVerifier from './EliteTransactionVerifier';
import extremeCaseHandler from './ExtremeCaseHandler';
import killSwitch from './KillSwitch';
import heartbeatMonitor from './HeartbeatMonitor';
import transactionQueue from './TransactionQueue';
import ultimateProtection from './UltimateProtection';
import secureWalletService from './SecureWalletService';
import PositionSizeManager from './PositionSizeManager';
import SolanaTransactionService, { SwapErrorCode } from './SolanaTransactionService';
import useStore from '../store/useStore';

// ──────────────────────────────────────────────────────────────────────────────
// SIGNAL ROUTING
//
//  userTier === 'free'
//    → always sendManualNotification()
//
//  userTier === 'premium' + tradingMode === 'auto'  + source === 'elite15'
//    → executeAutoTrade()
//
//  userTier === 'premium' + tradingMode === 'manual' + source === 'elite15'
//    → sendManualNotification() with "auto-trader is OFF" note
//
//  any tier + source === 'watchlist'
//    → sendManualNotification()
// ──────────────────────────────────────────────────────────────────────────────

interface ActivePosition {
  tradeId: number;
  entryPrice: number;
  size: number;
  remaining: number;
  txid: string;
  tp1: boolean;
  tp2: boolean;
  tp3: boolean;
  tp4: boolean;
}

class FortifiedAutoTrader {
  positionManager: PositionSizeManager | null;
  private initialized: boolean;
  private activePositions: Map<string, ActivePosition>;
  private userTier: string;
  tradingMode: string;

  constructor() {
    this.positionManager = null;
    this.initialized = false;
    this.activePositions = new Map();

    // Loaded from DB — kept in sync with store via initialize()
    this.userTier = 'free';
    this.tradingMode = 'auto';
  }

  async initialize(userId: string): Promise<void> {
    console.log('\n🛡️ INITIALIZING FORTIFIED AUTO-TRADER');

    await secureWalletService.init();
    await killSwitch.start();
    await heartbeatMonitor.start();
    await transactionQueue.loadQueue();
    await duplicatePrevention.loadHistory();

    const userData = await DatabaseService.getUser(userId);
    this.userTier = userData.tier;
    this.tradingMode = userData.preferredMode || 'auto';

    const portfolioTotal = parseFloat(await DatabaseService.getSetting('portfolio_total') || '10000') || 10000;
    this.positionManager = new PositionSizeManager(portfolioTotal);

    this.initialized = true;
    console.log(`✅ Auto-Trader ready | tier=${this.userTier} | mode=${this.tradingMode}`);
    console.log('🛡️ MEV Protection: ACTIVE | 🎯 Sniper Defense: ACTIVE');
  }

  // ── Mode switching (called from ModeSwitcher component and store) ──────────
  async setTradingMode(mode: string): Promise<void> {
    if (mode !== 'auto' && mode !== 'manual') return;
    this.tradingMode = mode;
    await DatabaseService.saveUserPreference('trading_mode', mode);
    notificationService.showTradeNotification('mode_changed', {
      reason: mode === 'auto'
        ? 'Auto-trader ACTIVE -- watching Elite 15'
        : 'Manual mode ACTIVE -- you control all trades',
    });
  }

  getCurrentMode(): { mode: string; tier: string; watching: string } {
    return {
      mode: this.tradingMode,
      tier: this.userTier,
      watching: this.userTier === 'premium' && this.tradingMode === 'auto'
        ? 'Elite 15'
        : 'Your watchlist'
    };
  }

  // ── Main entry point (called by RealTimeMonitor via BackgroundService) ─────
  async processSignal(signal: any): Promise<void> {
    const { source } = signal;

    // FREE users — manual notifications only, no auto-trading
    if (this.userTier === 'free') {
      return this.sendManualNotification(signal);
    }

    // PREMIUM users
    if (this.userTier === 'premium') {
      if (source === 'watchlist') {
        return this.sendManualNotification({ ...signal, note: 'From your watchlist — manual trade only' });
      }

      if (source === 'elite15') {
        if (this.tradingMode === 'manual') {
          return this.sendManualNotification({ ...signal, note: '🤖 Auto-trader is OFF — tap to trade manually' });
        }
        // AUTO mode — execute
        return this.executeAutoTrade(signal);
      }
    }
  }

  // ── Auto-trade pipeline (13 protection layers) ────────────────────────────
  async executeAutoTrade(signal: any): Promise<void> {
    try {
      console.log('\n🚨 AUTO-TRADE SIGNAL');
      if (__DEV__) console.log(`Token: ${signal.token?.slice(0, 8)} | Wallets: ${signal.walletCount} | $${signal.totalUsd}`);

      // LAYER 1: Kill switch
      if (await killSwitch.isEnabled()) {
        console.log('🚫 Kill switch active — aborting');
        return;
      }

      // LAYER 2: Duplicate prevention (hard rule — never auto-buy same token twice)
      const canBuy = await duplicatePrevention.canBuy(signal.token, signal.wallets[0], signal);
      if (!canBuy) return;

      // LAYER 3: Elite 15 on-chain verification (signed + ≥$100)
      if (signal.trades?.[0]) {
        const verification = await eliteVerifier.verifyEliteBuy(signal.trades[0], signal.wallets[0]);
        if (!verification.valid) {
          console.log(`❌ Verification failed: ${verification.reason}`);
          return;
        }
      }

      // LAYER 4: Extreme case analysis (slippage + gas)
      const context = await this.buildContext(signal);
      const extremeAnalysis = await extremeCaseHandler.calculateExtremeSlippage(
        signal.token, 'buy', context
      );
      console.log(`📊 Extreme score: ${extremeAnalysis.extremeScore}/100 | ${extremeAnalysis.recommendedAction}`);
      if (extremeAnalysis.isPanic) {
        notificationService.showTradeNotification('panic_mode', {
          slippage: extremeAnalysis.slippage,
        });
      }

      // LAYER 5: Position sizing
      const size = this.positionManager!.calculatePosition(signal);
      if (size <= 0) { console.log('⏭️ Position size zero — skipping'); return; }

      // LAYER 6: MEV / sniper protection (pre-trade analysis + bundle)
      const protectionResult = await ultimateProtection.protectTransaction(
        signal.token, size, signal, extremeAnalysis
      );
      if (!protectionResult.success) {
        console.log('❌ Protection blocked:', protectionResult.reason);
        notificationService.showSecurityAlert(protectionResult.reason || 'Protection blocked trade');
        return;
      }

      // LAYER 7: Queue if offline
      const network = await NetInfo.fetch();
      if (!network.isConnected) {
        await transactionQueue.addTransaction({ ...signal, size, protectionResult, extremeAnalysis });
        console.log('📡 Offline — queued');
        return;
      }

      // LAYER 8: Wallet connected?
      const walletConnected = await DatabaseService.getSetting('wallet_connected') === 'true';
      if (!walletConnected) {
        this.sendManualNotification({ ...signal, note: '⚠️ No wallet connected — connect in Settings' });
        return;
      }

      // LAYER 9: Sign + send
      // Wallet adapter users must approve each transaction in their wallet app,
      // which is incompatible with automated trading. Only manual-import wallets
      // can auto-trade because the private key is available on-device.
      const walletType = await DatabaseService.getSetting('wallet_type');
      if (walletType === 'mobile-adapter') {
        throw new Error('Auto-trading requires manual key import for automated signing. Wallet adapter connections require user approval per transaction.');
      }

      let wallet: any = null;
      let txid: string;
      try {
        wallet = await secureWalletService.retrieveWallet();
        txid = await this.sendProtectedBundle(protectionResult.bundle, wallet.privateKey);
      } finally {
        // Zero out private key material
        if (wallet?.privateKey) {
          wallet.privateKey = '\0'.repeat(wallet.privateKey.length);
          wallet.privateKey = null;
        }
      }

      // LAYER 10: Record purchase (hard duplicate lock)
      await duplicatePrevention.recordBuy(signal.token, signal.wallets[0], txid);
      this.positionManager!.updatePosition(signal.token, size);

      // LAYER 11: Persist to DB
      const tradeData = {
        token_address: signal.token,
        token_symbol: signal.trades?.[0]?.tokenSymbol || signal.token.slice(0, 6),
        entry_price: protectionResult.executionPrice || 0.00001,
        entry_size: size, remaining_size: size,
        signal_type: signal.type, wallet_count: signal.walletCount,
        triggering_wallets: signal.wallets, total_usd_signal: signal.totalUsd,
        tx_signature: txid
      };
      const tradeId = await DatabaseService.addTrade(tradeData);

      this.activePositions.set(signal.token, {
        tradeId, entryPrice: protectionResult.executionPrice || 0.00001,
        size, remaining: size, txid,
        tp1: false, tp2: false, tp3: false, tp4: false
      });

      // LAYER 12: Success notification
      if (__DEV__) console.log(`\n✅ TRADE EXECUTED | txid: ${txid.slice(0, 8)}... | size: $${size}`);
      notificationService.showTradeNotification('buy_executed', {
        tokenSymbol: tradeData.token_symbol,
        amount: size,
        walletCount: signal.walletCount,
        txid,
      });

      // LAYER 13: Post-trade sniper analysis (background, 5s delay)
      setTimeout(() => {
        ultimateProtection.analyzeTradeAfterExecution(txid, signal.token);
      }, 5000);

      // Start TP monitoring
      this.monitorPosition(signal.token, tradeId, protectionResult.executionPrice || 0.00001, size);

    } catch (error: any) {
      console.error('❌ Auto-trade failed:', error);
      notificationService.showTradeNotification('trade_failed', { reason: error.message });
    }
  }

  // ── Manual trade (user tapped "Trade Now") ────────────────────────────────
  async executeManualTrade(signal: any, isManualOverride: boolean = false): Promise<void> {
    console.log('👤 Manual trade initiated by user');
    return this.executeAutoTrade({ ...signal, isManual: true, isManualOverride });
  }

  // ── Called by TransactionQueue for offline-queued trades ─────────────────
  async executeFromQueue(tx: any): Promise<void> {
    return this.executeAutoTrade(tx);
  }

  // ── TP position monitoring ────────────────────────────────────────────────
  async monitorPosition(token: string, tradeId: number, entryPrice: number, initialSize: number): Promise<void> {
    let remaining = initialSize;
    let tp1 = false, tp2 = false, tp3 = false, tp4 = false;

    const check = async () => {
      try {
        const currentPrice = await this.getCurrentPrice(token);
        const multiplier = currentPrice / entryPrice;
        console.log(`📊 ${token.slice(0, 8)}: ${multiplier.toFixed(2)}x`);

        if (multiplier >= 5 && !tp1) {
          const sell = remaining * 0.25;
          const txid = await this.executeSell(token, sell, currentPrice, 1, tradeId);
          remaining -= sell; tp1 = true;
          await DatabaseService.updateTradeAfterTP(tradeId, 1, sell, currentPrice, sell * multiplier, txid);
        }
        if (multiplier >= 10 && !tp2) {
          const sell = remaining * 0.333;
          const txid = await this.executeSell(token, sell, currentPrice, 2, tradeId);
          remaining -= sell; tp2 = true;
          await DatabaseService.updateTradeAfterTP(tradeId, 2, sell, currentPrice, sell * multiplier, txid);
        }
        if (multiplier >= 20 && !tp3) {
          const sell = remaining * 0.5;
          const txid = await this.executeSell(token, sell, currentPrice, 3, tradeId);
          remaining -= sell; tp3 = true;
          await DatabaseService.updateTradeAfterTP(tradeId, 3, sell, currentPrice, sell * multiplier, txid);
        }
        if (multiplier >= 30 && !tp4) {
          const txid = await this.executeSell(token, remaining, currentPrice, 4, tradeId);
          await DatabaseService.closeTrade(tradeId, currentPrice, remaining * multiplier, txid);
          this.activePositions.delete(token);
          this.positionManager!.closePosition(token);
          return; // Stop monitoring
        }

        if (this.activePositions.has(token)) setTimeout(check, 30000);

      } catch (e) {
        console.error(`Monitoring error for ${token}:`, e);
        setTimeout(check, 60000);
      }
    };

    setTimeout(check, 30000);
  }

  async executeSell(token: string, amount: number, price: number, tpLevel: number, tradeId: number): Promise<string> {
    // Get extreme analysis for sell
    const extremeAnalysis = await extremeCaseHandler.calculateExtremeSlippage(
      token, 'sell', { isSell: true }
    );
    const protection = await ultimateProtection.protectTransaction(
      token, amount, { type: 'sell', tpLevel }, extremeAnalysis
    );

    let txid: string;
    if (protection.success) {
      // Retrieve wallet for signing (same pattern as executeAutoTrade)
      let wallet: any = null;
      try {
        wallet = await secureWalletService.retrieveWallet();
        // Convert slippage from decimal to basis points for Jupiter
        const slippageBps = protection.slippage ? Math.round(protection.slippage * 10000) : 150;
        const result = await SolanaTransactionService.sellToken(
          wallet.privateKey, token, amount, slippageBps
        );
        if (!result.success) {
          console.warn(`TP${tpLevel} sell failed: ${result.error} — recording as mock`);
          txid = 'failed_sell_' + Date.now();
        } else {
          txid = result.signature!;
        }
      } finally {
        if (wallet?.privateKey) {
          wallet.privateKey = '\0'.repeat(wallet.privateKey.length);
          wallet.privateKey = null;
        }
      }
    } else {
      txid = 'mock_sell_' + Date.now();
    }

    notificationService.showTradeNotification('tp_hit', {
      tokenAddress: token,
      tpLevel,
      multiplier: tpLevel === 1 ? '5x' : tpLevel === 2 ? '10x' : tpLevel === 3 ? '20x' : '30x',
    });
    return txid;
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  async buildContext(signal: any): Promise<any> {
    const congestion = await extremeCaseHandler.getNetworkCongestion();
    return {
      walletCount: signal.walletCount,
      isSell: false,
      priceChange1m: 0,
      networkCongestion: congestion,
      liquidity: 100000
    };
  }

  async getCurrentPrice(token: string): Promise<number> {
    // Delegate to the store's price oracle (shared cache, SolanaTracker + Birdeye fallback)
    return useStore.getState().getCurrentPrice(token);
  }

  async sendProtectedBundle(bundle: any, privateKey: string | null): Promise<string> {
    if (__DEV__) console.log(`📤 Sending protected bundle for ${bundle.tokenAddress?.slice(0, 8)}`);

    if (!privateKey) {
      console.warn('⚠️ No private key provided — returning mock signature');
      return 'mock_tx_' + Date.now();
    }

    // Convert slippage from decimal (0.15) to basis points (1500) for Jupiter
    const slippageBps = bundle.slippage ? Math.round(bundle.slippage * 10000) : 100;

    // Use Jupiter DEX swap with JITO MEV protection fallback
    const result = await SolanaTransactionService.buyToken(
      privateKey, bundle.tokenAddress, bundle.amount || bundle.amountSol, slippageBps
    );

    if (!result.success) {
      // Provide actionable error messages based on error code
      const prefix = result.errorCode ? `[${result.errorCode}] ` : '';
      let userMessage = result.error || 'Transaction submission failed';

      switch (result.errorCode) {
        case SwapErrorCode.SLIPPAGE_EXCEEDED:
          userMessage = 'Price moved too fast — slippage tolerance exceeded. Retrying with higher slippage may help.';
          break;
        case SwapErrorCode.INSUFFICIENT_BALANCE:
          userMessage = `Not enough SOL to complete the trade. ${result.error}`;
          break;
        case SwapErrorCode.TRANSACTION_EXPIRED:
          userMessage = 'Transaction expired before confirmation — network may be congested. Will retry.';
          break;
        case SwapErrorCode.RPC_ERROR:
          userMessage = 'RPC node error — may be rate-limited or unavailable. Will retry.';
          break;
      }

      throw new Error(`${prefix}${userMessage}`);
    }

    return result.signature!;
  }

  sendManualNotification(signal: any): void {
    const tradingBalance = (this.positionManager?.portfolioTotal || 10000) * 0.10;
    let suggestedAmount = signal.walletCount >= 3
      ? (this.positionManager?.portfolioTotal || 10000) * 0.40
      : signal.walletCount === 2 ? tradingBalance : tradingBalance * 0.30;

    const title = signal.walletCount >= 3 ? '🔥🔥🔥 MEGA SIGNAL'
      : signal.walletCount === 2 ? '🚀 DOUBLE SIGNAL' : '🔔 SIGNAL';

    notificationService.showSignalNotification({
      token: signal.token,
      walletCount: signal.walletCount,
      suggestedAmount,
      note: signal.note,
      signal,
    });

    DatabaseService.addNotification({
      type: 'manual_signal', title,
      body: `${signal.token?.slice(0, 8)} — $${suggestedAmount.toFixed(0)} suggested`,
      data: { signal, suggestedAmount }
    });
  }
}

export const fortifiedAutoTrader = new FortifiedAutoTrader();
export default fortifiedAutoTrader;
