// ResultsPanel.jsx — CENTERED MODAL VERSION with SELECTION and COMPACT EXPANDED VIEW
// - Added checkbox selection for wallets
// - Dynamic "Add Selected" button that updates with count
// - Compact footer with dynamic sizing based on expanded state
// - Full wallet addresses in collapsed view
// - Full token address in header with copy button
// - Enhanced "Other Runners" section with full token details
// - Increased panel height to 98vh
// - FIXED: Expanded view now fully visible without scrolling

import React, { useState, useEffect } from 'react';
import { BookmarkPlus, BarChart3, ChevronDown, ChevronUp, Copy, CheckSquare, Square, TrendingUp, Award, ExternalLink } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// ── Formatters ────────────────────────────────────────────────────────────────
const fmtMcap = (v) => {
  if (v == null || v === 0) return '—';
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${Number(v).toFixed(0)}`;
};

const fmtUsd = (v) => {
  if (v == null || v === 0) return '$0.00';
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(2)}K`;
  return `$${Number(v).toFixed(2)}`;
};

const fmtX = (v) => v != null && !isNaN(v) ? `${Number(v).toFixed(2)}x` : '—';
const fmtPct = (v) => v != null && !isNaN(v) ? `${v > 0 ? '+' : ''}${Number(v).toFixed(2)}%` : '—';

