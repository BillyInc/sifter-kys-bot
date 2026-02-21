import React, { useState } from 'react';
import { RefreshCw, Trash2, ChevronDown, ChevronUp } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export default function WatchlistExpandedCard({
  wallet,
  rank,
  onRefresh,
  onDelete,
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

  // ── Field mapping ──────────────────────────────────────────────────────────
  const distanceToATH  = wallet.avg_distance_to_ath_multiplier ?? wallet.distance_to_ath_pct ?? 0;
  const entryQuality   = wallet.avg_entry_quality_multiplier ?? wallet.entry_to_ath_multiplier ?? 0;
  const consistency    = wallet.consistency_score ?? 0;
  const winRate7d      = wallet.win_rate_7d ?? 0;
  const winRate30d     = wallet.win_rate_30d ?? 0;
  const roi30dMult     = wallet.roi_30d_multiplier ?? (wallet.roi_percent != null ? 1 + wallet.roi_percent / 100 : 1);
  const score          = wallet.professional_score ?? wallet.avg_professional_score ?? 0;
  const zone           = wallet.zone ?? 'monitoring';
  const runners30d     = wallet.runners_30d ?? wallet.runner_hits_30d ?? 0;
  const topRunners     = (wallet.tokens_hit || wallet.runners_hit || []).slice(0, 4);
  const form           = wallet.form || Array(5).fill({ result: 'neutral' });
  const alerts         = wallet.degradation_alerts || [];

  const roiDisplay = roi30dMult >= 1
    ? `+${((roi30dMult - 1) * 100).toFixed(0)}%`
    : `${((roi30dMult - 1) * 100).toFixed(0)}%`;

  const rankDisplay = rank <= 3
    ? ['🥇', '🥈', '🥉'][rank - 1]
    : `#${rank}`;

  // ── Tier colours ───────────────────────────────────────────────────────────
  const tierColors = {
    S: { text: '#f5c842', bg: 'rgba(245,200,66,0.12)', border: 'rgba(245,200,66,0.25)' },
    A: { text: '#22c55e', bg: 'rgba(34,197,94,0.12)',  border: 'rgba(34,197,94,0.25)'  },
    B: { text: '#60a5fa', bg: 'rgba(59,130,246,0.12)', border: 'rgba(59,130,246,0.25)' },
    C: { text: '#6b7280', bg: 'rgba(107,114,128,0.1)', border: 'rgba(107,114,128,0.2)' },
  };
  const tc = tierColors[wallet.tier] || tierColors.C;

  // ── Alert severity ─────────────────────────────────────────────────────────
  const topAlert = alerts[0]?.severity;
  const alertAccent = topAlert === 'red' ? '#ef4444' : topAlert === 'orange' ? '#f97316' : topAlert === 'yellow' ? '#eab308' : null;

  // ── Stat bar component (inline) ────────────────────────────────────────────
  const StatBar = ({ label, val, pct, color = '#3b82f6' }) => (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 10, color: '#3a5a8a', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</span>
        <span style={{ fontSize: 11, color, fontFamily: 'monospace', fontWeight: 700 }}>{val}</span>
      </div>
      <div style={{ height: 2, background: '#1a2640', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, pct))}%`, background: `linear-gradient(90deg, ${color}88, ${color})`, borderRadius: 2, transition: 'width 0.5s ease' }} />
      </div>
    </div>
  );

  return (
    <div style={{
      borderBottom: '1px solid rgba(26,38,64,0.6)',
      borderLeft: alertAccent ? `2px solid ${alertAccent}` : '2px solid transparent',
      transition: 'background 0.15s',
    }}>

      {/* ── COLLAPSED ROW ─────────────────────────────────────────────────── */}
      <div
        onClick={() => setIsExpanded(!isExpanded)}
        style={{
          display: 'grid',
          gridTemplateColumns: '36px 140px 44px 52px 76px 68px 60px 60px 1fr',
          gap: 8,
          alignItems: 'center',
          padding: '11px 16px',
          cursor: 'pointer',
          background: isExpanded ? 'rgba(59,130,246,0.04)' : 'transparent',
        }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(59,130,246,0.04)'}
        onMouseLeave={e => e.currentTarget.style.background = isExpanded ? 'rgba(59,130,246,0.04)' : 'transparent'}
      >
        {/* Rank */}
        <div style={{ fontFamily: 'monospace', fontSize: rank <= 3 ? 15 : 12, color: '#3a5a8a', textAlign: 'center' }}>
          {rankDisplay}
        </div>

        {/* Address */}
        <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {wallet.wallet_address?.slice(0, 8)}...{wallet.wallet_address?.slice(-4)}
        </div>

        {/* Tier */}
        <div style={{ textAlign: 'center' }}>
          <span style={{
            display: 'inline-block', padding: '1px 7px', borderRadius: 3,
            fontSize: 11, fontWeight: 700, fontFamily: 'monospace',
            color: tc.text, background: tc.bg, border: `1px solid ${tc.border}`,
          }}>
            {wallet.tier || 'C'}
          </span>
        </div>

        {/* Score */}
        <div style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: '#e2e8f0', textAlign: 'right' }}>
          {score}
        </div>

        {/* ATH dist */}
        <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#22c55e', textAlign: 'right', fontWeight: 600 }}>
          {Number(distanceToATH).toFixed(1)}x
        </div>

        {/* ROI */}
        <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, textAlign: 'right', color: roi30dMult >= 1 ? '#22c55e' : '#ef4444' }}>
          {roiDisplay}
        </div>

        {/* Runners */}
        <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#f5c842', textAlign: 'right', fontWeight: 600 }}>
          {runners30d}
        </div>

        {/* Form pips */}
        <div style={{ display: 'flex', gap: 3, justifyContent: 'center' }}>
          {form.slice(0, 5).map((f, i) => (
            <div key={i} style={{
              width: 6, height: 6, borderRadius: 1,
              background: f.result === 'win' ? '#22c55e' : f.result === 'loss' ? '#ef4444' : '#334155',
            }} />
          ))}
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: 5, justifyContent: 'flex-end', alignItems: 'center' }}>
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            style={{
              padding: '3px 8px', borderRadius: 4, border: 'none',
              background: 'rgba(59,130,246,0.15)', color: '#60a5fa',
              fontSize: 11, fontFamily: 'monospace', fontWeight: 700,
              cursor: 'pointer', opacity: isRefreshing ? 0.5 : 1,
            }}
          >
            <RefreshCw size={10} style={{ display: 'inline', animation: isRefreshing ? 'spin 1s linear infinite' : 'none' }} />
          </button>
          <button
            onClick={handleDelete}
            disabled={isDeleting}
            style={{
              padding: '3px 8px', borderRadius: 4, border: 'none',
              background: confirmDelete ? 'rgba(239,68,68,0.3)' : 'rgba(239,68,68,0.12)',
              color: confirmDelete ? '#fca5a5' : '#ef4444',
              fontSize: 11, fontFamily: 'monospace', fontWeight: 700,
              cursor: 'pointer', opacity: isDeleting ? 0.5 : 1,
              transition: 'all 0.15s',
            }}
          >
            {confirmDelete ? '?' : '✕'}
          </button>
          <div style={{ color: '#3a5a8a', lineHeight: 1 }}>
            {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </div>
        </div>
      </div>

      {/* ── EXPANDED PANEL ────────────────────────────────────────────────── */}
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
              background: '#060c14',
              borderTop: '1px solid #1a2640',
              padding: '16px 20px',
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 1fr',
              gap: 20,
            }}>

              {/* Col 1: Performance */}
              <div>
                <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', color: '#3a5a8a', marginBottom: 12 }}>
                  ● Performance Metrics
                </div>
                <StatBar label="ATH Distance" val={`${Number(distanceToATH).toFixed(1)}x`} pct={Math.min((distanceToATH / 100) * 100, 100)} color="#22c55e" />
                <StatBar label="Entry Quality" val={`${Number(entryQuality).toFixed(1)}x`}  pct={Math.max(100 - (entryQuality / 50) * 100, 0)} color="#f5c842" />
                <StatBar label="Consistency"   val={Number(consistency).toFixed(2)}          pct={(1 - Math.min(consistency, 1)) * 100} color="#a855f7" />
                <StatBar label="Win Rate 7d / 30d" val={`${Number(winRate7d).toFixed(0)}% / ${Number(winRate30d).toFixed(0)}%`} pct={Math.min(winRate7d, 100)} color="#3b82f6" />
                <StatBar
                  label="ROI 30d"
                  val={`${roi30dMult.toFixed(2)}x`}
                  pct={Math.min(roi30dMult * 50, 100)}
                  color={roi30dMult >= 1 ? '#22c55e' : '#ef4444'}
                />
              </div>

              {/* Col 2: Runners */}
              <div>
                <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', color: '#3a5a8a', marginBottom: 12 }}>
                  ● Recent Runners
                </div>
                {topRunners.length === 0 ? (
                  <div style={{ fontSize: 11, color: '#334155', fontFamily: 'monospace' }}>No runners in last 30 days</div>
                ) : topRunners.map((runner, i) => {
                  const sym  = runner.symbol || runner.token || runner;
                  const mult = runner.entry_to_ath_multiplier || 0;
                  return (
                    <div key={i} style={{
                      display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
                      padding: '4px 8px', borderRadius: 4,
                      background: 'rgba(245,200,66,0.06)', border: '1px solid rgba(245,200,66,0.15)',
                    }}>
                      <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#f5c842', fontWeight: 700 }}>${sym}</span>
                      <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#64748b', marginLeft: 'auto' }}>{mult.toFixed(1)}x</span>
                    </div>
                  );
                })}

                {/* Form row */}
                <div style={{ marginTop: 14 }}>
                  <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', color: '#3a5a8a', marginBottom: 8 }}>
                    ● Recent Form
                  </div>
                  <div style={{ display: 'flex', gap: 3 }}>
                    {form.slice(0, 10).map((f, i) => (
                      <span key={i} style={{
                        fontFamily: 'monospace', fontSize: 11, fontWeight: 700,
                        color: f.result === 'win' ? '#22c55e' : f.result === 'loss' ? '#ef4444' : '#475569',
                      }}>
                        {f.result === 'win' ? 'W' : f.result === 'loss' ? 'L' : 'D'}
                      </span>
                    ))}
                  </div>
                  <div style={{ fontSize: 10, color: '#334155', fontFamily: 'monospace', marginTop: 4 }}>
                    W = &gt;3x · D = 0–3x · L = negative
                  </div>
                </div>
              </div>

              {/* Col 3: Alerts + meta */}
              <div>
                <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', color: '#3a5a8a', marginBottom: 12 }}>
                  ● Alerts
                </div>
                {alerts.length === 0 ? (
                  <div style={{ fontSize: 11, color: '#22c55e', fontFamily: 'monospace' }}>✓ No active alerts</div>
                ) : alerts.map((alert, i) => {
                  const aColors = {
                    red:    { bg: 'rgba(239,68,68,0.1)',  border: 'rgba(239,68,68,0.25)',  text: '#f87171', icon: '🔴' },
                    orange: { bg: 'rgba(249,115,22,0.1)', border: 'rgba(249,115,22,0.25)', text: '#fb923c', icon: '🟠' },
                    yellow: { bg: 'rgba(234,179,8,0.1)',  border: 'rgba(234,179,8,0.25)',  text: '#fbbf24', icon: '🟡' },
                  };
                  const ac = aColors[alert.severity] || aColors.yellow;
                  return (
                    <div key={i} style={{
                      display: 'flex', alignItems: 'flex-start', gap: 6,
                      padding: '6px 8px', marginBottom: 6, borderRadius: 4,
                      background: ac.bg, border: `1px solid ${ac.border}`,
                      fontSize: 11, color: ac.text, fontFamily: 'monospace',
                    }}>
                      <span>{ac.icon}</span> {alert.message}
                    </div>
                  );
                })}

                <div style={{ marginTop: 12, fontSize: 11, color: '#334155', fontFamily: 'monospace', lineHeight: 1.8 }}>
                  <div>Last refresh: {wallet.last_updated ? new Date(wallet.last_updated).toLocaleString() : 'Never'}</div>
                </div>

                <button
                  onClick={handleRefresh}
                  disabled={isRefreshing}
                  style={{
                    marginTop: 12, display: 'flex', alignItems: 'center', gap: 6,
                    padding: '5px 12px', borderRadius: 4,
                    background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.3)',
                    color: '#a78bfa', fontSize: 11, fontFamily: 'monospace', fontWeight: 700,
                    cursor: 'pointer', opacity: isRefreshing ? 0.5 : 1, transition: 'all 0.15s',
                  }}
                >
                  <RefreshCw size={11} style={{ animation: isRefreshing ? 'spin 1s linear infinite' : 'none' }} />
                  {isRefreshing ? 'Refreshing...' : 'Refresh'}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}