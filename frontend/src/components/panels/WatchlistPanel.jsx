import React, { useState, useEffect } from 'react';
import { TrendingUp, RefreshCw, Activity, Bell, Zap } from 'lucide-react';
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
        body: JSON.stringify({ user_id: userId })
      });
      const data = await response.json();
      if (data.success) await loadWatchlist();
    } catch (error) {
      console.error('Error refreshing wallet:', error);
    }
  };

  // ✅ NEW: Delete handler
  const handleDeleteWallet = async (walletAddress) => {
    try {
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, wallet_address: walletAddress })
      });
      const data = await response.json();
      if (data.success) {
        setWallets(prev => prev.filter(w => w.wallet_address !== walletAddress));
      } else {
        console.error('Delete failed:', data.error);
      }
    } catch (error) {
      console.error('Error deleting wallet:', error);
    }
  };

  const getTierColor = (tier) => {
    if (tier === 'S') return 'from-yellow-600 to-yellow-500';
    if (tier === 'A') return 'from-green-600 to-green-500';
    if (tier === 'B') return 'from-blue-600 to-blue-500';
    return 'from-gray-600 to-gray-500';
  };

  const healthyCount = wallets.filter(w => !w.degradation_alerts || w.degradation_alerts.length === 0).length;
  const warningCount = wallets.filter(w => w.degradation_alerts?.some(a => a.severity === 'yellow')).length;
  const criticalCount = wallets.filter(w => w.degradation_alerts?.some(a => a.severity === 'red')).length;

  return (
    <div className="space-y-4">
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

      <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
        <div className="bg-gradient-to-r from-purple-900/50 to-purple-800/30 border-b border-white/10 p-3">
          <h3 className="font-bold text-sm">Rankings</h3>
        </div>

        <div className="divide-y divide-white/5">
          {wallets.map((wallet, idx) => (
            <WatchlistExpandedCard
              key={wallet.wallet_address}
              wallet={wallet}
              rank={idx + 1}
              onRefresh={handleRefreshWallet}
              onDelete={handleDeleteWallet}
              getTierColor={getTierColor}
            />
          ))}
        </div>

        {wallets.length === 0 && (
          <div className="p-8 text-center text-gray-500">
            <TrendingUp size={48} className="mx-auto mb-3 opacity-20" />
            <p className="text-sm">No wallets in your watchlist yet</p>
            <p className="text-xs mt-1">Use Auto Discovery or Analyze to find smart money wallets</p>
          </div>
        )}
      </div>
    </div>
  );
}