// ResultsPanel.jsx — REBUILT with all fixes applied:
// 1. Per-token breakdown table in expanded panel (replaces single MCap boxes)
// 2. Section divider between cross-token and single-token wallets
// 3. Consistency score displayed as LOW/MED/HIGH with color — no raw number shown
// 4. "total" label under Invested column replaced with actual sum display
// 5. Tokens column added to batch results (tokens participated count)
// 6. Single-token wallets in batch results tagged "UNCONFIRMED" badge
// 7. Entry consistency in score breakdown now reflects distance from launch price

import React, { useState, useEffect } from 'react';
import {
  BookmarkPlus, BarChart3, ChevronDown, ChevronUp,
  Copy, CheckSquare, Square, TrendingUp, AlertTriangle,
} from 'lucide-react';
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
  if (v == null || v === 0) return '$0';
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${Number(v).toFixed(2)}`;
};

const fmtX   = (v) => (v != null && !isNaN(v) ? `${Number(v).toFixed(2)}x` : '—');
const fmtPct = (v) => (v != null && !isNaN(v) ? `${v > 0 ? '+' : ''}${Number(v).toFixed(1)}%` : '—');

// ── Consistency label — NO raw number shown ───────────────────────────────────
const consistencyLabel = (score) => {
  if (score == null) return { label: '—', color: '#7c879c' };
  if (score >= 70) return { label: 'HIGH',  color: '#22c55e' };
  if (score >= 40) return { label: 'MED',   color: '#eab308' };
  return             { label: 'LOW',   color: '#ef4444' };
};

// ── StatBar ───────────────────────────────────────────────────────────────────
const StatBar = ({ label, val, pct, color = '#3b82f6', sublabel }) => (
  <div style={{ marginBottom: 8 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
      <div>
        <span style={{ fontSize: 9, color: '#9aa4b8', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          {label}
        </span>
        {sublabel && (
          <span style={{ fontSize: 8, color: '#5d6a81', fontFamily: 'monospace', marginLeft: 6 }}>
            {sublabel}
          </span>
        )}
      </div>
      <span style={{ fontSize: 10, color, fontFamily: 'monospace', fontWeight: 700 }}>{val}</span>
    </div>
    <div style={{ height: 2, background: '#28303f', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{
        height: '100%',
        width: `${Math.max(0, Math.min(100, pct || 0))}%`,
        background: `linear-gradient(90deg, ${color}88, ${color})`,
        borderRadius: 2, transition: 'width 0.5s ease',
      }} />
    </div>
  </div>
);

// ── Helpers ───────────────────────────────────────────────────────────────────
const gradeColor = (g) => {
  if (!g) return '#7c879c';
  if (g.startsWith('A')) return '#22c55e';
  if (g.startsWith('B')) return '#3b82f6';
  if (g.startsWith('C')) return '#eab308';
  return '#ef4444';
};

const TIER_COLORS = {
  S: { text: '#eab308', bg: 'rgba(234,179,8,0.15)',   border: 'rgba(234,179,8,0.3)'   },
  A: { text: '#22c55e', bg: 'rgba(34,197,94,0.15)',   border: 'rgba(34,197,94,0.3)'   },
  B: { text: '#3b82f6', bg: 'rgba(59,130,246,0.15)',  border: 'rgba(59,130,246,0.3)'  },
  C: { text: '#7c879c', bg: 'rgba(124,135,156,0.12)', border: 'rgba(124,135,156,0.2)' },
};

// Column template — includes Tokens column for batch mode
const COL_TEMPLATE_BATCH  = '30px 40px minmax(220px, 3fr) 50px 55px 60px 100px 100px 90px 90px';
const COL_TEMPLATE_SINGLE = '30px 40px minmax(260px, 3fr) 50px 60px 110px 110px 100px 90px';

// ── Per-token breakdown table ─────────────────────────────────────────────────
const PerTokenTable = ({ roiDetails, copyToClipboard, copiedRunnerAddress }) => {
  if (!roiDetails || roiDetails.length === 0) return (
    <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#5d6a81' }}>No token detail available</div>
  );
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {roiDetails.map((row, i) => {
        const entryMcap = row.entry_market_cap;
        const athMcap   = row.ath_market_cap;
        const entryATH  = row.entry_to_ath_multiplier;
        const roi       = row.roi_multiplier || row.total_multiplier;
        const isWin     = (entryATH || 0) >= 10;
        return (
          <div key={i} style={{
            padding: '8px 10px', borderRadius: 4,
            background: isWin ? 'rgba(34,197,94,0.05)' : '#1a2232',
            border: `1px solid ${isWin ? 'rgba(34,197,94,0.2)' : '#28303f'}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: '#eab308' }}>
                ${row.runner || '???'}
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                {row.runner_address && (
                  <>
                    <span style={{ fontFamily: 'monospace', fontSize: 8, color: '#5d6a81' }}>
                      {row.runner_address.slice(0, 4)}…{row.runner_address.slice(-4)}
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); copyToClipboard(row.runner_address, 'runner'); }}
                      style={{ background: 'none', border: 'none', padding: 2, color: copiedRunnerAddress === row.runner_address ? '#22c55e' : '#7c879c', cursor: 'pointer' }}
                    >
                      <Copy size={9} />
                    </button>
                  </>
                )}
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
              <div>
                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase', marginBottom: 2 }}>Entry MCap</div>
                <div style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 700, color: '#f1f5f9' }}>{fmtMcap(entryMcap)}</div>
              </div>
              <div>
                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase', marginBottom: 2 }}>ATH MCap</div>
                <div style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 700, color: '#eab308' }}>{fmtMcap(athMcap)}</div>
              </div>
              <div>
                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase', marginBottom: 2 }}>Entry → ATH</div>
                <div style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 700, color: '#a855f7' }}>{fmtX(entryATH)}</div>
              </div>
              <div>
                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase', marginBottom: 2 }}>Entry Price</div>
                <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#f1f5f9' }}>{row.entry_price ? `$${Number(row.entry_price).toPrecision(4)}` : '—'}</div>
              </div>
              <div>
                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase', marginBottom: 2 }}>Realized</div>
                <div style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 700, color: (roi || 0) >= 1 ? '#22c55e' : '#ef4444' }}>{fmtX(roi)}</div>
              </div>
              <div>
                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase', marginBottom: 2 }}>From ATH</div>
                <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#7c879c' }}>{fmtPct(row.distance_to_ath_pct)}</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ── Section divider ───────────────────────────────────────────────────────────
