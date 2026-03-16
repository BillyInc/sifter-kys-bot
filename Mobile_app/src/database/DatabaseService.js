import SQLite from 'react-native-sqlite-storage';
import * as FileSystem from 'expo-file-system';

SQLite.enablePromise(true);

class DatabaseService {
  constructor() {
    this.db = null;
    this.initialized = false;
  }

  async init() {
    if (this.initialized) return this.db;
    try {
      const dbPath = `${FileSystem.documentDirectory}sifter.db`;
      this.db = await SQLite.openDatabase({
        name: dbPath,
        location: 'default',
        createFromLocation: '~www/schema.sql'
      });
      await this.migrate();
      this.initialized = true;
      console.log('✅ Database initialized');
      return this.db;
    } catch (error) {
      console.error('Database init error:', error);
      throw error;
    }
  }

  async migrate() {
    const result = await this.db.executeSql(
      "SELECT value FROM user_settings WHERE key = 'db_version'"
    );
    const version = result[0]?.rows?.item(0)?.value || '0';

    if (version < '2') {
      // Create purchased_tokens table for duplicate prevention
      await this.db.executeSql(`
        CREATE TABLE IF NOT EXISTS purchased_tokens (
          token_address TEXT PRIMARY KEY,
          first_bought_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          tx_signature TEXT,
          wallet_address TEXT,
          usd_amount REAL
        )
      `);
      // Create sniper blacklist table
      await this.db.executeSql(`
        CREATE TABLE IF NOT EXISTS sniper_blacklist (
          wallet_address TEXT PRIMARY KEY,
          type TEXT NOT NULL,
          evidence_tx TEXT,
          token TEXT,
          detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
      `);
      await this.db.executeSql(
        "INSERT OR REPLACE INTO user_settings (key, value) VALUES ('db_version', '2')"
      );
    }
  }

