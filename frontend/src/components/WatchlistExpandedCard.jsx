import React, { useState } from 'react';
import { RefreshCw, TrendingUp, ChevronDown, ChevronUp } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export default function WatchlistExpandedCard({ 
  wallet, 
  rank, 
  onRefresh,
  getTierColor 
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await onRefresh(wallet.wallet_address);
    setIsRefreshing(false);
  };

  // Traffic light colors based on score
  const getTrafficLights = (value, max = 100) => {
    const percentage = (value / max) * 100;
    const filled = Math.round((percentage / 100) * 5);
    
    return Array(5).fill(0).map((_, i) => (
      <div
        key={i}
        className={`w-3 h-3 rounded-full ${
          i < filled ? 'bg-green-500' : 'bg-gray-600'
        }`}
      />
    ));
  };

  const getLabelForScore = (value, type) => {
    if (type === 'ath') {
      if (value >= 80) return 'ELITE';
      if (value >= 70) return 'STRONG';
      if (value >= 50) return 'GOOD';
      return 'POOR';
    }
    if (type === 'entry') {
      if (value >= 80) return 'EARLY';
      if (value >= 60) return 'GOOD';
      if (value >= 40) return 'LATE';
      return 'VERY LATE';
    }
    if (type === 'consistency') {
      if (value <= 0.3) return 'SOLID';
      if (value <= 0.5) return 'GOOD';
      if (value <= 0.7) return 'FAIR';
      return 'VOLATILE';
    }
    if (type === 'winrate') {
      if (value >= 70) return 'EXCELLENT';
      if (value >= 50) return 'GOOD';
      if (value >= 30) return 'FAIR';
      return 'POOR';
    }
    return '';
  };

  // Mock data for demonstration (replace with real data from API)
  const distanceToATH = wallet.avg_distance_to_peak || 78;
  const entryQuality = 82; // Calculate from entry percentile
  const consistency = wallet.consistency_score || 0.23;
  const winRate = wallet.win_rate_7d || 73;

  // Recent trades (mock - replace with real data)
  const recentTrades = wallet.recent_trades || [
    { token: 'BONK', entry: 0.1, ath: 92, distance: 920, result: 'win' },
    { token: 'WIF', entry: 2.3, ath: 88, distance: 38, result: 'win' },
    { token: 'POPCAT', entry: 5.1, ath: 76, distance: 15, result: 'win' }
  ];

  return (
    <motion.div
      layout
      className="bg-black/30 border border-white/10 rounded-lg overflow-hidden"
    >
      {/* COLLAPSED VIEW */}
      <div 
        className="p-3 hover:bg-white/5 transition cursor-pointer"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          {/* Rank */}
          <div className="w-8 text-center">
            <span className={`font-bold ${
              rank === 1 ? 'text-yellow-400 text-lg' :
              rank === 2 ? 'text-gray-400 text-lg' :
              rank === 3 ? 'text-orange-400 text-lg' :
              'text-gray-500'
            }`}>
              {rank <= 3 ? ['🥇', '🥈', '🥉'][rank - 1] : `#${rank}`}
            </span>
          </div>

          {/* Wallet Info */}
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <code className="text-sm font-mono text-gray-300">
                {wallet.wallet_address?.slice(0, 8)}...
              </code>
              
              {/* Tier Badge */}
              <div className={`px-2 py-0.5 bg-gradient-to-r ${getTierColor(wallet.tier)} rounded text-xs font-bold text-white shadow-lg`}>
                {wallet.tier}
              </div>
            </div>

            {/* Stats Row */}
            <div className="flex items-center gap-4 text-xs">
              <div>
                <span className="text-gray-500">Score:</span>
                <span className="ml-1 text-white font-bold">{wallet.professional_score || 0}</span>
              </div>
              <div>
                <span className="text-gray-500">ROI:</span>
                <span className={`ml-1 font-bold ${
                  (wallet.roi_30d || 0) > 0 ? 'text-green-400' : 'text-red-400'
                }`}>
                  {(wallet.roi_30d || 0) > 0 ? '+' : ''}{wallet.roi_30d || 0}%
                </span>
              </div>
              <div>
                <span className="text-gray-500">Runners:</span>
                <span className="ml-1 text-yellow-400 font-bold">{wallet.runners_30d || 0}</span>
              </div>
            </div>
          </div>

          {/* Form Circles */}
          <div className="flex gap-1">
            {(wallet.form || [{result: 'neutral'}, {result: 'neutral'}, {result: 'neutral'}, {result: 'neutral'}, {result: 'neutral'}]).slice(0, 5).map((f, fi) => (
              <div
                key={fi}
                className={`w-2 h-2 rounded-full ${
                  f.result === 'win' ? 'bg-green-500' :
                  f.result === 'loss' ? 'bg-red-500' :
                  'bg-gray-500'
                }`}
              />
            ))}
          </div>

          {/* Expand Icon */}
          <div className="text-gray-400">
            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </div>
        </div>
      </div>

      {/* EXPANDED VIEW */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t border-white/10"
          >
            <div className="p-4 space-y-4 bg-black/20">
              
              {/* Stats with Progress Bars + Traffic Lights */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 mb-3">📊 STATS (Last 30 Days)</h4>
                
                {/* Distance to ATH */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">Distance to ATH</span>
                    <span className="text-white font-bold">{distanceToATH}%</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-green-600 to-green-400"
                        style={{ width: `${distanceToATH}%` }}
                      />
                    </div>
                    <div className="flex gap-1">
                      {getTrafficLights(distanceToATH)}
                    </div>
                    <span className="text-xs font-bold text-green-400 w-16">
                      {getLabelForScore(distanceToATH, 'ath')}
                    </span>
                  </div>
                </div>

                {/* Entry Quality */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">Entry Quality (Earlier = Better)</span>
                    <span className="text-white font-bold">{entryQuality}%</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-green-600 to-green-400"
                        style={{ width: `${entryQuality}%` }}
                      />
                    </div>
                    <div className="flex gap-1">
                      {getTrafficLights(entryQuality)}
                    </div>
                    <span className="text-xs font-bold text-green-400 w-16">
                      {getLabelForScore(entryQuality, 'entry')}
                    </span>
                  </div>
                </div>

                {/* Consistency */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">Consistency (Lower = Better)</span>
                    <span className="text-white font-bold">{consistency}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-green-600 to-green-400"
                        style={{ width: `${(1 - consistency) * 100}%` }}
                      />
                    </div>
                    <div className="flex gap-1">
                      {getTrafficLights((1 - consistency) * 100)}
                    </div>
                    <span className="text-xs font-bold text-green-400 w-16">
                      {getLabelForScore(consistency, 'consistency')}
                    </span>
                  </div>
                </div>

                {/* Win Rate */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">Win Rate (&gt;3x ROI = Win)</span>
                    <span className="text-white font-bold">{winRate}%</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-green-600 to-green-400"
                        style={{ width: `${winRate}%` }}
                      />
                    </div>
                    <div className="flex gap-1">
                      {getTrafficLights(winRate)}
                    </div>
                    <span className="text-xs font-bold text-green-400 w-16">
                      {getLabelForScore(winRate, 'winrate')}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    ({Math.round(winRate * (wallet.runners_30d || 0) / 100)}/{wallet.runners_30d || 0})
                  </div>
                </div>
              </div>

              {/* Recent Form */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-semibold text-gray-400">🎯 RECENT FORM</h4>
                </div>
                <div className="flex items-center gap-2 text-2xl">
                  {(wallet.form || [{result: 'neutral'}, {result: 'neutral'}, {result: 'neutral'}, {result: 'neutral'}, {result: 'neutral'}]).slice(0, 10).map((f, i) => (
                    <span key={i}>
                      {f.result === 'win' ? '✅' : f.result === 'loss' ? '❌' : '⚪'}
                    </span>
                  ))}
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  (L = &lt;3x ROI, not actual loss)
                </div>
              </div>

              {/* Top 3 Runners */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 mb-2">💎 TOP 3 RUNNERS</h4>
                <div className="space-y-2">
                  {recentTrades.slice(0, 3).map((trade, i) => (
                    <div key={i} className="flex items-center justify-between text-xs bg-black/30 p-2 rounded">
                      <div className="flex items-center gap-2">
                        <span className="text-gray-500">{i + 1}.</span>
                        <span className="text-yellow-400 font-bold">${trade.token}</span>
                      </div>
                      <div className="text-gray-300">
                        Entry {trade.entry}% → Peak {trade.ath}% ({trade.distance}x)
                      </div>
                      <span className="text-green-400">✅</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Last Updated + Refresh */}
              <div className="flex items-center justify-between pt-2 border-t border-white/5">
                <span className="text-xs text-gray-500">
                  🗓️ Last Updated: {wallet.last_updated ? new Date(wallet.last_updated).toLocaleString() : 'Never'}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRefresh();
                  }}
                  disabled={isRefreshing}
                  className="flex items-center gap-1 px-3 py-1 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/30 rounded text-xs font-semibold transition"
                >
                  <RefreshCw size={12} className={isRefreshing ? 'animate-spin' : ''} />
                  Refresh Stats
                </button>
              </div>

            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}