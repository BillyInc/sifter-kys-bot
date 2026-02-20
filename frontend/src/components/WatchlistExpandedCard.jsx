import React, { useState } from 'react';
import { RefreshCw, ChevronDown, ChevronUp, Trash2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export default function WatchlistExpandedCard({ 
  wallet, 
  rank, 
  onRefresh,
  onDelete,
  getTierColor 
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleRefresh = async (e) => {
    e.stopPropagation();
    setIsRefreshing(true);
    await onRefresh(wallet.wallet_address);
    setIsRefreshing(false);
  };

  const handleDelete = async (e) => {
    e.stopPropagation();
    if (!confirmDelete) {
      setConfirmDelete(true);
      setTimeout(() => setConfirmDelete(false), 3000);
      return;
    }
    setIsDeleting(true);
    await onDelete(wallet.wallet_address);
    setIsDeleting(false);
    setConfirmDelete(false);
  };

  const getLabelForScore = (value, type) => {
    if (type === 'ath') {
      if (value >= 50) return 'ELITE';
      if (value >= 30) return 'STRONG';
      if (value >= 10) return 'GOOD';
      return 'POOR';
    }
    if (type === 'entry') {
      if (value <= 5) return 'EARLY';
      if (value <= 10) return 'GOOD';
      if (value <= 20) return 'LATE';
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

  // ── Field mapping: support both watchlist-refresh fields AND raw analysis fields ──
  // Watchlist refresh fields (after /watchlist/refresh runs)
  const distanceToATH   = wallet.avg_distance_to_ath_multiplier
                        ?? wallet.distance_to_ath_pct          // from analysis result
                        ?? 0;
  const entryQuality    = wallet.avg_entry_quality_multiplier
                        ?? wallet.entry_to_ath_multiplier
                        ?? 0;
  const consistency     = wallet.consistency_score ?? 0;
  const winRate7d       = wallet.win_rate_7d ?? 0;
  const winRate30d      = wallet.win_rate_30d ?? 0;

  // ROI: stored as multiplier (1.0 = breakeven) OR as roi_percent (0 = breakeven)
  const roi30dMultiplier = wallet.roi_30d_multiplier
                         ?? (wallet.roi_percent != null ? 1 + wallet.roi_percent / 100 : 1);

  const score       = wallet.professional_score ?? wallet.avg_professional_score ?? 0;
  const zone        = wallet.zone ?? 'monitoring';
  const runners30d  = wallet.runners_30d ?? wallet.runner_hits_30d ?? 0;
  const topRunners  = (wallet.tokens_hit || wallet.runners_hit || []).slice(0, 3);
  const form        = wallet.form || Array(5).fill({ result: 'neutral' });

  const getZoneColor = (z) => ({
    Elite:      'from-yellow-400 to-yellow-600 text-black',
    midtable:   'from-blue-500 to-blue-700 text-white',
    monitoring: 'from-orange-500 to-orange-700 text-white',
    relegation: 'from-red-500 to-red-700 text-white',
  }[z] || 'from-gray-500 to-gray-700 text-white');

  const roiDisplay = roi30dMultiplier >= 1
    ? `+${((roi30dMultiplier - 1) * 100).toFixed(0)}%`
    : `${((roi30dMultiplier - 1) * 100).toFixed(0)}%`;

  return (
    <motion.div layout className="bg-black/30 border border-white/10 rounded-lg overflow-hidden">
      
      {/* ── COLLAPSED ROW ── */}
      <div
        className="p-3 hover:bg-white/5 transition cursor-pointer"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          {/* Rank */}
          <div className="w-8 text-center shrink-0">
            <span className={`font-bold ${
              rank === 1 ? 'text-yellow-400 text-lg' :
              rank === 2 ? 'text-gray-400 text-lg' :
              rank === 3 ? 'text-orange-400 text-lg' : 'text-gray-500'
            }`}>
              {rank <= 3 ? ['🥇','🥈','🥉'][rank-1] : `#${rank}`}
            </span>
          </div>

          {/* Address + badges */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <code className="text-sm font-mono text-gray-300">
                {wallet.wallet_address?.slice(0, 8)}...
              </code>
              <div className={`px-2 py-0.5 bg-gradient-to-r ${getTierColor(wallet.tier)} rounded text-xs font-bold text-white shadow-lg`}>
                {wallet.tier || 'C'}
              </div>
              <div className={`px-2 py-0.5 bg-gradient-to-r ${getZoneColor(zone)} rounded text-xs font-semibold shadow-lg`}>
                {zone.toUpperCase()}
              </div>
              {wallet.movement && wallet.movement !== 'stable' && wallet.positions_changed > 0 && (
                <div className={`text-xs font-bold ${wallet.movement === 'up' ? 'text-green-400' : 'text-red-400'}`}>
                  {wallet.movement === 'up' ? '↑' : '↓'} {wallet.positions_changed}
                </div>
              )}
            </div>

            <div className="flex items-center gap-3 text-xs flex-wrap">
              <div><span className="text-gray-500">Score:</span><span className="ml-1 text-white font-bold">{score}</span></div>
              <div><span className="text-gray-500">ATH dist:</span><span className="ml-1 text-green-400 font-bold">{Number(distanceToATH).toFixed(1)}x</span></div>
              <div><span className={`ml-1 font-bold ${roi30dMultiplier >= 1 ? 'text-green-400' : 'text-red-400'}`}>{roiDisplay}</span></div>
              <div><span className="text-gray-500">Runners:</span><span className="ml-1 text-yellow-400 font-bold">{runners30d}</span></div>
            </div>
          </div>

          {/* Form dots */}
          <div className="flex gap-1 shrink-0">
            {form.slice(0, 5).map((f, fi) => (
              <div key={fi} className={`w-2 h-2 rounded-full ${
                f.result === 'win' ? 'bg-green-500' : f.result === 'loss' ? 'bg-red-500' : 'bg-gray-600'
              }`} />
            ))}
          </div>

          {/* ── DELETE button — visible on collapsed row ── */}
          <button
            onClick={handleDelete}
            disabled={isDeleting}
            className={`shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition ${
              confirmDelete
                ? 'bg-red-600 hover:bg-red-700 text-white animate-pulse'
                : 'bg-white/5 hover:bg-red-500/20 text-gray-500 hover:text-red-400 border border-white/10 hover:border-red-500/30'
            } disabled:opacity-40`}
            title={confirmDelete ? 'Click again to confirm' : 'Remove from watchlist'}
          >
            <Trash2 size={12} className={isDeleting ? 'animate-spin' : ''} />
            <span className="hidden sm:inline">{confirmDelete ? 'Sure?' : 'Del'}</span>
          </button>

          {/* Expand chevron */}
          <div className="text-gray-500 shrink-0">
            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </div>
        </div>
      </div>

      {/* ── EXPANDED VIEW ── */}
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
              
              {/* Stats */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 mb-3">📊 STATS (Last 30 Days)</h4>
                
                {[
                  { label: 'Avg Distance to ATH', val: Number(distanceToATH).toFixed(1) + 'x', pct: Math.min((distanceToATH / 100) * 100, 100), type: 'ath' },
                  { label: 'Entry Quality (lower = earlier)', val: Number(entryQuality).toFixed(1) + 'x', pct: Math.max(100 - (entryQuality / 50) * 100, 0), type: 'entry' },
                  { label: 'Consistency (lower = better)', val: Number(consistency).toFixed(2), pct: Math.min((1 - Math.min(consistency, 1)) * 100, 100), type: 'consistency' },
                  { label: `Win Rate (7d / 30d)`, val: `${Number(winRate7d).toFixed(0)}% / ${Number(winRate30d).toFixed(0)}%`, pct: Math.min(winRate7d, 100), type: 'winrate' },
                ].map(({ label, val, pct, type }) => (
                  <div key={label} className="mb-3">
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="text-gray-400">{label}</span>
                      <span className="text-white font-bold">{val}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                        <div className="h-full bg-gradient-to-r from-green-600 to-green-400 transition-all" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="text-xs font-bold text-green-400 w-20 text-right">{getLabelForScore(
                        type === 'winrate' ? winRate7d :
                        type === 'ath' ? distanceToATH :
                        type === 'entry' ? entryQuality : consistency, type
                      )}</span>
                    </div>
                  </div>
                ))}

                {/* ROI */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">ROI 30d</span>
                    <span className={`font-bold ${roi30dMultiplier >= 1 ? 'text-green-400' : 'text-red-400'}`}>
                      {roi30dMultiplier.toFixed(2)}x
                    </span>
                  </div>
                  <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                    <div className={`h-full ${roi30dMultiplier >= 1 ? 'bg-gradient-to-r from-green-600 to-green-400' : 'bg-gradient-to-r from-red-600 to-red-400'}`}
                      style={{ width: `${Math.min(roi30dMultiplier * 50, 100)}%` }} />
                  </div>
                </div>
              </div>

              {/* Recent Form */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 mb-2">🎯 RECENT FORM</h4>
                <div className="flex items-center gap-2">
                  {form.slice(0, 10).map((f, i) => (
                    <span key={i} className={`text-lg font-bold ${
                      f.result === 'win' ? 'text-green-400' : f.result === 'loss' ? 'text-red-400' : 'text-gray-500'
                    }`}>
                      {f.result === 'win' ? 'W' : f.result === 'loss' ? 'L' : 'D'}
                    </span>
                  ))}
                </div>
                <div className="text-xs text-gray-500 mt-1">(W = &gt;3x ROI, L = negative, D = 0-3x)</div>
              </div>

              {/* Top Runners */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 mb-2">💎 TOP RUNNERS (Last 30d)</h4>
                {topRunners.length > 0 ? (
                  <div className="space-y-2">
                    {topRunners.map((runner, i) => {
                      const sym = runner.symbol || runner.token || runner;
                      const ep  = runner.entry_price || 0;
                      const ap  = runner.ath_price || 0;
                      const mult = runner.entry_to_ath_multiplier || (ap && ep ? ap / ep : 0);
                      return (
                        <div key={i} className="flex items-center justify-between text-xs bg-black/30 p-2 rounded">
                          <div className="flex items-center gap-2 flex-1">
                            <span className="text-gray-500">{i + 1}.</span>
                            <span className="text-yellow-400 font-bold">${sym}</span>
                          </div>
                          <div className="text-gray-300 text-right flex-1">
                            {ep > 0 && ap > 0
                              ? <>Entry ${ep.toFixed(6)} → ATH ${ap.toFixed(6)} ({mult.toFixed(1)}x)</>
                              : runner.roi_multiplier ? <>ROI: {runner.roi_multiplier.toFixed(1)}x</> : null
                            }
                          </div>
                          <span className="text-green-400 ml-2">✅</span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-xs text-gray-500 text-center py-2">No runners in last 30 days</div>
                )}
              </div>

              {/* Alerts */}
              {wallet.degradation_alerts?.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-gray-400 mb-2">⚠️ ALERTS</h4>
                  <div className="space-y-1">
                    {wallet.degradation_alerts.map((alert, i) => (
                      <div key={i} className={`text-xs p-2 rounded ${
                        alert.severity === 'red'    ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                        alert.severity === 'orange' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' :
                                                      'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                      }`}>
                        <span className="font-semibold mr-1">
                          {alert.severity === 'red' ? '🔴' : alert.severity === 'orange' ? '🟠' : '🟡'}
                        </span>
                        {alert.message}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Footer: last updated + refresh */}
              <div className="flex items-center justify-between pt-2 border-t border-white/5">
                <span className="text-xs text-gray-500">
                  🗓️ {wallet.last_updated ? new Date(wallet.last_updated).toLocaleString() : 'Never updated'}
                </span>
                <button
                  onClick={handleRefresh}
                  disabled={isRefreshing}
                  className="flex items-center gap-1 px-3 py-1 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/30 rounded text-xs font-semibold transition"
                >
                  <RefreshCw size={12} className={isRefreshing ? 'animate-spin' : ''} />
                  Refresh
                </button>
              </div>

            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}