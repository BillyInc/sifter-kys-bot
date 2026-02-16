import React, { useState } from 'react';
import { RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';
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

  const getLabelForScore = (value, type) => {
    if (type === 'ath') {
      // Distance to ATH: Higher = Better (big gap between entry and peak)
      if (value >= 50) return 'ELITE';
      if (value >= 30) return 'STRONG';
      if (value >= 10) return 'GOOD';
      return 'POOR';
    }
    if (type === 'entry') {
      // Entry Quality: Lower = Earlier = Better
      if (value <= 5) return 'EARLY';
      if (value <= 10) return 'GOOD';
      if (value <= 20) return 'LATE';
      return 'VERY LATE';
    }
    if (type === 'consistency') {
      // Consistency: Lower = Better
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

  // Real data from wallet object (ALL IN MULTIPLIERS)
  const distanceToATH = wallet.avg_distance_to_ath_multiplier || 0; // Multiplier: ATH - entry (e.g., 78.4x gap)
  const entryQuality = wallet.avg_entry_quality_multiplier || 0; // Multiplier: How many X from launch when entered (e.g., 5.2x)
  const consistency = wallet.consistency_score || 0; // 0-1 range (lower = better)
  const winRate7d = wallet.win_rate_7d || 0; // Percentage 0-100
  const winRate30d = wallet.win_rate_30d || 0; // Percentage 0-100
  const roi30dMultiplier = wallet.roi_30d_multiplier || 1; // Multiplier (e.g., 2.34x)
  const zone = wallet.zone || 'monitoring'; // Elite/midtable/monitoring/relegation

  // Top 3 runners from tokens_hit
  const topRunners = (wallet.tokens_hit || []).slice(0, 3);

  // Get zone styling
  const getZoneColor = (zone) => {
    switch(zone) {
      case 'Elite':
        return 'from-yellow-400 to-yellow-600 text-black';
      case 'midtable':
        return 'from-blue-500 to-blue-700 text-white';
      case 'monitoring':
        return 'from-orange-500 to-orange-700 text-white';
      case 'relegation':
        return 'from-red-500 to-red-700 text-white';
      default:
        return 'from-gray-500 to-gray-700 text-white';
    }
  };

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

              {/* Zone Badge */}
              <div className={`px-2 py-0.5 bg-gradient-to-r ${getZoneColor(zone)} rounded text-xs font-semibold shadow-lg`}>
                {zone.toUpperCase()}
              </div>

              {/* Position Change Indicator */}
              {wallet.movement !== 'stable' && wallet.positions_changed > 0 && (
                <div className={`text-xs font-bold ${
                  wallet.movement === 'up' ? 'text-green-400' : 'text-red-400'
                }`}>
                  {wallet.movement === 'up' ? '↑' : '↓'} {wallet.positions_changed}
                </div>
              )}
            </div>

            {/* Stats Row - COLLAPSED (4 STATS WITH MULTIPLIERS) */}
            <div className="flex items-center gap-3 text-xs">
              <div>
                <span className="text-gray-500">Score:</span>
                <span className="ml-1 text-white font-bold">{wallet.professional_score || 0}</span>
              </div>
              <div>
                <span className="text-gray-500">Avg distance to ATH:</span>
                <span className="ml-1 text-green-400 font-bold">{distanceToATH.toFixed(1)}x</span>
              </div>
              <div>
                <span className="text-gray-500">ROI:</span>
                <span className={`ml-1 font-bold ${
                  roi30dMultiplier >= 1 ? 'text-green-400' : 'text-red-400'
                }`}>
                  {roi30dMultiplier >= 1 ? '+' : ''}{((roi30dMultiplier - 1) * 100).toFixed(0)}%
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
            {(wallet.form || Array(5).fill({result: 'neutral'})).slice(0, 5).map((f, fi) => (
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
              
              {/* Stats with Progress Bars (ALL MULTIPLIERS) */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 mb-3">📊 STATS (Last 30 Days)</h4>
                
                {/* Distance to ATH Multiplier (ATH - Entry) */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">Avg Distance to ATH Multiplier (Entry → ATH Gap)</span>
                    <span className="text-white font-bold">{distanceToATH.toFixed(1)}x</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-green-600 to-green-400"
                        style={{ width: `${Math.min((distanceToATH / 100) * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs font-bold text-green-400 w-20 text-right">
                      {getLabelForScore(distanceToATH, 'ath')}
                    </span>
                  </div>
                </div>

                {/* Average Entry Quality (X from launch) */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">Average Entry Quality (Lower = Earlier)</span>
                    <span className="text-white font-bold">{entryQuality.toFixed(1)}x</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-green-600 to-green-400"
                        style={{ width: `${Math.max(100 - (entryQuality / 50) * 100, 0)}%` }}
                      />
                    </div>
                    <span className="text-xs font-bold text-green-400 w-20 text-right">
                      {getLabelForScore(entryQuality, 'entry')}
                    </span>
                  </div>
                </div>

                {/* Consistency (Lower = Better) */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">Consistency (Lower = Better)</span>
                    <span className="text-white font-bold">{consistency.toFixed(2)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-green-600 to-green-400"
                        style={{ width: `${Math.min((1 - Math.min(consistency, 1)) * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs font-bold text-green-400 w-20 text-right">
                      {getLabelForScore(consistency, 'consistency')}
                    </span>
                  </div>
                </div>

                {/* Win Rate 7d/30d (Percentage) */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">Win Rate (7d / 30d)</span>
                    <span className="text-white font-bold">{winRate7d.toFixed(0)}% / {winRate30d.toFixed(0)}%</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-green-600 to-green-400"
                        style={{ width: `${Math.min(winRate7d, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs font-bold text-green-400 w-20 text-right">
                      {getLabelForScore(winRate7d, 'winrate')}
                    </span>
                  </div>
                </div>

                {/* ROI 30d Multiplier */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">ROI 30d Multiplier</span>
                    <span className={`font-bold ${
                      roi30dMultiplier >= 1 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {roi30dMultiplier.toFixed(2)}x
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className={`h-full ${
                          roi30dMultiplier >= 1
                            ? 'bg-gradient-to-r from-green-600 to-green-400' 
                            : 'bg-gradient-to-r from-red-600 to-red-400'
                        }`}
                        style={{ width: `${Math.min(roi30dMultiplier * 50, 100)}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Recent Form */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 mb-2">🎯 RECENT FORM</h4>
                <div className="flex items-center gap-2">
                  {(wallet.form || Array(10).fill({result: 'neutral'})).slice(0, 10).map((f, i) => (
                    <span 
                      key={i}
                      className={`text-lg font-bold ${
                        f.result === 'win' ? 'text-green-400' :
                        f.result === 'loss' ? 'text-red-400' :
                        'text-gray-500'
                      }`}
                    >
                      {f.result === 'win' ? 'W' : f.result === 'loss' ? 'L' : 'D'}
                    </span>
                  ))}
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  (W = &gt;3x ROI, L = negative, D = 0-3x)
                </div>
              </div>

              {/* Top 3 Runners with Individual Stats (ALL MULTIPLIERS) */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 mb-2">💎 TOP 3 RUNNERS (Last 30d)</h4>
                {topRunners.length > 0 ? (
                  <div className="space-y-2">
                    {topRunners.map((runner, i) => {
                      // Parse runner data - match backend structure
                      const tokenSymbol = runner.symbol || runner.token || runner;
                      const entryPrice = runner.entry_price || 0;
                      const athPrice = runner.ath_price || 0;
                      const entryToAthMult = runner.entry_to_ath_multiplier || 
                                            (athPrice && entryPrice ? athPrice / entryPrice : 0);
                      const distancePct = runner.distance_to_ath_pct || 0;
                      
                      return (
                        <div key={i} className="flex items-center justify-between text-xs bg-black/30 p-2 rounded">
                          <div className="flex items-center gap-2 flex-1">
                            <span className="text-gray-500">{i + 1}.</span>
                            <span className="text-yellow-400 font-bold">${tokenSymbol}</span>
                          </div>
                          <div className="text-gray-300 text-right flex-1">
                            {entryPrice > 0 && athPrice > 0 ? (
                              <>Entry ${entryPrice.toFixed(6)} → ATH ${athPrice.toFixed(6)} ({entryToAthMult.toFixed(1)}x)</>
                            ) : (
                              <>ROI: {runner.roi_multiplier?.toFixed(1)}x</>
                            )}
                          </div>
                          <span className="text-green-400 ml-2">✅</span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-xs text-gray-500 text-center py-2">
                    No runners in last 30 days
                  </div>
                )}
              </div>

              {/* Degradation Alerts */}
              {wallet.degradation_alerts && wallet.degradation_alerts.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-gray-400 mb-2">⚠️ ALERTS</h4>
                  <div className="space-y-1">
                    {wallet.degradation_alerts.map((alert, i) => (
                      <div 
                        key={i} 
                        className={`text-xs p-2 rounded ${
                          alert.severity === 'red' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                          alert.severity === 'orange' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' :
                          'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                        }`}
                      >
                        <span className="font-semibold mr-1">
                          {alert.severity === 'red' ? '🔴' : alert.severity === 'orange' ? '🟠' : '🟡'}
                        </span>
                        {alert.message}
                      </div>
                    ))}
                  </div>
                </div>
              )}

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