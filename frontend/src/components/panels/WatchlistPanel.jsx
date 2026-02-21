import React, { useState, useEffect } from 'react';
import { RefreshCw, TrendingUp, Activity, Bell, Zap } from 'lucide-react';
import { motion } from 'framer-motion';
import WatchlistExpandedCard from '../WatchlistExpandedCard';

export default function WatchlistPanel({ userId, apiUrl, onConfigure }) {
  const [wallets, setWallets] = useState([]);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => { loadWatchlist(); }, [userId]);

  const loadWatchlist = async () => {
    setIsRefreshing(true);
    try {
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/table?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setWallets(data.wallets || []);
        setLastUpdate(new Date());
      }
    } catch (error) {
      console.error('Error loading watchlist:', error);
    }
    setIsRefreshing(false);
  };

  const handleRefreshWallet = async (walletAddress) => {
    try {
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/${walletAddress}/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId }),
      });
      const data = await response.json();
      if (data.success) await loadWatchlist();
    } catch (error) {
      console.error('Error refreshing wallet:', error);
    }
  };

  const handleDeleteWallet = async (walletAddress) => {
    try {
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, wallet_address: walletAddress }),
      });
      const data = await response.json();
      if (data.success) {
        setWallets(prev => prev.filter(w => w.wallet_address !== walletAddress));
      }
    } catch (error) {
      console.error('Error deleting wallet:', error);
    }
  };

  const healthyCount  = wallets.filter(w => !w.degradation_alerts?.length).length;
  const warningCount  = wallets.filter(w => w.degradation_alerts?.some(a => a.severity === 'yellow')).length;
  const criticalCount = wallets.filter(w => w.degradation_alerts?.some(a => a.severity === 'red')).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* ── Original header ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-bold text-lg">🏆 Your Watchlist</h3>
          <p className="text-xs text-gray-400">
            Last updated: {lastUpdate ? new Date(lastUpdate).toLocaleTimeString() : 'Never'}
          </p>
        </div>
        <button onClick={loadWatchlist} disabled={isRefreshing} className="p-2 hover:bg-white/10 rounded-lg transition disabled:opacity-50">
          <RefreshCw size={16} className={isRefreshing ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* ── Original health stat cards ───────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-3">
        <motion.div whileHover={{ scale: 1.02 }} className="bg-gradient-to-br from-green-900/30 to-green-800/20 border border-green-500/30 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <Activity className="text-green-400" size={18} />
            <span className="text-2xl font-bold text-green-400">{healthyCount}</span>
          </div>
          <div className="text-xs text-gray-400">Healthy</div>
        </motion.div>

        <motion.div whileHover={{ scale: 1.02 }} className="bg-gradient-to-br from-yellow-900/30 to-yellow-800/20 border border-yellow-500/30 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <Bell className="text-yellow-400" size={18} />
            <span className="text-2xl font-bold text-yellow-400">{warningCount}</span>
          </div>
          <div className="text-xs text-gray-400">Monitoring</div>
        </motion.div>

        <motion.div whileHover={{ scale: 1.02 }} className="bg-gradient-to-br from-red-900/30 to-red-800/20 border border-red-500/30 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <Zap className="text-red-400" size={18} />
            <span className="text-2xl font-bold text-red-400">{criticalCount}</span>
          </div>
          <div className="text-xs text-gray-400">Action Needed</div>
        </motion.div>
      </div>

      {/* ── Terminal table ───────────────────────────────────────────────────── */}
      <div style={{
        background: '#070d14',
        border: '1px solid #1a2640',
        borderRadius: 8,
        overflow: 'hidden',
      }}>

        {/* Column headers */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '36px 140px 44px 52px 76px 68px 60px 60px 1fr',
          gap: 8,
          padding: '9px 16px',
          background: '#0a1220',
          borderBottom: '1px solid #1a2640',
          fontFamily: 'monospace', fontSize: 9,
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          color: '#3a5a8a',
        }}>
          <div style={{ textAlign: 'center' }}>#</div>
          <div>ADDRESS</div>
          <div style={{ textAlign: 'center' }}>TIER</div>
          <div style={{ textAlign: 'right' }}>SCORE</div>
          <div style={{ textAlign: 'right' }}>ATH DIST</div>
          <div style={{ textAlign: 'right' }}>ROI 30D</div>
          <div style={{ textAlign: 'right' }}>RUNNERS</div>
          <div style={{ textAlign: 'center' }}>FORM</div>
          <div style={{ textAlign: 'right' }}>ACTIONS</div>
        </div>

        {/* Rows */}
        {wallets.length === 0 ? (
          <div style={{ padding: '48px 24px', textAlign: 'center' }}>
            <TrendingUp size={36} style={{ color: '#1a2640', margin: '0 auto 12px', display: 'block' }} />
            <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#334155' }}>No wallets in watchlist</div>
            <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#1e293b', marginTop: 4 }}>Use Auto Discovery to find smart money wallets</div>
          </div>
        ) : wallets.map((wallet, idx) => (
          <WatchlistExpandedCard
            key={wallet.wallet_address}
            wallet={wallet}
            rank={idx + 1}
            onRefresh={handleRefreshWallet}
            onDelete={handleDeleteWallet}
          />
        ))}
      </div>

    </div>
  );
}