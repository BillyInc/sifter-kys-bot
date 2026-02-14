import React, { useState, useEffect, useRef } from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  Zap, 
  Bell, 
  Settings, 
  RefreshCw,
  ArrowUp,
  ArrowDown,
  Activity,
  Radio
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export default function WatchlistPanel({ 
  userId, 
  apiUrl, 
  onConfigure 
}) {
  const [wallets, setWallets] = useState([]);
  const [liveActivity, setLiveActivity] = useState([]);
  const [isLive, setIsLive] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [positionChanges, setPositionChanges] = useState({});
  const activityFeedRef = useRef(null);

  // Load initial data
  useEffect(() => {
    loadWatchlist();
    const interval = setInterval(loadWatchlist, 30000); // Poll every 30s
    return () => clearInterval(interval);
  }, [userId]);

  // Auto-scroll activity feed
  useEffect(() => {
    if (activityFeedRef.current) {
      activityFeedRef.current.scrollTop = 0;
    }
  }, [liveActivity]);

  const loadWatchlist = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/table?user_id=${userId}`);
      const data = await response.json();
      
      if (data.success) {
        // Detect position changes
        const changes = {};
        data.wallets.forEach((wallet, idx) => {
          const oldWallet = wallets.find(w => w.wallet_address === wallet.wallet_address);
          if (oldWallet && oldWallet.position !== wallet.position) {
            changes[wallet.wallet_address] = {
              from: oldWallet.position,
              to: wallet.position,
              direction: wallet.position < oldWallet.position ? 'up' : 'down'
            };
          }
        });
        
        setPositionChanges(changes);
        setTimeout(() => setPositionChanges({}), 2000); // Clear after animation
        
        setWallets(data.wallets || []);
        setLastUpdate(new Date());
      }
    } catch (error) {
      console.error('Error loading watchlist:', error);
    }
  };

  // Simulated live activity (replace with real WebSocket/polling)
  useEffect(() => {
    if (!isLive) return;
    
    const interval = setInterval(() => {
      // This should come from real-time data source
      const mockActivity = {
        id: Date.now(),
        wallet: wallets[Math.floor(Math.random() * wallets.length)]?.wallet_address,
        action: Math.random() > 0.5 ? 'buy' : 'sell',
        token: 'BONK',
        amount: Math.floor(Math.random() * 5000) + 100,
        timestamp: new Date()
      };
      
      setLiveActivity(prev => [mockActivity, ...prev].slice(0, 10));
    }, 15000); // New activity every 15s
    
    return () => clearInterval(interval);
  }, [isLive, wallets]);

  const getHealthColor = (status) => {
    if (status === 'healthy') return 'text-green-400';
    if (status === 'warning') return 'text-yellow-400';
    if (status === 'critical') return 'text-red-400';
    return 'text-gray-400';
  };

  const getTierColor = (tier) => {
    if (tier === 'S') return 'from-yellow-600 to-yellow-500';
    if (tier === 'A') return 'from-green-600 to-green-500';
    if (tier === 'B') return 'from-blue-600 to-blue-500';
    return 'from-gray-600 to-gray-500';
  };

  return (
    <div className="space-y-4 pb-20"> {/* Extra padding for activity feed */}
      
      {/* Live Status Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="relative">
            <Radio className={`${isLive ? 'text-red-500 animate-pulse' : 'text-gray-400'}`} size={20} />
            {isLive && (
              <span className="absolute -top-1 -right-1 w-2 h-2 bg-red-500 rounded-full animate-ping" />
            )}
          </div>
          <div>
            <h3 className="font-bold">Smart Money Watchlist</h3>
            <p className="text-xs text-gray-400">
              {isLive ? 'Live Monitoring' : 'Paused'} • Updated {lastUpdate ? new Date(lastUpdate).toLocaleTimeString() : 'Never'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsLive(!isLive)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              isLive 
                ? 'bg-red-500/20 text-red-400 border border-red-500/30' 
                : 'bg-gray-500/20 text-gray-400 border border-gray-500/30'
            }`}
          >
            {isLive ? 'LIVE' : 'Paused'}
          </button>
          
          <button
            onClick={loadWatchlist}
            className="p-2 hover:bg-white/10 rounded-lg transition"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* Health Overview Cards */}
      <div className="grid grid-cols-3 gap-3">
        <motion.div 
          whileHover={{ scale: 1.02 }}
          className="bg-gradient-to-br from-green-900/30 to-green-800/20 border border-green-500/30 rounded-xl p-4"
        >
          <div className="flex items-center justify-between mb-2">
            <Activity className="text-green-400" size={18} />
            <span className="text-2xl font-bold text-green-400">
              {wallets.filter(w => !w.degradation_alerts || w.degradation_alerts.length === 0).length}
            </span>
          </div>
          <div className="text-xs text-gray-400">Healthy</div>
        </motion.div>

        <motion.div 
          whileHover={{ scale: 1.02 }}
          className="bg-gradient-to-br from-yellow-900/30 to-yellow-800/20 border border-yellow-500/30 rounded-xl p-4"
        >
          <div className="flex items-center justify-between mb-2">
            <Bell className="text-yellow-400" size={18} />
            <span className="text-2xl font-bold text-yellow-400">
              {wallets.filter(w => w.degradation_alerts && w.degradation_alerts.some(a => a.severity === 'yellow')).length}
            </span>
          </div>
          <div className="text-xs text-gray-400">Monitoring</div>
        </motion.div>

        <motion.div 
          whileHover={{ scale: 1.02 }}
          className="bg-gradient-to-br from-red-900/30 to-red-800/20 border border-red-500/30 rounded-xl p-4"
        >
          <div className="flex items-center justify-between mb-2">
            <Zap className="text-red-400" size={18} />
            <span className="text-2xl font-bold text-red-400">
              {wallets.filter(w => w.degradation_alerts && w.degradation_alerts.some(a => a.severity === 'red')).length}
            </span>
          </div>
          <div className="text-xs text-gray-400">Action Needed</div>
        </motion.div>
      </div>

      {/* Premier League Table */}
      <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
        <div className="bg-gradient-to-r from-purple-900/50 to-purple-800/30 border-b border-white/10 p-3">
          <h3 className="font-bold text-sm">🏆 Premier League Rankings</h3>
        </div>

        <div className="divide-y divide-white/5">
          <AnimatePresence>
            {wallets.slice(0, 10).map((wallet, idx) => {
              const change = positionChanges[wallet.wallet_address];
              
              return (
                <motion.div
                  key={wallet.wallet_address}
                  layout
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  transition={{ duration: 0.3 }}
                  className={`p-3 hover:bg-white/5 transition relative ${
                    change ? 'bg-purple-500/10' : ''
                  }`}
                >
                  {/* Position Change Indicator */}
                  {change && (
                    <motion.div
                      initial={{ opacity: 0, scale: 0 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0 }}
                      className={`absolute left-2 top-1/2 -translate-y-1/2 ${
                        change.direction === 'up' ? 'text-green-400' : 'text-red-400'
                      }`}
                    >
                      {change.direction === 'up' ? (
                        <ArrowUp size={16} className="animate-bounce" />
                      ) : (
                        <ArrowDown size={16} className="animate-bounce" />
                      )}
                    </motion.div>
                  )}

                  <div className="flex items-center gap-3">
                    {/* Rank */}
                    <div className="w-8 text-center">
                      <span className={`font-bold ${
                        idx === 0 ? 'text-yellow-400 text-lg' :
                        idx === 1 ? 'text-gray-400 text-lg' :
                        idx === 2 ? 'text-orange-400 text-lg' :
                        'text-gray-500'
                      }`}>
                        {idx < 3 ? ['🥇', '🥈', '🥉'][idx] : `#${idx + 1}`}
                      </span>
                    </div>

                    {/* Wallet Info */}
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <code className="text-sm font-mono text-gray-300">
                          {wallet.wallet_address?.slice(0, 8)}...
                        </code>
                        
                        {/* Tier Badge with Gradient */}
                        <div className={`px-2 py-0.5 bg-gradient-to-r ${getTierColor(wallet.tier)} rounded text-xs font-bold text-white shadow-lg`}>
                          {wallet.tier}
                        </div>

                        {/* Live Indicator if trading */}
                        {Math.random() > 0.7 && ( // Simulate some wallets being active
                          <motion.div
                            animate={{ opacity: [1, 0.3, 1] }}
                            transition={{ repeat: Infinity, duration: 2 }}
                            className="flex items-center gap-1 text-xs text-green-400"
                          >
                            <div className="w-1.5 h-1.5 bg-green-400 rounded-full" />
                            Active
                          </motion.div>
                        )}
                      </div>

                      {/* Mini Sparkline (simulated) */}
                      <div className="flex items-center gap-2">
                        <div className="flex items-end gap-0.5 h-4">
                          {[...Array(8)].map((_, i) => (
                            <motion.div
                              key={i}
                              initial={{ height: 0 }}
                              animate={{ height: `${Math.random() * 100}%` }}
                              transition={{ delay: i * 0.05 }}
                              className={`w-1 rounded-t ${
                                wallet.roi_30d > 0 ? 'bg-green-500' : 'bg-red-500'
                              }`}
                            />
                          ))}
                        </div>
                        
                        <span className={`text-xs font-semibold ${
                          wallet.roi_30d > 0 ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {wallet.roi_30d > 0 ? '+' : ''}{wallet.roi_30d}%
                        </span>
                      </div>
                    </div>

                    {/* Form Circles */}
                    <div className="flex gap-1">
                      {(wallet.form || [{}, {}, {}, {}, {}]).slice(0, 5).map((f, fi) => (
                        <motion.div
                          key={fi}
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ delay: fi * 0.05 }}
                          className={`w-2 h-2 rounded-full ${
                            f.result === 'win' ? 'bg-green-500' :
                            f.result === 'loss' ? 'bg-red-500' :
                            'bg-gray-500'
                          }`}
                        />
                      ))}
                    </div>

                    {/* Configure Button */}
                    <button
                      onClick={() => onConfigure(wallet)}
                      className="p-2 hover:bg-purple-500/20 rounded-lg transition"
                    >
                      <Settings size={14} className="text-purple-400" />
                    </button>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      </div>

      {/* Fixed Live Activity Feed */}
      <motion.div
        initial={{ y: 100, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        className="fixed bottom-0 right-0 w-96 bg-black/95 backdrop-blur-xl border-t border-l border-white/10 rounded-tl-xl shadow-2xl"
        style={{ maxHeight: '300px' }}
      >
        <div className="bg-gradient-to-r from-red-900/50 to-red-800/30 border-b border-white/10 p-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="text-red-400 animate-pulse" size={16} />
            <h4 className="font-bold text-sm">Live Activity Feed</h4>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 bg-red-500 rounded-full animate-ping" />
            <span className="text-xs text-red-400">LIVE</span>
          </div>
        </div>

        <div 
          ref={activityFeedRef}
          className="overflow-y-auto" 
          style={{ maxHeight: '250px' }}
        >
          <AnimatePresence>
            {liveActivity.map((activity) => (
              <motion.div
                key={activity.id}
                initial={{ x: 100, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                exit={{ x: -100, opacity: 0 }}
                className={`p-3 border-b border-white/5 ${
                  activity.action === 'buy' ? 'bg-green-500/5' : 'bg-red-500/5'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  {activity.action === 'buy' ? (
                    <TrendingUp className="text-green-400" size={14} />
                  ) : (
                    <TrendingDown className="text-red-400" size={14} />
                  )}
                  <code className="text-xs font-mono text-gray-300">
                    {activity.wallet?.slice(0, 8)}...
                  </code>
                  <span className={`text-xs font-bold ${
                    activity.action === 'buy' ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {activity.action.toUpperCase()}
                  </span>
                </div>
                <div className="text-xs text-gray-400">
                  <span className="text-yellow-400">${activity.token}</span>
                  {' • '}
                  <span className="text-white font-semibold">${activity.amount}</span>
                  {' • '}
                  <span>{new Date(activity.timestamp).toLocaleTimeString()}</span>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>

          {liveActivity.length === 0 && (
            <div className="p-8 text-center text-gray-500 text-sm">
              Waiting for activity...
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}