// components/panels/ResultsPanel.jsx
import React, { useState } from 'react';
import {
  X, BookmarkPlus, TrendingUp, Zap, Search,
  BarChart3, ChevronDown, ChevronUp, Target,
  DollarSign, Activity, Trophy, Clock, Layers
} from 'lucide-react';

export default function ResultsPanel({
  data,
  onClose,
  onAddToWatchlist,
  resultType,
  formatNumber,
  formatPrice
}) {
  const [expandedWallets, setExpandedWallets] = useState({});

  const isBatch     = resultType?.includes('batch') || resultType === 'discovery';
  const isTrending  = resultType?.includes('trending');
  const isDiscovery = resultType === 'discovery';

  const getWallets = () => {
    if (!data) return [];
    if (data.wallets)             return data.wallets;
    if (data.smart_money_wallets) return data.smart_money_wallets;
    if (data.top_wallets)         return data.top_wallets;
    return Array.isArray(data) ? data : [];
  };

  const wallets = getWallets();

  const getSummary = () => {
    const sTier   = wallets.filter(w => w.tier === 'S').length;
    const aTier   = wallets.filter(w => w.tier === 'A').length;
    const avgScore = wallets.length
      ? Math.round(wallets.reduce((a, w) => a + (w.professional_score || w.avg_professional_score || 0), 0) / wallets.length)
      : 0;
    const avgDistATH = wallets.filter(w => w.distance_to_ath_pct).length
      ? (wallets.reduce((a, w) => a + (w.distance_to_ath_pct || 0), 0) / wallets.filter(w => w.distance_to_ath_pct).length).toFixed(1)
      : null;
    const token = data?.token;
    return { total: wallets.length, sTier, aTier, avgScore, avgDistATH, token };
  };

  const summary = getSummary();

  const toggleExpand = (idx) =>
    setExpandedWallets(prev => ({ ...prev, [idx]: !prev[idx] }));

  const getTierColors = (tier) => ({
    S: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40',
    A: 'bg-green-500/20 text-green-300 border-green-500/40',
    B: 'bg-blue-500/20 text-blue-300 border-blue-500/40',
    C: 'bg-gray-500/20 text-gray-300 border-gray-500/40',
  }[tier] || 'bg-gray-500/20 text-gray-300 border-gray-500/40');

  const getGradeColor = (grade) => {
    if (!grade) return 'text-gray-400';
    if (grade.startsWith('A')) return 'text-green-400';
    if (grade.startsWith('B')) return 'text-blue-400';
    if (grade.startsWith('C')) return 'text-yellow-400';
    return 'text-red-400';
  };

  const fmt = (v, suffix = '') => v != null ? `${Number(v).toFixed(1)}${suffix}` : '—';
  const fmtX = (v) => v != null ? `${Number(v).toFixed(1)}x` : '—';
  const fmtPct = (v) => v != null ? `${Number(v).toFixed(1)}%` : '—';
  const fmtUsd = (v) => v != null ? formatNumber(v) : '—';

  const renderWalletCard = (wallet, idx) => {
    const addr         = wallet.wallet || wallet.wallet_address || '';
    const score        = wallet.professional_score ?? wallet.avg_professional_score;
    const grade        = wallet.professional_grade;
    const tier         = wallet.tier;
    const roiPct       = wallet.roi_percent;
    const roiMult      = wallet.roi_multiplier;
    const totalMult    = wallet.total_multiplier;
    const distATH      = wallet.distance_to_ath_pct;
    const entryATHMult = wallet.entry_to_ath_multiplier;
    const entryPrice   = wallet.entry_price;
    const athPrice     = wallet.ath_price;
    const invested     = wallet.total_invested;
    const realized     = wallet.realized_profit;
    const unrealized   = wallet.unrealized_profit;
    const source       = wallet.source;
    const runners      = wallet.runner_hits_30d || 0;
    const winRate      = wallet.runner_success_rate;
    const runnerROI    = wallet.runner_avg_roi;
    const otherRunners = wallet.other_runners || [];
    const firstBuy     = wallet.first_buy_time;
    const runnersHit   = wallet.runners_hit || wallet.analyzed_tokens || [];
    const breakdown    = wallet.score_breakdown || {};
    const isExpanded   = expandedWallets[idx];

    return (
      <div
        key={addr + idx}
        className={`border rounded-xl transition-all duration-200 overflow-hidden ${
          tier === 'S' ? 'border-yellow-500/30 bg-yellow-500/5' :
          tier === 'A' ? 'border-green-500/20 bg-green-500/5' :
          'border-white/10 bg-white/3'
        }`}
      >
        {/* Card Header — always visible */}
        <div className="p-4">
          <div className="flex items-start justify-between gap-3">
            {/* Rank + address + badges */}
            <div className="flex items-center gap-3 flex-wrap flex-1 min-w-0">
              <span className={`text-lg font-black shrink-0 ${idx < 3 ? 'text-yellow-400' : 'text-gray-500'}`}>
                #{idx + 1}
              </span>
              <code className="text-sm font-mono bg-black/40 px-2 py-1 rounded text-gray-200 shrink-0">
                {addr.slice(0, 8)}…{addr.slice(-6)}
              </code>
              {tier && (
                <span className={`px-2 py-0.5 rounded border text-xs font-bold shrink-0 ${getTierColors(tier)}`}>
                  {tier}-Tier
                </span>
              )}
              {grade && (
                <span className={`text-sm font-bold shrink-0 ${getGradeColor(grade)}`}>{grade}</span>
              )}
              {source && (
                <span className="text-xs text-gray-500 bg-white/5 px-2 py-0.5 rounded shrink-0">{source}</span>
              )}
            </div>

            {/* Score + buttons */}
            <div className="flex items-center gap-2 shrink-0">
              {score != null && (
                <div className="text-right">
                  <div className={`text-xl font-black ${getGradeColor(grade)}`}>{Math.round(score)}</div>
                  <div className="text-[10px] text-gray-500 uppercase">Score</div>
                </div>
              )}
              <button
                onClick={() => onAddToWatchlist({
                  wallet_address: addr,
                  professional_score: score,
                  tier,
                  roi_percent: roiPct,
                  runner_hits_30d: runners,
                  runner_success_rate: winRate,
                  total_invested: invested,
                  runners_hit: runnersHit
                })}
                className="p-2 bg-purple-600 hover:bg-purple-500 rounded-lg transition"
                title="Add to watchlist"
              >
                <BookmarkPlus size={16} />
              </button>
              <button
                onClick={() => toggleExpand(idx)}
                className="p-2 bg-white/5 hover:bg-white/10 rounded-lg transition"
              >
                {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
            </div>
          </div>

          {/* Primary metrics row — always visible */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
            <div className="bg-black/30 rounded-lg p-2.5">
              <div className="flex items-center gap-1 text-[10px] text-gray-500 uppercase mb-1">
                <DollarSign size={10} /> ROI
              </div>
              <div className={`text-base font-bold ${(roiPct || 0) > 0 ? 'text-green-400' : 'text-red-400'}`}>
                {roiPct != null ? `${roiPct > 0 ? '+' : ''}${Number(roiPct).toFixed(1)}%` : '—'}
              </div>
              {roiMult != null && (
                <div className="text-xs text-gray-400">{fmtX(roiMult)} realized</div>
              )}
            </div>

            <div className="bg-black/30 rounded-lg p-2.5">
              <div className="flex items-center gap-1 text-[10px] text-gray-500 uppercase mb-1">
                <Target size={10} /> Dist to ATH
              </div>
              <div className="text-base font-bold text-purple-300">
                {distATH != null ? `${Number(distATH).toFixed(1)}%` : '—'}
              </div>
              {entryATHMult != null && (
                <div className="text-xs text-gray-400">{fmtX(entryATHMult)} entry→ATH</div>
              )}
            </div>

            <div className="bg-black/30 rounded-lg p-2.5">
              <div className="flex items-center gap-1 text-[10px] text-gray-500 uppercase mb-1">
                <TrendingUp size={10} /> Total Mult
              </div>
              <div className="text-base font-bold text-blue-300">
                {fmtX(totalMult)}
              </div>
              <div className="text-xs text-gray-400">incl. unrealized</div>
            </div>

            <div className="bg-black/30 rounded-lg p-2.5">
              <div className="flex items-center gap-1 text-[10px] text-gray-500 uppercase mb-1">
                <DollarSign size={10} /> Invested
              </div>
              <div className="text-base font-bold text-white">
                {fmtUsd(invested)}
              </div>
              {realized != null && (
                <div className="text-xs text-green-400">+{fmtUsd(realized)} realized</div>
              )}
            </div>
          </div>
        </div>

        {/* Expanded section */}
        {isExpanded && (
          <div className="border-t border-white/10 p-4 space-y-4 bg-black/20">

            {/* Score breakdown */}
            {(breakdown.entry_score != null || breakdown.realized_score != null) && (
              <div>
                <div className="text-xs text-gray-500 uppercase mb-2 font-semibold">Score Breakdown</div>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { label: 'Entry (60%)', val: breakdown.entry_score, color: 'purple' },
                    { label: 'Realized (30%)', val: breakdown.realized_score, color: 'green' },
                    { label: 'Total (10%)', val: breakdown.total_score, color: 'blue' },
                  ].map(({ label, val, color }) => (
                    <div key={label} className="bg-black/30 rounded-lg p-2">
                      <div className="text-[10px] text-gray-500 mb-1">{label}</div>
                      <div className={`text-lg font-bold text-${color}-400`}>
                        {val != null ? Number(val).toFixed(0) : '—'}
                      </div>
                      <div className="mt-1 h-1 rounded bg-white/10">
                        <div
                          className={`h-1 rounded bg-${color}-500`}
                          style={{ width: `${Math.min(100, val || 0)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Price details */}
            {(entryPrice || athPrice) && (
              <div>
                <div className="text-xs text-gray-500 uppercase mb-2 font-semibold">Price Details</div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                  {entryPrice != null && (
                    <div className="bg-black/30 rounded-lg p-2">
                      <div className="text-gray-500 mb-0.5">Entry Price</div>
                      <div className="font-mono text-white">{formatPrice(entryPrice)}</div>
                    </div>
                  )}
                  {athPrice != null && athPrice > 0 && (
                    <div className="bg-black/30 rounded-lg p-2">
                      <div className="text-gray-500 mb-0.5">Token ATH</div>
                      <div className="font-mono text-yellow-300">{formatPrice(athPrice)}</div>
                    </div>
                  )}
                  {unrealized != null && (
                    <div className="bg-black/30 rounded-lg p-2">
                      <div className="text-gray-500 mb-0.5">Unrealized</div>
                      <div className={`font-mono ${unrealized >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {fmtUsd(unrealized)}
                      </div>
                    </div>
                  )}
                  {firstBuy && (
                    <div className="bg-black/30 rounded-lg p-2">
                      <div className="text-gray-500 mb-0.5">First Buy</div>
                      <div className="font-mono text-gray-300 text-[10px]">
                        {new Date(firstBuy * 1000).toLocaleDateString()}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 30d Runner History */}
            <div>
              <div className="text-xs text-gray-500 uppercase mb-2 font-semibold flex items-center gap-2">
                <Activity size={11} /> 30-Day Runner History
              </div>
              <div className="grid grid-cols-3 gap-2 mb-3">
                <div className="bg-black/30 rounded-lg p-2 text-center">
                  <div className="text-lg font-bold text-yellow-400">{runners}</div>
                  <div className="text-[10px] text-gray-500">Runners Hit</div>
                </div>
                <div className="bg-black/30 rounded-lg p-2 text-center">
                  <div className="text-lg font-bold text-green-400">{winRate != null ? `${winRate}%` : '—'}</div>
                  <div className="text-[10px] text-gray-500">Win Rate</div>
                </div>
                <div className="bg-black/30 rounded-lg p-2 text-center">
                  <div className="text-lg font-bold text-blue-400">{runnerROI != null ? `${runnerROI}x` : '—'}</div>
                  <div className="text-[10px] text-gray-500">Avg ROI</div>
                </div>
              </div>

              {otherRunners.length > 0 && (
                <div className="space-y-1.5">
                  {otherRunners.map((r, ridx) => (
                    <div key={ridx} className="flex items-center justify-between bg-black/20 rounded-lg px-3 py-2 text-xs">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-white">{r.symbol || r.address?.slice(0, 8)}</span>
                        <span className="text-gray-500">{fmtX(r.multiplier)} runner</span>
                      </div>
                      <div className="flex items-center gap-3">
                        {r.entry_to_ath_multiplier && (
                          <span className="text-purple-300">{fmtX(r.entry_to_ath_multiplier)} entry→ATH</span>
                        )}
                        {r.roi_multiplier && (
                          <span className="text-green-400">{fmtX(r.roi_multiplier)} ROI</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Tokens / runners hit (batch mode) */}
            {runnersHit.length > 0 && (
              <div>
                <div className="text-xs text-gray-500 uppercase mb-2 font-semibold">
                  {isBatch ? 'Runners Hit' : 'Tokens Analyzed'}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {runnersHit.map((t, ti) => (
                    <span key={ti} className="text-xs px-2 py-1 bg-purple-500/15 text-purple-300 border border-purple-500/20 rounded-full">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  const headerColor =
    isDiscovery ? 'from-yellow-900/30 to-yellow-800/10 border-yellow-500/20' :
    isTrending  ? 'from-orange-900/30 to-orange-800/10 border-orange-500/20' :
                  'from-purple-900/30 to-purple-800/10 border-purple-500/20';

  const accentColor =
    isDiscovery ? 'text-yellow-400' :
    isTrending  ? 'text-orange-400' :
                  'text-purple-400';

  const titleIcon =
    isDiscovery ? <Zap className="text-yellow-400" size={22} /> :
    isTrending  ? <TrendingUp className="text-orange-400" size={22} /> :
                  <Search className="text-purple-400" size={22} />;

  const title =
    isDiscovery ? '⚡ Auto Discovery' :
    isBatch     ? '📊 Batch Analysis' :
                  '📊 Token Analysis';

  return (
    /* Full-screen overlay — sits above everything */
    <div className="fixed inset-0 z-[200] bg-black/95 backdrop-blur-sm flex flex-col">

      {/* ── Header ── */}
      <div className={`flex items-center justify-between px-6 py-4 bg-gradient-to-r ${headerColor} border-b border-white/10 shrink-0`}>
        <div className="flex items-center gap-3">
          {titleIcon}
          <div>
            <h2 className="text-xl font-bold">{title} Results</h2>
            {summary.token && (
              <p className="text-xs text-gray-400 mt-0.5">
                {summary.token.ticker || summary.token.symbol} — {summary.token.address?.slice(0, 12)}…
              </p>
            )}
          </div>
        </div>
        <button onClick={onClose} className="p-2 hover:bg-white/10 rounded-lg transition">
          <X size={22} />
        </button>
      </div>

      {/* ── Summary Stats ── */}
      <div className={`grid grid-cols-2 sm:grid-cols-5 gap-3 px-6 py-4 bg-gradient-to-r ${headerColor} border-b border-white/10 shrink-0`}>
        <div className="text-center">
          <div className={`text-2xl font-black ${accentColor}`}>{summary.total}</div>
          <div className="text-[11px] text-gray-400">Qualified</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-black text-yellow-400">{summary.sTier}</div>
          <div className="text-[11px] text-gray-400">S-Tier</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-black text-green-400">{summary.aTier}</div>
          <div className="text-[11px] text-gray-400">A-Tier</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-black text-blue-400">{summary.avgScore}</div>
          <div className="text-[11px] text-gray-400">Avg Score</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-black text-purple-400">
            {summary.avgDistATH != null ? `${summary.avgDistATH}%` : '—'}
          </div>
          <div className="text-[11px] text-gray-400">Avg Dist ATH</div>
        </div>
      </div>

      {/* ── Expand hint ── */}
      <div className="px-6 py-2 text-xs text-gray-600 shrink-0">
        Click <ChevronDown size={11} className="inline" /> on any wallet to see score breakdown, price details, and 30-day runner history.
      </div>

      {/* ── Wallet List ── */}
      <div className="flex-1 overflow-y-auto px-6 pb-6 space-y-3">
        {wallets.length === 0 ? (
          <div className="text-center py-20 text-gray-500">
            <BarChart3 size={56} className="mx-auto mb-4 opacity-20" />
            <p className="text-sm">No qualifying wallets found</p>
            <p className="text-xs mt-1 text-gray-600">Try lowering your ROI threshold</p>
          </div>
        ) : (
          wallets.map((wallet, idx) => renderWalletCard(wallet, idx))
        )}
      </div>

      {/* ── Batch Add Footer ── */}
      {wallets.length > 1 && (
        <div className="px-6 py-4 border-t border-white/10 bg-black/60 shrink-0">
          <button
            onClick={() => {
              if (window.confirm(`Add all ${wallets.length} wallets to your watchlist?`)) {
                wallets.forEach(w => onAddToWatchlist({
                  wallet_address: w.wallet || w.wallet_address,
                  professional_score: w.professional_score || w.avg_professional_score,
                  tier: w.tier,
                  roi_percent: w.roi_percent || w.avg_roi,
                  runner_hits_30d: w.runner_hits_30d || w.runner_count,
                  runner_success_rate: w.runner_success_rate,
                  total_invested: w.total_invested,
                  runners_hit: w.runners_hit || w.analyzed_tokens
                }));
              }
            }}
            className="w-full px-4 py-3 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 rounded-xl font-semibold transition flex items-center justify-center gap-2 shadow-lg shadow-purple-500/20"
          >
            <BookmarkPlus size={18} />
            Add All {wallets.length} Wallets to Watchlist
          </button>
        </div>
      )}
    </div>
  );
}