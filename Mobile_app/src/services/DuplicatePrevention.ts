import AsyncStorage from '@react-native-async-storage/async-storage';
import PushNotification from 'react-native-push-notification';
import DatabaseService from '../database/DatabaseService';

// HARD RULE: The auto-trader NEVER buys the same token twice.
// The only way to buy again is explicit user approval via the "Buy Again" button.
class DuplicatePrevention {
  private purchasedTokens: Set<string>;
  private userApprovedTokens: Set<string>;
  private walletLastBuy: Map<string, number>;
  private WALLET_COOLDOWN: number;

  constructor() {
    this.purchasedTokens = new Set(); // Persisted to DB — survives app restarts
    this.userApprovedTokens = new Set(); // Explicit one-time overrides
    this.walletLastBuy = new Map(); // wallet -> last buy timestamp (in-memory only)
    this.WALLET_COOLDOWN = 60000; // 1 min — just for logging, not blocking
  }

  async loadHistory(): Promise<void> {
    // Reload from database on startup so restarts don't reset the hard block
    const stored = await DatabaseService.getPurchasedTokens();
    this.purchasedTokens = stored;
    console.log(`📝 Loaded ${this.purchasedTokens.size} previously purchased tokens`);
  }

  async canBuy(tokenAddress: string, walletAddress: string, signal: any, isManualOverride: boolean = false): Promise<boolean> {
    // ── HARD RULE ──────────────────────────────────────────────────────────────
    // Never auto-buy the same token twice regardless of how many wallets signal
    // Check database (source of truth) instead of in-memory Set to avoid race conditions
    // ──────────────────────────────────────────────────────────────────────────
    const exists = await DatabaseService.hasBeenPurchased(tokenAddress);
    if (exists) {
      if (isManualOverride) {
        // User clicked "Buy Again" and confirmed — allow it this once
        if (__DEV__) console.log(`👤 Manual override: user approved re-buy of ${tokenAddress.slice(0, 8)}`);
        this.userApprovedTokens.add(tokenAddress);
        return true;
      }

      // Auto-trade path → BLOCK
      if (__DEV__) console.log(`🚫 BLOCKED: already bought ${tokenAddress.slice(0, 8)} — auto-trade will not buy twice`);
      this.suggestManualRebuy(tokenAddress);
      return false;
    }

    // Track wallet activity for monitoring (doesn't block different-token buys)
    const lastWalletBuy = this.walletLastBuy.get(walletAddress);
    if (lastWalletBuy && (Date.now() - lastWalletBuy) < this.WALLET_COOLDOWN) {
      if (__DEV__) console.log(`⚡ Wallet ${walletAddress.slice(0, 8)} buying rapidly — OK, different token`);
    }

    // Check local blacklist
    const blacklisted = await this.checkBlacklist(tokenAddress);
    if (blacklisted) {
      if (__DEV__) console.log(`⛔ Token ${tokenAddress.slice(0, 8)} is blacklisted`);
      return false;
    }

    return true;
  }

  async recordBuy(tokenAddress: string, walletAddress: string, txId: string): Promise<void> {
    // Persist forever — this token is off the auto-trade list permanently
    this.purchasedTokens.add(tokenAddress);
    this.walletLastBuy.set(walletAddress, Date.now());

    await DatabaseService.recordPurchasedToken(tokenAddress, walletAddress, txId, 0);
    if (__DEV__) console.log(`📝 Recorded purchase of ${tokenAddress.slice(0, 8)} — will NEVER auto-buy again`);
  }

  async approveRebuy(tokenAddress: string): Promise<void> {
    // Called when user taps "Buy Again" and confirms the dialog
    this.userApprovedTokens.add(tokenAddress);
    if (__DEV__) console.log(`✅ User approved re-buy of ${tokenAddress.slice(0, 8)}`);
  }

  suggestManualRebuy(tokenAddress: string): void {
    PushNotification.localNotification({
      channelId: 'trades',
      title: '🔄 Already Own This Token',
      message: 'You already bought this token. Tap to manually buy again if you want.',
      data: { type: 'manual_rebuy', token: tokenAddress }
    } as any);
  }

  async checkBlacklist(tokenAddress: string): Promise<boolean> {
    const blacklist = await AsyncStorage.getItem('token_blacklist');
    if (blacklist) return JSON.parse(blacklist).includes(tokenAddress);
    return false;
  }

  // Called after completing a manual override to reset the one-time flag
  clearOverride(tokenAddress: string): void {
    this.userApprovedTokens.delete(tokenAddress);
  }
}

export const duplicatePrevention = new DuplicatePrevention();
export default duplicatePrevention;