const SectionDivider = ({ label, count, sublabel }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '6px 20px', background: '#111827',
    borderTop: '1px solid #1e2a3a', borderBottom: '1px solid #1e2a3a',
  }}>
    <div style={{ fontFamily: 'monospace', fontSize: 9, fontWeight: 700, color: '#7c879c', textTransform: 'uppercase', letterSpacing: '0.12em' }}>
      {label}
    </div>
    <span style={{
      fontFamily: 'monospace', fontSize: 9, padding: '1px 6px', borderRadius: 3,
      background: 'rgba(124,135,156,0.15)', color: '#9aa4b8',
    }}>
      {count}
    </span>
    {sublabel && (
      <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#5d6a81', marginLeft: 4 }}>
        {sublabel}
      </span>
    )}
  </div>
);

// =============================================================================
// MAIN COMPONENT
// =============================================================================
export default function ResultsPanel({ data, onClose, onAddToWatchlist, resultType, formatNumber, formatPrice }) {
  const [expandedWallets,     setExpandedWallets]     = useState({});
  const [selectedWallets,     setSelectedWallets]     = useState(new Set());
  const [copiedAddress,       setCopiedAddress]       = useState(null);
  const [copiedTokenAddress,  setCopiedTokenAddress]  = useState(null);
  const [copiedRunnerAddress, setCopiedRunnerAddress] = useState(null);

  const isBatch     = resultType?.includes('batch') || resultType === 'discovery';
  const hasExpanded = Object.values(expandedWallets).some(Boolean);

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') { setSelectedWallets(new Set()); onClose(); } };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const copyToClipboard = (addr, type = 'wallet') => {
    navigator.clipboard?.writeText(addr);
    if (type === 'wallet') { setCopiedAddress(addr); setTimeout(() => setCopiedAddress(null), 2000); }
    else if (type === 'token') { setCopiedTokenAddress(addr); setTimeout(() => setCopiedTokenAddress(null), 2000); }
    else { setCopiedRunnerAddress(addr); setTimeout(() => setCopiedRunnerAddress(null), 2000); }
  };

  const getWallets = () => {
    if (!data) return [];
    const found = data.wallets ?? data.smart_money_wallets ?? data.top_wallets;
    if (Array.isArray(found)) return found;
    if (Array.isArray(data)) return data;
    return [];
  };

  const allWallets = getWallets();

  // Split into cross-token and single-token groups (only relevant in batch mode)
  const crossTokenWallets  = isBatch ? allWallets.filter(w => w.is_cross_token) : [];
  const singleTokenWallets = isBatch ? allWallets.filter(w => !w.is_cross_token) : allWallets;
  const hasMixed = isBatch && crossTokenWallets.length > 0 && singleTokenWallets.length > 0;

  const COL_TEMPLATE = isBatch ? COL_TEMPLATE_BATCH : COL_TEMPLATE_SINGLE;

  const toggleSelectWallet = (addr, e) => {
    e.stopPropagation();
    setSelectedWallets(prev => {
      const s = new Set(prev);
      s.has(addr) ? s.delete(addr) : s.add(addr);
      return s;
    });
  };

  const toggleSelectAll = () => {
    if (selectedWallets.size === allWallets.length) setSelectedWallets(new Set());
    else setSelectedWallets(new Set(allWallets.map(w => w.wallet || w.wallet_address)));
  };

  const addSelectedToWatchlist = () => {
    const selected = allWallets.filter(w => selectedWallets.has(w.wallet || w.wallet_address));
    if (!selected.length) return;
    if (selected.length === 1 || window.confirm(`Add ${selected.length} wallets to watchlist?`)) {
      selected.forEach(w => onAddToWatchlist({
        wallet_address:      w.wallet || w.wallet_address,
        professional_score:  w.professional_score ?? w.aggregate_score,
        tier:                w.tier,
        roi_percent:         w.roi_percent,
        runner_hits_30d:     w.runner_hits_30d ?? w.runner_count,
        runner_success_rate: w.runner_success_rate,
        total_invested:      w.total_invested_sum ?? w.total_invested,
        runners_hit:         w.runners_hit ?? w.analyzed_tokens ?? [],
        other_runners:       w.other_runners || [],
      }));
    }
  };

  const summary = {
    total:          allWallets.length,
    sTier:          allWallets.filter(w => w.tier === 'S').length,
    aTier:          allWallets.filter(w => w.tier === 'A').length,
    token:          data?.token,
    tokensAnalyzed: data?.tokens_analyzed || data?.tokens_analyzed_list?.length || null,
  };

  const toggleExpand = (idx) => setExpandedWallets(prev => ({ ...prev, [idx]: !prev[idx] }));

  // ── Per-wallet card ─────────────────────────────────────────────────────────
  const renderWalletCard = (wallet, globalIdx, isUnconfirmed = false) => {
    const addr  = wallet.wallet || wallet.wallet_address || '';
    const grade = wallet.professional_grade;
    const tier  = wallet.tier;
    const tc    = TIER_COLORS[tier] || TIER_COLORS.C;

    const isWalletCrossToken = isBatch && wallet.is_cross_token;

    const score = isWalletCrossToken
      ? (wallet.aggregate_score ?? wallet.professional_score ?? 0)
      : (wallet.professional_score ?? 0);

    const entryATHMult = isWalletCrossToken
      ? (wallet.avg_entry_to_ath_multiplier ?? wallet.entry_to_ath_multiplier)
      : wallet.entry_to_ath_multiplier;

    const distATH = isWalletCrossToken
      ? (wallet.avg_distance_to_ath_pct ?? wallet.distance_to_ath_pct)
      : wallet.distance_to_ath_pct;

    const totalMult = isWalletCrossToken ? wallet.avg_total_roi : wallet.total_multiplier;
    const roiPct    = totalMult != null ? (totalMult - 1) * 100 : wallet.roi_percent;

    const totalInvested  = isWalletCrossToken
      ? (wallet.total_invested_sum ?? wallet.total_invested)
      : wallet.total_invested;

    const totalRealized  = isWalletCrossToken
      ? (wallet.total_realized_sum ?? wallet.realized_profit)
      : wallet.realized_profit;

    const unrealized     = wallet.unrealized_profit;
    const consistency    = wallet.consistency_score;
    const consist        = consistencyLabel(consistency);
    const runnerCount    = wallet.runner_count || (wallet.runners_hit?.length) || 0;
    const runnersHit     = wallet.runners_hit || wallet.analyzed_tokens || [];
    const runners30d     = wallet.runner_hits_30d || 0;
    const winRate        = wallet.runner_success_rate;
    const runnerROI      = wallet.runner_avg_roi;
    const otherRunners   = wallet.other_runners || [];
    const roiDetails     = wallet.roi_details || [];
    const firstBuy       = wallet.first_buy_time;
    const breakdown      = wallet.score_breakdown || {};
    const isExpanded     = expandedWallets[globalIdx];
    const rankDisplay    = globalIdx < 3 ? ['🥇', '🥈', '🥉'][globalIdx] : `#${globalIdx + 1}`;
    const isSelected     = selectedWallets.has(addr);

    const avgInvested = wallet.avg_invested ?? null;
    const avgRealized = wallet.avg_realized ?? null;

    // Tokens participated (for batch mode)
    const tokensParticipated = runnersHit.length || runnerCount || 0;
    const totalTokensAnalyzed = data?.tokens_analyzed || data?.tokens_analyzed_list?.length || null;

    return (
      <div
        key={addr + globalIdx}
        style={{
          borderBottom: '1px solid #1e2a3a',
          borderLeft: tier === 'S'
            ? '2px solid rgba(234,179,8,0.5)'
            : tier === 'A'
              ? '2px solid rgba(34,197,94,0.4)'
              : '2px solid transparent',
          background: isSelected ? 'rgba(124,58,237,0.04)' : 'transparent',
        }}
      >
        {/* ── COLLAPSED ROW ── */}
        <div
          onClick={() => toggleExpand(globalIdx)}
          style={{
            display: 'grid',
            gridTemplateColumns: COL_TEMPLATE,
            gap: 8, alignItems: 'center',
            padding: '10px 20px', cursor: 'pointer',
            background: isExpanded ? 'rgba(124,58,237,0.07)' : 'transparent',
            transition: 'background 0.15s',
          }}
          onMouseEnter={e => { if (!isExpanded) e.currentTarget.style.background = 'rgba(124,58,237,0.03)'; }}
          onMouseLeave={e => { if (!isExpanded) e.currentTarget.style.background = 'transparent'; }}
        >
          {/* Checkbox */}
          <div style={{ textAlign: 'center' }} onClick={e => e.stopPropagation()}>
            <button onClick={(e) => toggleSelectWallet(addr, e)} style={{
              background: 'none', border: 'none', padding: 4,
              color: isSelected ? '#a855f7' : '#5d6a81', cursor: 'pointer',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {isSelected ? <CheckSquare size={15} /> : <Square size={15} />}
            </button>
          </div>

          {/* Rank */}
          <div style={{ fontFamily: 'monospace', fontSize: globalIdx < 3 ? 15 : 12, color: '#7c879c', textAlign: 'center' }}>
            {rankDisplay}
          </div>

          {/* Address + unconfirmed badge */}
          <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#e2e8f0', display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden' }}>
            {isUnconfirmed && (
              <span style={{
                fontSize: 7, padding: '1px 4px', borderRadius: 2, flexShrink: 0,
                background: 'rgba(234,179,8,0.1)', border: '1px solid rgba(234,179,8,0.3)',
                color: '#eab308', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em',
              }}>
                Unconfirmed
              </span>
            )}
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{addr}</span>
            <button
              onClick={(e) => { e.stopPropagation(); copyToClipboard(addr, 'wallet'); }}
              style={{ background: 'none', border: 'none', padding: 2, color: copiedAddress === addr ? '#22c55e' : '#7c879c', cursor: 'pointer', flexShrink: 0 }}
            >
              <Copy size={12} />
            </button>
          </div>

          {/* Tier */}
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
          <div style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: gradeColor(grade), textAlign: 'right' }}>
            {Math.round(score)}
          </div>

          {/* Tokens column — batch only */}
          {isBatch && (
            <div style={{ textAlign: 'center' }}>
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: 3,
                padding: '2px 6px', borderRadius: 3,
                background: tokensParticipated >= 3
                  ? 'rgba(234,179,8,0.12)' : 'rgba(124,135,156,0.1)',
                border: `1px solid ${tokensParticipated >= 3 ? 'rgba(234,179,8,0.25)' : 'rgba(124,135,156,0.15)'}`,
              }}>
                <span style={{
                  fontFamily: 'monospace', fontSize: 11, fontWeight: 700,
                  color: tokensParticipated >= 3 ? '#eab308' : '#7c879c',
                }}>
                  {tokensParticipated}
                </span>
                {totalTokensAnalyzed && (
                  <span style={{ fontFamily: 'monospace', fontSize: 8, color: '#5d6a81' }}>
                    /{totalTokensAnalyzed}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Entry → ATH */}
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: '#a855f7' }}>
              {fmtX(entryATHMult)}
            </div>
            <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#7c879c' }}>
              {isWalletCrossToken ? 'avg ' : ''}{fmtPct(distATH)} from ATH
            </div>
          </div>

          {/* Total ROI */}
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: (totalMult || 0) >= 1 ? '#22c55e' : '#ef4444' }}>
              {fmtX(totalMult)}
            </div>
            <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#7c879c' }}>
              {roiPct != null ? `${roiPct > 0 ? '+' : ''}${Number(roiPct).toFixed(1)}%` : '—'}
            </div>
          </div>

          {/* Invested */}
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: '#f1f5f9' }}>
              {fmtUsd(totalInvested)}
            </div>
            <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#7c879c' }}>
              {isWalletCrossToken
                ? `${fmtUsd(totalRealized)} realized`
                : 'invested'}
            </div>
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onAddToWatchlist({
                  wallet_address: addr, professional_score: score, tier,
                  roi_percent: roiPct, runner_hits_30d: runners30d,
                  runner_success_rate: winRate, total_invested: totalInvested,
                  runners_hit: runnersHit, other_runners: otherRunners,
                });
              }}
              style={{
                padding: '4px 8px', borderRadius: 4, border: 'none',
                background: 'rgba(168,85,247,0.15)', color: '#a855f7',
                fontSize: 10, fontFamily: 'monospace', fontWeight: 700,
                cursor: 'pointer',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(168,85,247,0.25)'}
              onMouseLeave={e => e.currentTarget.style.background = 'rgba(168,85,247,0.15)'}
              title="Add to watchlist"
            >
              +WL
            </button>
            <div style={{ color: '#7c879c', lineHeight: 1 }}>
              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </div>
          </div>
        </div>

        {/* ── EXPANDED PANEL ── */}
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
                background: '#0e1520',
                borderTop: '1px solid #1e2a3a',
                padding: '16px 20px',
                display: 'grid',
                gridTemplateColumns: isWalletCrossToken ? '1fr 1.1fr 1.1fr' : '1.1fr 1.2fr 0.9fr',
                gap: 20,
              }}>

                {/* ── Col 1 ── */}
                {isWalletCrossToken ? (
                  <div>
                    <div style={{
                      fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase',
                      letterSpacing: '0.1em', color: '#9aa4b8', marginBottom: 10, fontWeight: 500,
                      display: 'flex', alignItems: 'center', gap: 6,
                    }}>
                      ● Per-Token Breakdown
                      <span style={{ color: '#eab308', fontSize: 10, marginLeft: 'auto' }}>
                        {runnerCount} tokens
                      </span>
                    </div>
                    <div style={{ maxHeight: 300, overflowY: 'auto', paddingRight: 2 }}>
                      <PerTokenTable
                        roiDetails={roiDetails}
                        copyToClipboard={copyToClipboard}
                        copiedRunnerAddress={copiedRunnerAddress}
                      />
                    </div>
                    {/* Consistency info below table — label only, no raw number */}
                    <div style={{
                      marginTop: 10, padding: '6px 10px', borderRadius: 4,
                      background: '#1a2232', border: '1px solid #28303f',
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    }}>
                      <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#9aa4b8', textTransform: 'uppercase' }}>
                        Entry Consistency
                      </span>
                      <span style={{
                        fontFamily: 'monospace', fontSize: 11, fontWeight: 700,
                        color: consist.color,
                      }}>
                        {consist.label}
                      </span>
                    </div>
                  </div>
                ) : (
                  // Single-token: score breakdown + mcap
                  <div>
                    <div style={{
                      fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase',
                      letterSpacing: '0.1em', color: '#9aa4b8', marginBottom: 12, fontWeight: 500,
                    }}>
                      ● Score Breakdown
                    </div>
                    <StatBar
                      label="Entry Timing (60%)"
                      val={breakdown.entry_score != null ? Number(breakdown.entry_score).toFixed(0) : '—'}
                      pct={breakdown.entry_score} color="#a855f7"
                    />
                    <StatBar
                      label="Total ROI (30%)"
                      val={breakdown.total_roi_score != null ? Number(breakdown.total_roi_score).toFixed(0) : '—'}
                      pct={breakdown.total_roi_score} color="#22c55e"
                    />
                    <StatBar
                      label="Realized ROI (10%)"
                      val={breakdown.realized_score != null ? Number(breakdown.realized_score).toFixed(0) : '—'}
                      pct={breakdown.realized_score} color="#3b82f6"
                    />
                    <div style={{
                      fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase',
                      letterSpacing: '0.1em', color: '#9aa4b8', marginTop: 14, marginBottom: 10, fontWeight: 500,
                    }}>
                      ● Market Cap
                    </div>
                    <div style={{
                      display: 'flex', justifyContent: 'space-between',
                      padding: '6px 10px', marginBottom: 6, borderRadius: 4,
                      background: 'rgba(168,85,247,0.08)', border: '1px solid rgba(168,85,247,0.2)',
                    }}>
                      <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#9aa4b8', textTransform: 'uppercase', alignSelf: 'center' }}>Entry MCap</span>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: '#f1f5f9' }}>{fmtMcap(wallet.entry_market_cap)}</div>
                        <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#9aa4b8' }}>{wallet.entry_price ? formatPrice(wallet.entry_price) : '—'}</div>
                      </div>
                    </div>
                    <div style={{
                      display: 'flex', justifyContent: 'space-between',
                      padding: '6px 10px', borderRadius: 4,
                      background: 'rgba(234,179,8,0.08)', border: '1px solid rgba(234,179,8,0.2)',
                    }}>
                      <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#9aa4b8', textTransform: 'uppercase', alignSelf: 'center' }}>ATH MCap</span>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: '#eab308' }}>{fmtMcap(wallet.ath_market_cap)}</div>
                        <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#9aa4b8' }}>{wallet.ath_price ? formatPrice(wallet.ath_price) : '—'}</div>
                      </div>
                    </div>
                    {firstBuy && (
                      <div style={{ marginTop: 8, fontFamily: 'monospace', fontSize: 9, color: '#5d6a81' }}>
                        First buy: {new Date(firstBuy * 1000).toLocaleDateString()}
                      </div>
                    )}
                  </div>
                )}

                {/* ── Col 2: PnL + score breakdown (cross) + 30d runner summary ── */}
                <div>
                  {isWalletCrossToken && (
                    <>
                      <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.1em', color: '#9aa4b8', marginBottom: 10, fontWeight: 500 }}>
                        ● Score Breakdown
                      </div>
                      <StatBar
                        label="Entry Timing (60%)"
                        sublabel="vs ATH"
                        val={breakdown.entry_score != null ? Number(breakdown.entry_score).toFixed(0) : '—'}
                        pct={breakdown.entry_score} color="#a855f7"
                      />
                      <StatBar
                        label="Total ROI (30%)"
                        val={breakdown.total_roi_score != null ? Number(breakdown.total_roi_score).toFixed(0) : '—'}
                        pct={breakdown.total_roi_score} color="#22c55e"
                      />
                      {/* Consistency bar — shows label, not raw score */}
                      <div style={{ marginBottom: 8 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                          <div>
                            <span style={{ fontSize: 9, color: '#9aa4b8', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                              Entry Consistency (10%)
                            </span>
                            <span style={{ fontSize: 8, color: '#5d6a81', fontFamily: 'monospace', marginLeft: 6 }}>
                              vs launch price
                            </span>
                          </div>
                          <span style={{ fontSize: 11, color: consist.color, fontFamily: 'monospace', fontWeight: 700 }}>
                            {consist.label}
                          </span>
                        </div>
                        <div style={{ height: 2, background: '#28303f', borderRadius: 2, overflow: 'hidden' }}>
                          <div style={{
                            height: '100%',
                            width: `${Math.max(0, Math.min(100, breakdown.consistency_score || 0))}%`,
                            background: `linear-gradient(90deg, ${consist.color}88, ${consist.color})`,
                            borderRadius: 2, transition: 'width 0.5s ease',
                          }} />
                        </div>
                      </div>
                      <div style={{ height: 12 }} />
                    </>
                  )}

                  <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.1em', color: '#9aa4b8', marginBottom: 10, fontWeight: 500 }}>
                    ● PnL Summary
                  </div>

                  {isWalletCrossToken ? (
                    <>
                      <StatBar label={`Total Realized (${runnerCount} tokens)`} val={fmtUsd(totalRealized)} pct={totalRealized && totalInvested ? Math.min((totalRealized / totalInvested) * 20, 100) : 0} color="#22c55e" />
                      <StatBar label="Total Invested" val={fmtUsd(totalInvested)} pct={50} color="#7c879c" />
                      {avgInvested != null && <StatBar label="Avg Invested / Token" val={fmtUsd(avgInvested)} pct={35} color="#5d6a81" />}
                      {avgRealized != null && <StatBar label="Avg Realized / Token" val={fmtUsd(avgRealized)} pct={avgRealized && avgInvested ? Math.min((avgRealized / avgInvested) * 20, 100) : 0} color="#16a34a" />}
                    </>
                  ) : (
                    <>
                      <StatBar label="Realized" val={fmtUsd(totalRealized)} pct={totalRealized && totalInvested ? Math.min((totalRealized / totalInvested) * 20, 100) : 0} color="#22c55e" />
                      <StatBar label="Unrealized" val={fmtUsd(unrealized)} pct={unrealized && totalInvested ? Math.min(Math.abs(unrealized / totalInvested) * 20, 100) : 0} color={(unrealized || 0) >= 0 ? '#3b82f6' : '#ef4444'} />
                      <StatBar label="Invested" val={fmtUsd(totalInvested)} pct={50} color="#7c879c" />
                    </>
                  )}

                  <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.1em', color: '#9aa4b8', marginTop: 14, marginBottom: 10, fontWeight: 500 }}>
                    ● 30-Day Runner Summary
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                    {[
                      { label: 'Runners Hit', val: runners30d, color: '#eab308' },
                      { label: 'Win Rate (5x+)', val: winRate != null ? `${winRate}%` : '—', color: (winRate || 0) >= 50 ? '#22c55e' : '#ef4444' },
                      { label: 'Avg ROI', val: runnerROI != null ? `${runnerROI}x` : '—', color: '#3b82f6' },
                      { label: 'Grade', val: grade || '—', color: gradeColor(grade) },
                    ].map(({ label, val, color }) => (
                      <div key={label} style={{ padding: '4px 8px', borderRadius: 4, background: '#1a2232', border: '1px solid #28303f' }}>
                        <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#9aa4b8', textTransform: 'uppercase', marginBottom: 2 }}>{label}</div>
                        <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color }}>{val}</div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* ── Col 3: Other Runners (30d history) ── */}
                <div>
                  <div style={{
                    fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase',
                    letterSpacing: '0.1em', color: '#9aa4b8', marginBottom: 10, fontWeight: 500,
                    display: 'flex', alignItems: 'center', gap: 6,
                  }}>
                    <TrendingUp size={12} color="#eab308" />
                    ● Other Runners (30d)
                    <span style={{ color: '#eab308', marginLeft: 'auto', fontSize: 10 }}>{otherRunners.length}</span>
                  </div>

                  {otherRunners.length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 280, overflowY: 'auto', paddingRight: 4 }}>
                      {otherRunners.map((r, ridx) => {
                        const entryToAth = r.entry_to_ath_multiplier || r.multiplier || 0;
                        const isWin      = entryToAth >= 5;
                        return (
                          <div key={ridx} style={{
                            padding: '7px 9px', borderRadius: 4,
                            background: isWin ? 'rgba(34,197,94,0.05)' : '#1a2232',
                            border: `1px solid ${isWin ? 'rgba(34,197,94,0.18)' : '#28303f'}`,
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                              <span style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 700, color: '#eab308' }}>
                                ${r.symbol || r.ticker || '???'}
                              </span>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                                {r.address && (
                                  <>
                                    <span style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81' }}>
                                      {r.address.slice(0, 4)}…{r.address.slice(-4)}
                                    </span>
                                    <button onClick={(e) => { e.stopPropagation(); copyToClipboard(r.address, 'runner'); }} style={{ background: 'none', border: 'none', padding: 2, color: copiedRunnerAddress === r.address ? '#22c55e' : '#7c879c', cursor: 'pointer' }}>
                                      <Copy size={9} />
                                    </button>
                                  </>
                                )}
                              </div>
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                              <div>
                                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase' }}>Entry MCap</div>
                                <div style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 600, color: '#f1f5f9' }}>{fmtMcap(r.entry_market_cap)}</div>
                              </div>
                              <div>
                                <div style={{ fontFamily: 'monospace', fontSize: 7, color: '#5d6a81', textTransform: 'uppercase' }}>Entry→ATH</div>
                                <div style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 600, color: '#a855f7' }}>{fmtX(entryToAth)}</div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div style={{ padding: '20px 12px', background: '#1a2232', borderRadius: 4, border: '1px dashed #28303f', textAlign: 'center' }}>
                      <TrendingUp size={18} style={{ color: '#3f4a5c', marginBottom: 6 }} />
                      <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#7c879c' }}>No other runners in last 30 days</div>
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

  // ── Render wallet groups ───────────────────────────────────────────────────
  const renderWalletList = () => {
    if (!isBatch) {
      return allWallets.map((w, i) => renderWalletCard(w, i, false));
    }
    if (!hasMixed) {
      return allWallets.map((w, i) => renderWalletCard(w, i, !w.is_cross_token));
    }
    const crossElems  = crossTokenWallets.map((w, i) => renderWalletCard(w, i, false));
    const divider     = (
      <SectionDivider
        key="divider"
        label="Single Token Only"
        count={singleTokenWallets.length}
        sublabel="— unconfirmed, appeared in 1 token only"
      />
    );
    const singleElems = singleTokenWallets.map((w, i) =>
      renderWalletCard(w, crossTokenWallets.length + i, true)
    );
    return [...crossElems, divider, ...singleElems];
  };

  const selectedCount = selectedWallets.size;
  const titleText =
    resultType === 'discovery' ? '⚡ Auto Discovery' :
    isBatch                    ? '📊 Batch Analysis' :
                                 '📊 Token Analysis';

  // Column headers — dynamic for batch vs single
  const renderHeaders = () => {
    if (isBatch) {
      return (
        <div style={{
          display: 'grid', gridTemplateColumns: COL_TEMPLATE_BATCH,
          gap: 8, padding: '6px 20px',
          background: '#111827', borderBottom: '1px solid #1e2a3a',
          fontFamily: 'monospace', fontSize: 9,
          textTransform: 'uppercase', letterSpacing: '0.08em', color: '#9aa4b8',
          flexShrink: 0,
        }}>
          <div style={{ textAlign: 'center' }}>
            <button onClick={toggleSelectAll} style={{ background: 'none', border: 'none', padding: 4, color: selectedCount === allWallets.length ? '#a855f7' : '#5d6a81', cursor: 'pointer', display: 'inline-flex' }}>
              {selectedCount === allWallets.length ? <CheckSquare size={12} /> : <Square size={12} />}
            </button>
          </div>
          <div style={{ textAlign: 'center' }}>#</div>
          <div>Address</div>
          <div style={{ textAlign: 'center' }}>Tier</div>
          <div style={{ textAlign: 'right' }}>Score</div>
          <div style={{ textAlign: 'center' }}>Tokens</div>
          <div style={{ textAlign: 'right' }}>Entry→ATH</div>
          <div style={{ textAlign: 'right' }}>ROI</div>
          <div style={{ textAlign: 'right' }}>Invested</div>
          <div style={{ textAlign: 'right' }}>Actions</div>
        </div>
      );
    }
    return (
      <div style={{
        display: 'grid', gridTemplateColumns: COL_TEMPLATE_SINGLE,
        gap: 8, padding: '6px 20px',
        background: '#111827', borderBottom: '1px solid #1e2a3a',
        fontFamily: 'monospace', fontSize: 9,
        textTransform: 'uppercase', letterSpacing: '0.08em', color: '#9aa4b8',
        flexShrink: 0,
      }}>
        <div style={{ textAlign: 'center' }}>
          <button onClick={toggleSelectAll} style={{ background: 'none', border: 'none', padding: 4, color: selectedCount === allWallets.length ? '#a855f7' : '#5d6a81', cursor: 'pointer', display: 'inline-flex' }}>
            {selectedCount === allWallets.length ? <CheckSquare size={12} /> : <Square size={12} />}
          </button>
        </div>
        <div style={{ textAlign: 'center' }}>#</div>
        <div>Address</div>
        <div style={{ textAlign: 'center' }}>Tier</div>
        <div style={{ textAlign: 'right' }}>Score</div>
        <div style={{ textAlign: 'right' }}>Entry→ATH</div>
        <div style={{ textAlign: 'right' }}>ROI</div>
        <div style={{ textAlign: 'right' }}>Invested</div>
        <div style={{ textAlign: 'right' }}>Actions</div>
      </div>
    );
  };

  // ── MAIN RENDER ─────────────────────────────────────────────────────────────
  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 200,
        background: 'rgba(0,0,0,0.75)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '12px',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        width: '100%', maxWidth: isBatch ? 1260 : 1160, height: '98vh',
        background: '#0b0f17', borderRadius: 12,
        border: '1px solid #1e2a3a',
        boxShadow: '0 25px 50px -12px rgba(0,0,0,0.8), 0 0 0 1px rgba(124,58,237,0.12)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>

        {/* ── Header ── */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 20px', background: '#1e1b2e',
          borderBottom: '1px solid #2d2642', flexShrink: 0,
        }}>
          <div>
            <div style={{ fontFamily: 'monospace', fontSize: 16, fontWeight: 700, color: '#fff', letterSpacing: '0.02em' }}>
              {titleText} Results
            </div>
            {summary.token && (
              <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#9aa4b8', marginTop: 2, display: 'flex', alignItems: 'center', gap: 6 }}>
                {summary.token.ticker || summary.token.symbol}{' — '}
                <span style={{ color: '#a78bfa' }}>{summary.token.address}</span>
                <button onClick={() => { navigator.clipboard?.writeText(summary.token.address); setCopiedTokenAddress(summary.token.address); setTimeout(() => setCopiedTokenAddress(null), 2000); }} style={{ background: 'none', border: 'none', padding: 2, color: copiedTokenAddress === summary.token.address ? '#22c55e' : '#7c879c', cursor: 'pointer' }}>
                  <Copy size={11} />
                </button>
              </div>
            )}
            {isBatch && summary.tokensAnalyzed && (
              <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#9aa4b8', marginTop: 2 }}>
                {summary.tokensAnalyzed} tokens analyzed
                {hasMixed && ` · ${crossTokenWallets.length} confirmed · ${singleTokenWallets.length} unconfirmed`}
              </div>
            )}
          </div>
          <button
            onClick={() => { setSelectedWallets(new Set()); onClose(); }}
            style={{
              width: 32, height: 32, borderRadius: 6,
              border: '1px solid #3d2d3a', background: 'rgba(239,68,68,0.15)', color: '#f87171',
              fontSize: 16, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >✕</button>
        </div>

        {/* ── Summary stats ── */}
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 1, background: '#3a2d22', borderBottom: '1px solid #3a2d22', flexShrink: 0,
        }}>
          {[
            { label: 'Qualified', val: summary.total, color: '#f97316' },
            { label: 'S-Tier',    val: summary.sTier, color: '#eab308' },
            { label: 'A-Tier',    val: summary.aTier, color: '#22c55e' },
          ].map(({ label, val, color }, i) => (
            <div key={label} style={{
              padding: '8px 12px', background: '#281f16', textAlign: 'center',
              borderRight: i < 2 ? '1px solid #3a2d22' : 'none',
            }}>
              <div style={{ fontFamily: 'monospace', fontSize: 22, fontWeight: 900, color }}>{val}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 9, color: '#b3967a', textTransform: 'uppercase', letterSpacing: '0.1em', marginTop: 2 }}>
                {label}
              </div>
            </div>
          ))}
        </div>

        {/* ── Column headers ── */}
        {renderHeaders()}

        {/* ── Wallet rows ── */}
        <div style={{ flex: 1, overflowY: 'auto', background: '#0b0f17', scrollbarWidth: 'thin', scrollbarColor: '#3f4a5c #1a2232' }}>
          {allWallets.length === 0 ? (
            <div style={{ padding: '40px 24px', textAlign: 'center' }}>
              <BarChart3 size={40} style={{ color: '#3f4a5c', margin: '0 auto 16px', display: 'block' }} />
              <div style={{ fontFamily: 'monospace', fontSize: 13, color: '#7c879c' }}>No qualifying wallets found</div>
              <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#5d6a81', marginTop: 6 }}>Try lowering your ROI threshold</div>
            </div>
          ) : renderWalletList()}
        </div>

        {/* ── Footer ── */}
        {allWallets.length > 0 && (
          <div style={{
            padding: hasExpanded ? '4px 20px' : '8px 20px',
            background: '#111827', borderTop: '1px solid #1e2a3a', flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <button onClick={toggleSelectAll} style={{
                background: '#1f2937', border: 'none', padding: '4px 8px', borderRadius: 4,
                color: '#9aa4b8', fontSize: 10, fontFamily: 'monospace', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 4,
              }}>
                {selectedCount === allWallets.length
                  ? <><CheckSquare size={12} /> Deselect All</>
                  : <><Square size={12} /> Select All</>}
              </button>
              {selectedCount > 0 && (
                <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#9aa4b8' }}>
                  {selectedCount} selected
                </span>
              )}
            </div>
            <button
              onClick={addSelectedToWatchlist}
              disabled={selectedCount === 0}
              style={{
                padding: '6px 14px', borderRadius: 4, border: 'none',
                background: selectedCount > 0 ? 'linear-gradient(90deg, #7c3aed, #9333ea)' : '#374151',
                color: selectedCount > 0 ? '#fff' : '#6b7280',
                fontSize: 12, fontFamily: 'monospace', fontWeight: 600,
                cursor: selectedCount > 0 ? 'pointer' : 'default',
                display: 'flex', alignItems: 'center', gap: 6,
                opacity: selectedCount > 0 ? 1 : 0.5,
              }}
            >
              <BookmarkPlus size={14} />
              Add Selected ({selectedCount})
            </button>
          </div>
        )}
      </div>
    </div>
  );
}