// ── StatBar ───────────────────────────────────────────────────────────────────
const StatBar = ({ label, val, pct, color = '#3b82f6' }) => (
  <div style={{ marginBottom: 8 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
      <span style={{
        fontSize: 9, color: '#9aa4b8', fontFamily: 'monospace',
        textTransform: 'uppercase', letterSpacing: '0.08em',
      }}>
        {label}
      </span>
      <span style={{ fontSize: 10, color, fontFamily: 'monospace', fontWeight: 700 }}>
        {val}
      </span>
    </div>
    <div style={{ height: 2, background: '#28303f', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{
        height: '100%',
        width: `${Math.max(0, Math.min(100, pct || 0))}%`,
        background: `linear-gradient(90deg, ${color}88, ${color})`,
        borderRadius: 2,
        transition: 'width 0.5s ease',
      }} />
    </div>
  </div>
);

// ── Helpers ───────────────────────────────────────────────────────────────────
const gradeColor = (grade) => {
  if (!grade) return '#7c879c';
  if (grade.startsWith('A')) return '#22c55e';
  if (grade.startsWith('B')) return '#3b82f6';
  if (grade.startsWith('C')) return '#eab308';
  return '#ef4444';
};

const TIER_COLORS = {
  S: { text: '#eab308', bg: 'rgba(234,179,8,0.15)', border: 'rgba(234,179,8,0.3)' },
  A: { text: '#22c55e', bg: 'rgba(34,197,94,0.15)', border: 'rgba(34,197,94,0.3)' },
  B: { text: '#3b82f6', bg: 'rgba(59,130,246,0.15)', border: 'rgba(59,130,246,0.3)' },
  C: { text: '#7c879c', bg: 'rgba(124,135,156,0.12)', border: 'rgba(124,135,156,0.2)' },
};

// ─────────────────────────────────────────────────────────────────────────────
export default function ResultsPanel({
  data,
  onClose,
  onAddToWatchlist,
  resultType,
  formatNumber,
  formatPrice,
}) {
  const [expandedWallets, setExpandedWallets] = useState({});
  const [selectedWallets, setSelectedWallets] = useState(new Set());
  const [copiedAddress, setCopiedAddress] = useState(null);
  const [copiedTokenAddress, setCopiedTokenAddress] = useState(null);
  const [copiedRunnerAddress, setCopiedRunnerAddress] = useState(null);

  const isBatch = resultType?.includes('batch') || resultType === 'discovery';
  const isTrending = resultType?.includes('trending');
  const isDiscovery = resultType === 'discovery';

  // Check if any wallet is expanded
  const hasExpanded = Object.values(expandedWallets).some(Boolean);

  // Handle Escape key
  useEffect(() => {
    const handleEsc = (e) => {
      if (e.key === 'Escape') {
        setSelectedWallets(new Set());
        onClose();
      }
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const copyToClipboard = (addr, type = 'wallet') => {
    navigator.clipboard?.writeText(addr);
    if (type === 'wallet') {
      setCopiedAddress(addr);
      setTimeout(() => setCopiedAddress(null), 2000);
    } else if (type === 'token') {
      setCopiedTokenAddress(addr);
      setTimeout(() => setCopiedTokenAddress(null), 2000);
    } else {
      setCopiedRunnerAddress(addr);
      setTimeout(() => setCopiedRunnerAddress(null), 2000);
    }
  };

  // ── Wallet extraction ───────────────────────────────────────────────────────
  const getWallets = () => {
    if (!data) return [];
    const found = data.wallets ?? data.smart_money_wallets ?? data.top_wallets;
    if (Array.isArray(found)) return found;
    if (Array.isArray(data)) return data;
    return [];
  };

  const wallets = getWallets();

  // Selection handlers
  const toggleSelectWallet = (addr, e) => {
    e.stopPropagation();
    setSelectedWallets(prev => {
      const newSet = new Set(prev);
      if (newSet.has(addr)) {
        newSet.delete(addr);
      } else {
        newSet.add(addr);
      }
      return newSet;
    });
  };

  const toggleSelectAll = () => {
    if (selectedWallets.size === wallets.length) {
      setSelectedWallets(new Set());
    } else {
      setSelectedWallets(new Set(wallets.map(w => w.wallet || w.wallet_address)));
    }
  };

  const addSelectedToWatchlist = () => {
    const selected = wallets.filter(w =>
      selectedWallets.has(w.wallet || w.wallet_address)
    );

    if (selected.length === 0) return;

    if (selected.length === 1 || window.confirm(`Add ${selected.length} selected wallets to your watchlist?`)) {
      selected.forEach(w => onAddToWatchlist({
        wallet_address: w.wallet || w.wallet_address,
        professional_score: w.professional_score ?? w.avg_professional_score,
        tier: w.tier,
        roi_percent: w.roi_percent ?? w.avg_roi,
        runner_hits_30d: w.runner_hits_30d ?? w.runner_count,
        runner_success_rate: w.runner_success_rate,
        total_invested: w.total_invested_sum ?? w.total_invested,
        runners_hit: w.runners_hit ?? w.analyzed_tokens ?? [],
        other_runners: w.other_runners || [],
      }));
    }
  };

  const summary = {
    total: wallets.length,
    sTier: wallets.filter(w => w.tier === 'S').length,
    aTier: wallets.filter(w => w.tier === 'A').length,
    token: data?.token,
    tokensAnalyzed: data?.tokens_analyzed || data?.tokens_analyzed_list?.length || null,
  };

  const toggleExpand = (idx) =>
    setExpandedWallets(prev => ({ ...prev, [idx]: !prev[idx] }));

  const titleText =
    isDiscovery ? '⚡ Auto Discovery' :
      isBatch ? '📊 Batch Analysis' :
        '📊 Token Analysis';

  // ── Column templates ─────────────────────────────────────────────────────
  const colTemplate = isBatch
    ? '30px 40px minmax(280px, 2.5fr) 50px 60px 110px 110px 95px 70px 80px 90px'
    : '30px 40px minmax(280px, 3fr) 50px 60px 110px 110px 95px 70px 90px';

  // ── Per-wallet card ─────────────────────────────────────────────────────────
  const renderWalletCard = (wallet, idx) => {
    const addr = wallet.wallet || wallet.wallet_address || '';
    const score = wallet.professional_score ?? wallet.avg_professional_score ?? 0;
    const grade = wallet.professional_grade;
    const tier = wallet.tier;
    const tc = TIER_COLORS[tier] || TIER_COLORS.C;

    const entryATHMult = isBatch
      ? (wallet.avg_entry_to_ath_multiplier ?? wallet.entry_to_ath_multiplier)
      : wallet.entry_to_ath_multiplier;

    const distATH = isBatch
      ? (wallet.avg_distance_to_ath_pct ?? wallet.distance_to_ath_pct)
      : wallet.distance_to_ath_pct;

    const totalMult = isBatch
      ? (wallet.avg_total_roi ?? wallet.total_multiplier)
      : wallet.total_multiplier;

    const roiPct = isBatch
      ? (totalMult != null ? ((totalMult - 1) * 100) : null)
      : wallet.roi_percent;

    const totalInvested = isBatch
      ? (wallet.total_invested_sum ?? wallet.total_invested)
      : wallet.total_invested;

    const totalRealized = isBatch
      ? (wallet.total_realized_sum ?? wallet.realized_profit)
      : wallet.realized_profit;

    const avgInvested = isBatch
      ? (wallet.avg_invested ?? (
        wallet.total_invested_sum && wallet.runner_count
          ? wallet.total_invested_sum / wallet.runner_count
          : wallet.total_invested
      ))
      : null;

    const avgRealized = isBatch
      ? (wallet.avg_realized ?? (
        wallet.total_realized_sum && wallet.runner_count
          ? wallet.total_realized_sum / wallet.runner_count
          : null
      ))
      : null;

    const unrealized = wallet.unrealized_profit;
    const consistency = wallet.consistency_score;
    const runnerCount = wallet.runner_count || (wallet.runners_hit?.length) || 0;
    const runnersHit = wallet.runners_hit || wallet.analyzed_tokens || [];
    const runners30d = wallet.runner_hits_30d || 0;
    const winRate = wallet.runner_success_rate;
    const runnerROI = wallet.runner_avg_roi;
    const otherRunners = wallet.other_runners || [];
    const firstBuy = wallet.first_buy_time;
    const breakdown = wallet.score_breakdown || {};

    const entryMcap = wallet.entry_market_cap;
    const athMcap = wallet.ath_market_cap;
    const entryPrice = wallet.entry_price;
    const athPrice = wallet.ath_price;

    const isExpanded = expandedWallets[idx];
    const rankDisplay = idx < 3 ? ['🥇', '🥈', '🥉'][idx] : `#${idx + 1}`;
    const fmtUsd = (v) => (v != null ? formatNumber(v) : '—');
    const isSelected = selectedWallets.has(addr);

    return (
      <div
        key={addr + idx}
        style={{
          borderBottom: '1px solid #242b3a',
          borderLeft: tier === 'S'
            ? '2px solid rgba(234,179,8,0.5)'
            : tier === 'A'
              ? '2px solid rgba(34,197,94,0.4)'
              : '2px solid transparent',
          background: isSelected ? 'rgba(124,58,237,0.05)' : 'transparent',
        }}
      >
        {/* ── COLLAPSED ROW ─────────────────────────────────────────────── */}
        <div
          onClick={() => toggleExpand(idx)}
          style={{
            display: 'grid',
            gridTemplateColumns: colTemplate,
            gap: 8,
            alignItems: 'center',
            padding: '10px 20px',
            cursor: 'pointer',
            background: isExpanded ? 'rgba(124,58,237,0.08)' : 'transparent',
            transition: 'background 0.15s',
          }}
          onMouseEnter={e => { if (!isExpanded) e.currentTarget.style.background = 'rgba(124,58,237,0.03)'; }}
          onMouseLeave={e => { if (!isExpanded && !isSelected) e.currentTarget.style.background = 'transparent'; }}
        >
          {/* Checkbox */}
          <div style={{ textAlign: 'center' }} onClick={e => e.stopPropagation()}>
            <button
              onClick={(e) => toggleSelectWallet(addr, e)}
              style={{
                background: 'none',
                border: 'none',
                padding: 4,
                color: isSelected ? '#a855f7' : '#5d6a81',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {isSelected ? <CheckSquare size={16} /> : <Square size={16} />}
            </button>
          </div>

          {/* Rank */}
          <div style={{
            fontFamily: 'monospace',
            fontSize: idx < 3 ? 15 : 12,
            color: '#7c879c',
            textAlign: 'center',
          }}>
            {rankDisplay}
          </div>

          {/* Address - FULL ADDRESS */}
          <div style={{
            fontFamily: 'monospace',
            fontSize: 12,
            color: '#e2e8f0',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            overflow: 'hidden',
          }}>
            <span style={{
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {addr}
            </span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                copyToClipboard(addr, 'wallet');
              }}
              style={{
                background: 'none',
                border: 'none',
                padding: 2,
                color: copiedAddress === addr ? '#22c55e' : '#7c879c',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
              title="Copy address"
            >
              <Copy size={12} />
            </button>
          </div>

          {/* Tier badge */}
          <div style={{ textAlign: 'center' }}>
            <span style={{
              display: 'inline-block', padding: '2px 6px', borderRadius: 3,
              fontSize: 10, fontWeight: 700, fontFamily: 'monospace',
              color: tc.text, background: tc.bg, border: `1px solid ${tc.border}`,
            }}>
              {tier || 'C'}
            </span>
          </div>

          {/* Score */}
          <div style={{
            fontFamily: 'monospace', fontSize: 14, fontWeight: 700,
            color: gradeColor(grade), textAlign: 'right',
          }}>
            {Math.round(score)}
          </div>

          {/* Entry → ATH */}
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: '#a855f7' }}>
              {fmtX(entryATHMult)}
            </div>
            <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#7c879c' }}>
              {isBatch ? 'avg ' : ''}{fmtPct(distATH)} from ATH
            </div>
          </div>

          {/* Total ROI */}
          <div style={{ textAlign: 'right' }}>
            <div style={{
              fontFamily: 'monospace', fontSize: 13, fontWeight: 700,
              color: (totalMult || 0) >= 1 ? '#22c55e' : '#ef4444',
            }}>
              {fmtX(totalMult)}
            </div>
            <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#7c879c' }}>
              {roiPct != null
                ? `${roiPct > 0 ? '+' : ''}${Number(roiPct).toFixed(1)}%`
                : '—'}
            </div>
          </div>

          {/* Total Invested */}
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: '#f1f5f9' }}>
              {fmtUsd(totalInvested)}
            </div>
            <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#7c879c' }}>
              {isBatch ? 'total' : 'invested'}
            </div>
          </div>

          {/* Tokens — batch only */}
          {isBatch && (
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: '#eab308' }}>
                {runnerCount}
                <span style={{ fontSize: 8, color: '#7c879c' }}>/{summary.tokensAnalyzed || '?'}</span>
              </div>
              <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#7c879c' }}>tokens</div>
            </div>
          )}

          {/* Avg Consistency — batch only */}
          {isBatch && (
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: '#a855f7' }}>
                {consistency != null ? Number(consistency).toFixed(0) : '—'}
              </div>
              <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#7c879c' }}>consist.</div>
            </div>
          )}

          {/* Actions */}
          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onAddToWatchlist({
                  wallet_address: addr,
                  professional_score: score,
                  tier,
                  roi_percent: roiPct,
                  runner_hits_30d: runners30d,
                  runner_success_rate: winRate,
                  total_invested: totalInvested,
                  runners_hit: runnersHit,
                  other_runners: otherRunners,
                });
              }}
              style={{
                padding: '4px 8px',
                borderRadius: 4,
                border: 'none',
                background: 'rgba(168,85,247,0.15)',
                color: '#a855f7',
                fontSize: 10,
                fontFamily: 'monospace',
                fontWeight: 700,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                minWidth: '36px',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(168,85,247,0.25)'}
              onMouseLeave={e => e.currentTarget.style.background = 'rgba(168,85,247,0.15)'}
              title="Add to watchlist"
            >
              +WL
            </button>
            <div style={{ color: '#7c879c', lineHeight: 1, flexShrink: 0 }}>
              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </div>
          </div>
        </div>

        {/* ── EXPANDED PANEL ─────────────────────────────────────────────────── */}
        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.18 }}
              style={{ overflow: 'hidden' }}
            >
              <div style={{
                background: '#141b29',
                borderTop: '1px solid #2a3344',
                borderBottom: '1px solid #1f2838',
                padding: '16px 20px',
                display: 'grid',
                gridTemplateColumns: '1.1fr 1.2fr 0.9fr',
                gap: 20,
              }}>
                {/* Col 1: Score breakdown + Price/MCap */}
                <div>
                  <div style={{
                    fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase',
                    letterSpacing: '0.1em', color: '#9aa4b8', marginBottom: 12,
                    fontWeight: 500,
                  }}>
                    ● Score Breakdown
                  </div>

                  <StatBar
                    label="Entry Timing (60%)"
                    val={breakdown.entry_score != null ? Number(breakdown.entry_score).toFixed(0) : '—'}
                    pct={breakdown.entry_score}
                    color="#a855f7"
                  />
                  <StatBar
                    label="Total ROI (30%)"
                    val={breakdown.total_roi_score != null ? Number(breakdown.total_roi_score).toFixed(0) : '—'}
                    pct={breakdown.total_roi_score}
                    color="#22c55e"
                  />
                  {isBatch ? (
                    <StatBar
                      label="Avg Consistency (10%)"
                      val={breakdown.consistency_score != null ? Number(breakdown.consistency_score).toFixed(0) : '—'}
                      pct={breakdown.consistency_score}
                      color="#3b82f6"
                    />
                  ) : (
                    <StatBar
                      label="Realized ROI (10%)"
                      val={breakdown.realized_score != null ? Number(breakdown.realized_score).toFixed(0) : '—'}
                      pct={breakdown.realized_score}
                      color="#3b82f6"
                    />
                  )}

                  <div style={{
                    fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase',
                    letterSpacing: '0.1em', color: '#9aa4b8',
                    marginTop: 16, marginBottom: 10, fontWeight: 500,
                  }}>
                    ● Market Cap at Entry / ATH
                  </div>

                  <div style={{
                    display: 'flex', justifyContent: 'space-between',
                    padding: '6px 10px', marginBottom: 6, borderRadius: 4,
                    background: 'rgba(168,85,247,0.08)', border: '1px solid rgba(168,85,247,0.2)',
                  }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#9aa4b8', textTransform: 'uppercase', alignSelf: 'center' }}>
                      Entry MCap
                    </span>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: '#f1f5f9' }}>
                        {fmtMcap(entryMcap)}
                      </div>
                      <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#9aa4b8' }}>
                        {entryPrice ? formatPrice(entryPrice) : '—'}
                      </div>
                    </div>
                  </div>

                  <div style={{
                    display: 'flex', justifyContent: 'space-between',
                    padding: '6px 10px', borderRadius: 4,
                    background: 'rgba(234,179,8,0.08)', border: '1px solid rgba(234,179,8,0.2)',
                  }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#9aa4b8', textTransform: 'uppercase', alignSelf: 'center' }}>
                      ATH MCap
                    </span>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: '#eab308' }}>
                        {fmtMcap(athMcap)}
                      </div>
                      <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#9aa4b8' }}>
                        {athPrice ? formatPrice(athPrice) : '—'}
                      </div>
                    </div>
                  </div>

                  {firstBuy && (
                    <div style={{ marginTop: 8, fontFamily: 'monospace', fontSize: 9, color: '#5d6a81' }}>
                      First buy: {new Date(firstBuy * 1000).toLocaleDateString()}
                    </div>
                  )}
                </div>

                {/* Col 2: PnL breakdown + 30d runner stats summary */}
                <div>
                  <div style={{
                    fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase',
                    letterSpacing: '0.1em', color: '#9aa4b8', marginBottom: 12, fontWeight: 500,
                  }}>
                    ● PnL Breakdown
                  </div>

                  {isBatch ? (
                    <>
                      <StatBar label="Total Realized (all tokens)" val={fmtUsd(totalRealized)}
                        pct={totalRealized && totalInvested ? Math.min((totalRealized / totalInvested) * 20, 100) : 0} color="#22c55e" />
                      <StatBar label="Total Invested (all tokens)" val={fmtUsd(totalInvested)} pct={50} color="#7c879c" />
                      {avgInvested != null && (
                        <StatBar label="Avg Invested / Token" val={fmtUsd(avgInvested)} pct={35} color="#5d6a81" />
                      )}
                      {avgRealized != null && (
                        <StatBar label="Avg Realized / Token" val={fmtUsd(avgRealized)}
                          pct={avgRealized && avgInvested ? Math.min((avgRealized / avgInvested) * 20, 100) : 0} color="#16a34a" />
                      )}
                    </>
                  ) : (
                    <>
                      <StatBar label="Realized" val={fmtUsd(totalRealized)}
                        pct={totalRealized && totalInvested ? Math.min((totalRealized / totalInvested) * 20, 100) : 0} color="#22c55e" />
                      <StatBar label="Unrealized" val={fmtUsd(unrealized)}
                        pct={unrealized && totalInvested ? Math.min(Math.abs(unrealized / totalInvested) * 20, 100) : 0}
                        color={unrealized >= 0 ? '#3b82f6' : '#ef4444'} />
                      <StatBar label="Invested" val={fmtUsd(totalInvested)} pct={50} color="#7c879c" />
                    </>
                  )}

                  <div style={{
                    fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase',
                    letterSpacing: '0.1em', color: '#9aa4b8', marginTop: 16, marginBottom: 10, fontWeight: 500,
                  }}>
                    ● 30-Day Runner Summary
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 8 }}>
                    {[
                      { label: 'Runners Hit', val: runners30d, color: '#eab308' },
                      { label: 'Win Rate (5x+)', val: winRate != null ? `${winRate}%` : '—', color: winRate >= 50 ? '#22c55e' : '#ef4444' },
                      { label: 'Avg ROI', val: runnerROI != null ? `${runnerROI}x` : '—', color: '#3b82f6' },
                      { label: 'Grade', val: grade || '—', color: gradeColor(grade) },
                    ].map(({ label, val, color }) => (
                      <div key={label} style={{
                        padding: '4px 8px', borderRadius: 4,
                        background: '#1a2232', border: '1px solid #28303f',
                      }}>
                        <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#9aa4b8', textTransform: 'uppercase', marginBottom: 2 }}>
                          {label}
                        </div>
                        <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color }}>
                          {val}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Col 3: Detailed Other Runners (30-Day Runner Stats) */}
                <div>
                  <div style={{
                    fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase',
                    letterSpacing: '0.1em', color: '#9aa4b8', marginBottom: 12, fontWeight: 500,
                    display: 'flex', alignItems: 'center', gap: 6
                  }}>
                    <TrendingUp size={13} color="#eab308" />
                    ● Other Runners (Last 30 Days)
                    <span style={{ color: '#eab308', marginLeft: 'auto', fontSize: 10 }}>
                      {otherRunners.length} tokens
                    </span>
                  </div>

                  {otherRunners.length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 280, overflowY: 'auto', paddingRight: 4 }}>
                      {otherRunners.map((r, ridx) => {
                        const entryToAth = r.entry_to_ath_multiplier || r.multiplier || 0;
                        const totalProfit = r.total_multiplier || r.profit_multiplier || 0;
                        const invested = r.invested_amount || r.invested || 0;
                        const returned = r.returned_amount || (invested * totalProfit) || 0;
                        const profitPct = invested > 0 ? ((returned - invested) / invested) * 100 : 0;
                        const isWin = totalProfit >= 5;

                        return (
                          <div key={ridx} style={{
                            padding: '8px 10px',
                            borderRadius: 4,
                            background: isWin ? 'rgba(34,197,94,0.06)' : '#1a2232',
                            border: `1px solid ${isWin ? 'rgba(34,197,94,0.2)' : '#28303f'}`,
                          }}>
                            {/* Token header with ticker and address */}
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: '#eab308' }}>
                                  ${r.symbol || r.ticker || '???'}
                                </span>
                                <span style={{
                                  fontSize: 8, padding: '2px 4px', borderRadius: 2,
                                  background: isWin ? 'rgba(34,197,94,0.15)' : 'rgba(124,135,156,0.15)',
                                  color: isWin ? '#22c55e' : '#9aa4b8',
                                  fontWeight: 600
                                }}>
                                  {isWin ? 'WINNER' : 'miss'}
                                </span>
                              </div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                <span style={{ fontFamily: 'monospace', fontSize: 8, color: '#5d6a81' }}>
                                  {r.address?.slice(0, 4)}...{r.address?.slice(-4)}
                                </span>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    copyToClipboard(r.address, 'runner');
                                  }}
                                  style={{
                                    background: 'none',
                                    border: 'none',
                                    padding: 2,
                                    color: copiedRunnerAddress === r.address ? '#22c55e' : '#7c879c',
                                    cursor: 'pointer',
                                  }}
                                >
                                  <Copy size={9} />
                                </button>
                              </div>
                            </div>

                            {/* Stats grid */}
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                              {/* Entry MCap */}
                              <div>
                                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase' }}>
                                  Entry MCap
                                </div>
                                <div style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 600, color: '#f1f5f9' }}>
                                  {fmtMcap(r.entry_market_cap)}
                                </div>
                              </div>

                              {/* Entry→ATH Mult */}
                              <div>
                                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase' }}>
                                  Entry→ATH
                                </div>
                                <div style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 600, color: '#a855f7' }}>
                                  {fmtX(entryToAth)}
                                </div>
                              </div>

                              {/* Total Profit Mult */}
                              <div>
                                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase' }}>
                                  Total Profit
                                </div>
                                <div style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 600, color: totalProfit >= 5 ? '#22c55e' : '#ef4444' }}>
                                  {fmtX(totalProfit)}
                                </div>
                              </div>

                              {/* Invested / Return */}
                              <div>
                                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase' }}>
                                  Invested / Return
                                </div>
                                <div style={{ fontFamily: 'monospace', fontSize: 9, fontWeight: 600, color: '#f1f5f9' }}>
                                  {fmtUsd(invested)} → {fmtUsd(returned)}
                                </div>
                              </div>

                              {/* ROI % */}
                              <div style={{ gridColumn: 'span 2' }}>
                                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase' }}>
                                  ROI %
                                </div>
                                <div style={{
                                  fontFamily: 'monospace', fontSize: 10, fontWeight: 700,
                                  color: profitPct > 0 ? '#22c55e' : '#ef4444'
                                }}>
                                  {fmtPct(profitPct)}
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div style={{
                      padding: '20px 12px',
                      background: '#1a2232',
                      borderRadius: 4,
                      border: '1px dashed #28303f',
                      textAlign: 'center'
                    }}>
                      <TrendingUp size={20} style={{ color: '#3f4a5c', marginBottom: 6 }} />
                      <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#7c879c' }}>
                        No other runners in last 30 days
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  };

  // ── MAIN RENDER ─────────────────────────────────────────────────────────────
  const selectedCount = selectedWallets.size;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 200,
        background: 'rgba(0, 0, 0, 0.75)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '12px 12px',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        width: '100%',
        maxWidth: 1200,
        height: '98vh',
        background: '#0b0f17',
        borderRadius: 12,
        border: '1px solid #242b3a',
        boxShadow: '0 25px 50px -12px rgba(0,0,0,0.8), 0 0 0 1px rgba(124,58,237,0.15)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}>
        {/* Header with FULL TOKEN ADDRESS */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 20px',
          background: '#1e1b2e',
          borderBottom: '1px solid #2d2642',
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div>
              <div style={{ fontFamily: 'monospace', fontSize: 16, fontWeight: 700, color: '#ffffff', letterSpacing: '0.02em' }}>
                {titleText} Results
              </div>
              {summary.token && (
                <div style={{
                  fontFamily: 'monospace',
                  fontSize: 11,
                  color: '#9aa4b8',
                  marginTop: 2,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6
                }}>
                  {summary.token.ticker || summary.token.symbol}{' — '}
                  <span style={{ color: '#a78bfa' }} title={summary.token.address}>
                    {summary.token.address}
                  </span>
                  <button
                    onClick={() => {
                      navigator.clipboard?.writeText(summary.token.address);
                      setCopiedTokenAddress(summary.token.address);
                      setTimeout(() => setCopiedTokenAddress(null), 2000);
                    }}
                    style={{
                      background: 'none',
                      border: 'none',
                      padding: 2,
                      color: copiedTokenAddress === summary.token.address ? '#22c55e' : '#7c879c',
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                    }}
                    title="Copy token address"
                  >
                    <Copy size={11} />
                  </button>
                </div>
              )}
              {isBatch && summary.tokensAnalyzed && (
                <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#9aa4b8', marginTop: 2 }}>
                  {summary.tokensAnalyzed} tokens analyzed
                </div>
              )}
            </div>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setSelectedWallets(new Set());
              onClose();
            }}
            style={{
              width: 32, height: 32, borderRadius: 6,
              border: '1px solid #3d2d3a',
              background: 'rgba(239,68,68,0.15)', color: '#f87171',
              fontSize: 16, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.25)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(239,68,68,0.15)'}
          >
            ✕
          </button>
        </div>

        {/* Summary stats - compact */}
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 1, background: '#3a2d22',
          borderBottom: '1px solid #3a2d22',
          flexShrink: 0,
        }}>
          {[
            { label: 'Qualified', val: summary.total, color: '#f97316' },
            { label: 'S-Tier', val: summary.sTier, color: '#eab308' },
            { label: 'A-Tier', val: summary.aTier, color: '#22c55e' },
          ].map(({ label, val, color }, i) => (
            <div key={label} style={{
              padding: '8px 12px',
              background: '#281f16',
              textAlign: 'center',
              borderRight: i < 2 ? '1px solid #3a2d22' : 'none',
            }}>
              <div style={{ fontFamily: 'monospace', fontSize: 22, fontWeight: 900, color }}>
                {val}
              </div>
              <div style={{
                fontFamily: 'monospace', fontSize: 9, color: '#b3967a',
                textTransform: 'uppercase', letterSpacing: '0.1em', marginTop: 2,
              }}>
                {label}
              </div>
            </div>
          ))}
        </div>

        {/* Column headers with select all */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: colTemplate,
          gap: 8,
          padding: '6px 20px',
          background: '#1a2232',
          borderBottom: '1px solid #28303f',
          fontFamily: 'monospace', fontSize: 9,
          textTransform: 'uppercase', letterSpacing: '0.08em',
          color: '#9aa4b8',
          flexShrink: 0,
        }}>
          <div style={{ textAlign: 'center' }}>
            <button
              onClick={toggleSelectAll}
              style={{
                background: 'none',
                border: 'none',
                padding: 4,
                color: selectedCount === wallets.length ? '#a855f7' : '#5d6a81',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              title={selectedCount === wallets.length ? 'Deselect all' : 'Select all'}
            >
              {selectedCount === wallets.length ? <CheckSquare size={12} /> : <Square size={12} />}
            </button>
          </div>
          <div style={{ textAlign: 'center' }}>#</div>
          <div>Address</div>
          <div style={{ textAlign: 'center' }}>Tier</div>
          <div style={{ textAlign: 'right' }}>Score</div>
          <div style={{ textAlign: 'right' }}>{isBatch ? 'Avg Entry→ATH' : 'Entry→ATH'}</div>
          <div style={{ textAlign: 'right' }}>{isBatch ? 'Avg ROI' : 'Total ROI'}</div>
          <div style={{ textAlign: 'right' }}>{isBatch ? 'Total Invested' : 'Invested'}</div>
          {isBatch && <div style={{ textAlign: 'right' }}>Tokens</div>}
          {isBatch && <div style={{ textAlign: 'right' }}>Consist.</div>}
          <div style={{ textAlign: 'right' }}>Actions</div>
        </div>

        {/* Wallet rows */}
        <div style={{ 
          flex: 1, 
          overflowY: 'auto', 
          background: '#0b0f17',
          scrollbarWidth: 'thin',
          scrollbarColor: '#3f4a5c #1a2232',
        }}>
          {wallets.length === 0 ? (
            <div style={{ padding: '40px 24px', textAlign: 'center' }}>
              <BarChart3 size={40} style={{ color: '#3f4a5c', margin: '0 auto 16px', display: 'block' }} />
              <div style={{ fontFamily: 'monospace', fontSize: 13, color: '#7c879c' }}>
                No qualifying wallets found
              </div>
              <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#5d6a81', marginTop: 6 }}>
                Try lowering your ROI threshold
              </div>
            </div>
          ) : (
            wallets.map((wallet, idx) => renderWalletCard(wallet, idx))
          )}
        </div>

        {/* COMPACT FOOTER - changes based on expanded state */}
        {wallets.length > 0 && (
          <div style={{
            padding: hasExpanded ? '4px 20px' : '8px 20px',
            background: '#1a2232',
            borderTop: '1px solid #28303f',
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            transition: 'padding 0.2s ease',
          }}>
            
            {/* Left side - selection controls */}
            <div style={{ display: 'flex', alignItems: 'center', gap: hasExpanded ? 6 : 12 }}>
              <button
                onClick={toggleSelectAll}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: hasExpanded ? '3px 5px' : '4px 8px',
                  borderRadius: 4,
                  color: '#9aa4b8',
                  fontSize: hasExpanded ? 9 : 10,
                  fontFamily: 'monospace',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  backgroundColor: '#1f2937',
                }}
                onMouseEnter={e => e.currentTarget.style.backgroundColor = '#2d3748'}
                onMouseLeave={e => e.currentTarget.style.backgroundColor = '#1f2937'}
              >
                {selectedCount === wallets.length ? (
                  <>
                    <CheckSquare size={hasExpanded ? 11 : 13} />
                    {hasExpanded ? 'All' : 'Deselect All'}
                  </>
                ) : (
                  <>
                    <Square size={hasExpanded ? 11 : 13} />
                    {hasExpanded ? 'All' : 'Select All'}
                  </>
                )}
              </button>

              {selectedCount > 0 && (
                <span style={{ 
                  fontFamily: 'monospace', 
                  fontSize: hasExpanded ? 9 : 10, 
                  color: '#9aa4b8' 
                }}>
                  {selectedCount} {hasExpanded ? 'sel' : 'selected'}
                </span>
              )}
            </div>

            {/* Right side - add button */}
            <button
              onClick={addSelectedToWatchlist}
              disabled={selectedCount === 0}
              style={{
                padding: hasExpanded ? '3px 10px' : '6px 14px',
                borderRadius: 4,
                border: 'none',
                background: selectedCount > 0
                  ? 'linear-gradient(90deg, #7c3aed, #9333ea)'
                  : '#374151',
                color: selectedCount > 0 ? '#ffffff' : '#6b7280',
                fontSize: hasExpanded ? 10 : 12,
                fontFamily: 'monospace', fontWeight: 600,
                cursor: selectedCount > 0 ? 'pointer' : 'default',
                display: 'flex',
                alignItems: 'center',
                gap: hasExpanded ? 4 : 6,
                transition: 'all 0.15s',
                opacity: selectedCount > 0 ? 1 : 0.5,
              }}
              onMouseEnter={e => { if (selectedCount > 0) e.currentTarget.style.opacity = '0.9'; }}
              onMouseLeave={e => { if (selectedCount > 0) e.currentTarget.style.opacity = '1'; }}
            >
              <BookmarkPlus size={hasExpanded ? 13 : 15} />
              {hasExpanded 
                ? `Add ${selectedCount}` 
                : `Add Selected (${selectedCount})`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}