  // ==================== ELITE 15 ====================
  async syncElite15(wallets) {
    const db = await this.init();
    await db.executeSql('BEGIN TRANSACTION');
    try {
      await db.executeSql('DELETE FROM elite_15');
      for (const wallet of wallets) {
        await db.executeSql(
          `INSERT INTO elite_15
           (wallet_address, rank, professional_score, tier, roi_30d, runners_30d, win_rate_7d, consistency_score, last_trade_time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            wallet.wallet_address, wallet.rank, wallet.professional_score,
            wallet.tier, wallet.roi_30d || 0, wallet.runners_30d || 0,
            wallet.win_rate_7d || 0, wallet.consistency_score || 0, wallet.last_trade_time
          ]
        );
      }
      await db.executeSql('COMMIT');
      console.log(`✅ Synced ${wallets.length} Elite 15 wallets`);
    } catch (error) {
      await db.executeSql('ROLLBACK');
      throw error;
    }
  }

  async getElite15() {
    const db = await this.init();
    const results = await db.executeSql(
      `SELECT w.*,
        (SELECT status FROM watchlist WHERE wallet_address = w.wallet_address) as watchlist_status
       FROM elite_15 w ORDER BY rank ASC`
    );
    const wallets = [];
    for (let i = 0; i < results[0].rows.length; i++) {
      wallets.push(results[0].rows.item(i));
    }
    return wallets;
  }

  // ==================== WATCHLIST ====================
  async addToWatchlist(walletAddress, autoReplace = false) {
    const db = await this.init();
    await db.executeSql(
      `INSERT INTO watchlist (wallet_address, auto_replace)
       VALUES (?, ?)
       ON CONFLICT(wallet_address) DO UPDATE SET
         status = 'healthy', auto_replace = excluded.auto_replace`,
      [walletAddress, autoReplace ? 1 : 0]
    );
  }

  async removeFromWatchlist(walletAddress) {
    const db = await this.init();
    await db.executeSql('DELETE FROM watchlist WHERE wallet_address = ?', [walletAddress]);
  }

  async getWatchlist() {
    const db = await this.init();
    const results = await db.executeSql(
      `SELECT w.*, e.*
       FROM watchlist w
       JOIN elite_15 e ON w.wallet_address = e.wallet_address
       ORDER BY e.rank ASC`
    );
    const wallets = [];
    for (let i = 0; i < results[0].rows.length; i++) {
      wallets.push(results[0].rows.item(i));
    }
    return wallets;
  }

  async updateWatchlistStatus(walletAddress, status, alerts) {
    const db = await this.init();
    await db.executeSql(
      `UPDATE watchlist SET status = ?, degradation_alerts = ?, last_checked = CURRENT_TIMESTAMP
       WHERE wallet_address = ?`,
      [status, JSON.stringify(alerts), walletAddress]
    );
  }

  // ==================== ACTIVE TRADES ====================
  async addTrade(trade) {
    const db = await this.init();
    const result = await db.executeSql(
      `INSERT INTO active_trades
       (token_address, token_symbol, entry_price, entry_size, remaining_size,
        signal_type, wallet_count, triggering_wallets, total_usd_signal)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       RETURNING id`,
      [
        trade.token_address, trade.token_symbol, trade.entry_price,
        trade.entry_size, trade.remaining_size, trade.signal_type,
        trade.wallet_count, JSON.stringify(trade.triggering_wallets), trade.total_usd_signal
      ]
    );
    const tradeId = result[0].rows.item(0).id;
    await db.executeSql(
      `INSERT INTO trade_history (trade_id, action, amount, price, usd_value, tx_signature)
       VALUES (?, 'buy', ?, ?, ?, ?)`,
      [tradeId, trade.entry_size, trade.entry_price, trade.entry_size, trade.tx_signature]
    );
    return tradeId;
  }

  async updateTradeAfterTP(tradeId, tpLevel, sellAmount, price, usdValue, txSignature) {
    const db = await this.init();
    await db.executeSql('BEGIN TRANSACTION');
    try {
      await db.executeSql(
        `UPDATE active_trades SET remaining_size = remaining_size - ?, tp${tpLevel}_executed = 1
         WHERE id = ?`,
        [sellAmount, tradeId]
      );
      await db.executeSql(
        `INSERT INTO trade_history (trade_id, action, amount, price, usd_value, tx_signature)
         VALUES (?, ?, ?, ?, ?, ?)`,
        [tradeId, `sell_tp${tpLevel}`, sellAmount, price, usdValue, txSignature]
      );
      await db.executeSql('COMMIT');
    } catch (error) {
      await db.executeSql('ROLLBACK');
      throw error;
    }
  }

  async closeTrade(tradeId, finalPrice, finalUsd, txSignature) {
    const db = await this.init();
    await db.executeSql(
      `UPDATE active_trades SET is_active = 0, closed_at = CURRENT_TIMESTAMP,
       final_pnl = ? - entry_size WHERE id = ?`,
      [finalUsd, tradeId]
    );
    await db.executeSql(
      `INSERT INTO trade_history (trade_id, action, amount, price, usd_value, tx_signature)
       VALUES (?, 'close', ?, ?, ?, ?)`,
      [tradeId, finalUsd, finalPrice, finalUsd, txSignature]
    );
  }

  async getActiveTrades() {
    const db = await this.init();
    const results = await db.executeSql(
      'SELECT * FROM active_trades WHERE is_active = 1 ORDER BY entry_time DESC'
    );
    const trades = [];
    for (let i = 0; i < results[0].rows.length; i++) {
      const trade = results[0].rows.item(i);
      trade.triggering_wallets = JSON.parse(trade.triggering_wallets);
      trades.push(trade);
    }
    return trades;
  }

  // ==================== PURCHASED TOKENS (Duplicate Prevention) ====================
  async recordPurchasedToken(tokenAddress, walletAddress, txSignature, usdAmount) {
    const db = await this.init();
    await db.executeSql(
      `INSERT OR IGNORE INTO purchased_tokens
       (token_address, wallet_address, tx_signature, usd_amount)
       VALUES (?, ?, ?, ?)`,
      [tokenAddress, walletAddress, txSignature, usdAmount]
    );
  }

  async getPurchasedTokens() {
    const db = await this.init();
    const results = await db.executeSql('SELECT token_address FROM purchased_tokens');
    const tokens = new Set();
    for (let i = 0; i < results[0].rows.length; i++) {
      tokens.add(results[0].rows.item(i).token_address);
    }
    return tokens;
  }

  async hasBeenPurchased(tokenAddress) {
    const db = await this.init();
    const results = await db.executeSql(
      'SELECT 1 FROM purchased_tokens WHERE token_address = ?',
      [tokenAddress]
    );
    return results[0].rows.length > 0;
  }

  // ==================== SNIPER BLACKLIST ====================
  async addToSniperBlacklist(walletAddress, type, evidenceTx, token) {
    const db = await this.init();
    await db.executeSql(
      `INSERT OR IGNORE INTO sniper_blacklist (wallet_address, type, evidence_tx, token)
       VALUES (?, ?, ?, ?)`,
      [walletAddress, type, evidenceTx, token]
    );
  }

  async getSniperBlacklist() {
    const db = await this.init();
    const results = await db.executeSql('SELECT wallet_address FROM sniper_blacklist');
    const blacklist = new Set();
    for (let i = 0; i < results[0].rows.length; i++) {
      blacklist.add(results[0].rows.item(i).wallet_address);
    }
    return blacklist;
  }

  // ==================== SIGNALS BUFFER ====================
  async saveSignalBuffer(tokenAddress, signal) {
    const db = await this.init();
    await db.executeSql(
      `INSERT OR REPLACE INTO signals_buffer
       (token_address, wallets, total_usd, first_seen, last_seen, wallet_count, expires_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        tokenAddress, JSON.stringify(signal.wallets), signal.total_usd,
        signal.first_seen.toISOString(), signal.last_seen.toISOString(),
        signal.wallet_count, signal.expires_at.toISOString()
      ]
    );
  }

  async getSignalBuffer(tokenAddress) {
    const db = await this.init();
    const results = await db.executeSql(
      'SELECT * FROM signals_buffer WHERE token_address = ? AND expires_at > CURRENT_TIMESTAMP',
      [tokenAddress]
    );
    if (results[0].rows.length > 0) {
      const signal = results[0].rows.item(0);
      signal.wallets = JSON.parse(signal.wallets);
      signal.first_seen = new Date(signal.first_seen);
      signal.last_seen = new Date(signal.last_seen);
      signal.expires_at = new Date(signal.expires_at);
      return signal;
    }
    return null;
  }

  async deleteSignalBuffer(tokenAddress) {
    const db = await this.init();
    await db.executeSql('DELETE FROM signals_buffer WHERE token_address = ?', [tokenAddress]);
  }

  // ==================== USER SETTINGS ====================
  async getSetting(key) {
    const db = await this.init();
    const results = await db.executeSql(
      'SELECT value FROM user_settings WHERE key = ?',
      [key]
    );
    if (results[0].rows.length > 0) return results[0].rows.item(0).value;
    return null;
  }

  async setSetting(key, value) {
    const db = await this.init();
    await db.executeSql(
      `INSERT INTO user_settings (key, value, updated_at)
       VALUES (?, ?, CURRENT_TIMESTAMP)
       ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`,
      [key, value.toString()]
    );
  }

  async getAllSettings() {
    const db = await this.init();
    const results = await db.executeSql('SELECT key, value FROM user_settings');
    const settings = {};
    for (let i = 0; i < results[0].rows.length; i++) {
      const row = results[0].rows.item(i);
      settings[row.key] = row.value;
    }
    return settings;
  }

  // ==================== USER (Tier + Mode) ====================
  // Fetches user tier/mode from local settings (synced from Supabase)
  async getUser(userId) {
    const tier = await this.getSetting('user_tier') || 'free';
    const mode = await this.getSetting('trading_mode') || 'auto';
    return { id: userId, tier, preferredMode: mode };
  }

  async saveUserPreference(key, value) {
    // Persists trading_mode, user_tier, etc. locally
    await this.setSetting(key, value);
  }

  async getWallets() {
    const elite15 = await this.getElite15();
    const watchlist = await this.getWatchlist();
    return { elite15, watchlist };
  }

  // ==================== NOTIFICATIONS ====================
  async addNotification(notification) {
    const db = await this.init();
    await db.executeSql(
      `INSERT INTO notifications (type, title, body, data) VALUES (?, ?, ?, ?)`,
      [notification.type, notification.title, notification.body, JSON.stringify(notification.data)]
    );
  }

  async getUnreadNotifications() {
    const db = await this.init();
    const results = await db.executeSql(
      'SELECT * FROM notifications WHERE is_read = 0 ORDER BY created_at DESC'
    );
    const notifications = [];
    for (let i = 0; i < results[0].rows.length; i++) {
      const n = results[0].rows.item(i);
      n.data = JSON.parse(n.data || '{}');
      notifications.push(n);
    }
    return notifications;
  }

  async markNotificationRead(id) {
    const db = await this.init();
    await db.executeSql('UPDATE notifications SET is_read = 1 WHERE id = ?', [id]);
  }
}

export default new DatabaseService();
