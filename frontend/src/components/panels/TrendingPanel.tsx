import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useTrendingRunners } from '../../hooks/useApi';
import {
  TrendingUp, Filter, Sparkles, ChevronDown, CheckSquare, Square,
  BarChart3, Shield, RefreshCw, XCircle, ChevronUp, AlertTriangle,
  RotateCcw, Activity, Minimize2, Zap, Clock,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { toast } from 'sonner';

const LIVE_INTERVAL_MS  = 60_000;
const POLL_INTERVAL_MS  = 3_000;
const MAX_POLL_ATTEMPTS = 400;

// ─── Helpers ───────────────────────────────────────────────────────────────────
const fmtNum = (v: any) => {
  if (!v) return '$0';
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(2)}`;
};

const fmtPrice = (p: any) => {
  if (!p) return '$0';
  if (p < 0.000001) return `$${p.toExponential(2)}`;
  if (p < 0.01)     return `$${p.toFixed(6)}`;
  if (p < 1)        return `$${p.toFixed(4)}`;
  return `$${p.toFixed(2)}`;
};

const formatTs = (d: Date | null) =>
  d ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';

const RANK_BADGES = ['🥇', '🥈', '🥉'];

const MULT_COLORS = {
  5:  { text: '#fbbf24', bg: 'rgba(251,191,36,0.12)',  border: 'rgba(251,191,36,0.35)',  glow: 'rgba(251,191,36,0.25)'  },
  10: { text: '#34d399', bg: 'rgba(52,211,153,0.12)',  border: 'rgba(52,211,153,0.35)',  glow: 'rgba(52,211,153,0.25)'  },
  20: { text: '#38bdf8', bg: 'rgba(56,189,248,0.12)',  border: 'rgba(56,189,248,0.35)',  glow: 'rgba(56,189,248,0.25)'  },
  50: { text: '#a78bfa', bg: 'rgba(167,139,250,0.12)', border: 'rgba(167,139,250,0.35)', glow: 'rgba(167,139,250,0.25)' },
};

// ─── Stat pill ─────────────────────────────────────────────────────────────────
interface StatPillProps {
  label: string;
  value: string;
  color?: string;
  accent?: boolean;
}

const StatPill = ({ label, value, color = '#94a3b8', accent = false }: StatPillProps) => (
  <div style={{
    display: 'flex', flexDirection: 'column', gap: 2,
    padding: '5px 9px', borderRadius: 6,
    background: 'var(--bg-card)',
    border: '1px solid var(--border-color)',
    minWidth: 56,
  }}>
    <span style={{ fontFamily: 'monospace', fontSize: 8, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
      {label}
    </span>
    <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color }}>
      {value}
    </span>
  </div>
);

// ─── Runner card ───────────────────────────────────────────────────────────────
interface RunnerCardProps {
  token: any;
  rank: number;
  isSelected: boolean;
  isAnalyzingThis: boolean;
  isAnalysisRunning: boolean;
  showBatch: boolean;
  onToggle: (token: any) => void;
  onAnalyze: (token: any) => void;
  onCancel: (...args: any[]) => void;
}

const RunnerCard = ({ token, rank, isSelected, isAnalyzingThis, isAnalysisRunning, showBatch, onToggle, onAnalyze, onCancel }: RunnerCardProps) => {
  const multColor =
    token.multiplier >= 50 ? '#a78bfa' :
    token.multiplier >= 20 ? '#38bdf8' :
    token.multiplier >= 10 ? '#34d399' : '#fbbf24';

  const rankDisplay = rank <= 3 ? RANK_BADGES[rank - 1] : null;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      style={{
        borderBottom: '1px solid rgba(255,255,255,0.07)',
        borderLeft: isSelected ? '2px solid #fb923c' : '2px solid transparent',
        background: isSelected
          ? 'rgba(251,146,60,0.07)'
          : isAnalyzingThis
            ? 'rgba(139,92,246,0.07)'
            : 'rgba(255,255,255,0.02)',
        transition: 'background 0.15s, border-left 0.15s',
      }}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: showBatch
            ? '28px 22px 1fr auto'
            : '28px 1fr auto',
          gap: 10,
          alignItems: 'center',
          padding: '12px 16px',
        }}
      >
        {/* Rank */}
        <div style={{ textAlign: 'center' }}>
          {rankDisplay
            ? <span style={{ fontSize: 15 }}>{rankDisplay}</span>
            : <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#64748b', fontWeight: 700 }}>#{rank}</span>
          }
        </div>

        {/* Checkbox */}
        {showBatch && (
          <button
            onClick={() => onToggle(token)}
            disabled={isAnalysisRunning}
            style={{ background: 'none', border: 'none', padding: 2, cursor: 'pointer', display: 'flex', alignItems: 'center', color: isSelected ? '#fb923c' : '#64748b' }}
          >
            {isSelected ? <CheckSquare size={16} /> : <Square size={16} />}
          </button>
        )}

        {/* Token info */}
        <div style={{ minWidth: 0 }}>
          {/* Top row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
            <span style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>
              {token.ticker || token.symbol}
            </span>
            <span style={{
              fontFamily: 'monospace', fontSize: 9, padding: '2px 6px',
              borderRadius: 4, background: 'rgba(255,255,255,0.10)',
              color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em',
              border: '1px solid rgba(255,255,255,0.12)',
            }}>
              {token.chain?.toUpperCase()}
            </span>
            {/* Multiplier badge */}
            <span style={{
              fontFamily: 'monospace', fontSize: 11, fontWeight: 900,
              padding: '2px 7px', borderRadius: 4,
              background: `${multColor}18`,
              border: `1px solid ${multColor}50`,
              color: multColor,
            }}>
              {token.multiplier}x
            </span>
            {/* Verified */}
            <span style={{
              fontFamily: 'monospace', fontSize: 9, padding: '2px 6px',
              borderRadius: 4, background: 'rgba(34,197,94,0.12)',
              border: '1px solid rgba(34,197,94,0.30)', color: '#4ade80',
              display: 'flex', alignItems: 'center', gap: 3,
            }}>
              <Shield size={9} /> Verified
            </span>
          </div>

          {/* Token name */}
          <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#64748b', marginBottom: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {token.name}
          </div>

          {/* Stats row */}
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            <StatPill label="Price"    value={fmtPrice(token.current_price)} color="#f1f5f9" />
            <StatPill label="Vol 24h"  value={fmtNum(token.volume_24h)}      color="#38bdf8" accent />
            <StatPill label="Liq"      value={fmtNum(token.liquidity)}        color="#34d399" accent />
            {token.holders && (
              <StatPill label="Holders" value={token.holders.toLocaleString()} color="#a78bfa" />
            )}
            {token.momentum_score && (
              <StatPill label="Momentum" value={token.momentum_score} color="#fb923c" accent />
            )}
          </div>

          {/* Analyzing progress bar */}
          {isAnalyzingThis && (
            <div style={{ marginTop: 8, height: 2, background: 'rgba(139,92,246,0.20)', borderRadius: 2, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: '70%', background: 'linear-gradient(90deg, #7c3aed, #a855f7)', borderRadius: 2, animation: 'pulse 1.5s ease-in-out infinite' }} />
            </div>
          )}
        </div>

        {/* Action button */}
        <div>
          {isAnalyzingThis ? (
            <button
              onClick={onCancel}
              style={{
                padding: '6px 10px', borderRadius: 6, border: '1px solid rgba(239,68,68,0.35)',
                background: 'rgba(239,68,68,0.15)', color: '#f87171',
                fontFamily: 'monospace', fontSize: 10, fontWeight: 700,
                cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
              }}
            >
              <XCircle size={12} /> Cancel
            </button>
          ) : (
            <button
              onClick={() => onAnalyze(token)}
              disabled={isAnalysisRunning}
              style={{
                padding: '6px 10px', borderRadius: 6,
                border: isAnalysisRunning ? '1px solid rgba(139,92,246,0.15)' : '1px solid rgba(139,92,246,0.35)',
                background: isAnalysisRunning ? 'rgba(139,92,246,0.06)' : 'rgba(139,92,246,0.18)',
                color: isAnalysisRunning ? '#7c6a9a' : '#c084fc',
                fontFamily: 'monospace', fontSize: 10, fontWeight: 700,
                cursor: isAnalysisRunning ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', gap: 4,
                opacity: isAnalysisRunning && !isAnalyzingThis ? 0.5 : 1,
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => { if (!isAnalysisRunning) e.currentTarget.style.background = 'rgba(139,92,246,0.30)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = isAnalysisRunning ? 'rgba(139,92,246,0.06)' : 'rgba(139,92,246,0.18)'; }}
            >
              {isAnalysisRunning && !isAnalyzingThis
                ? <div style={{ width: 10, height: 10, border: '2px solid rgba(139,92,246,0.3)', borderTop: '2px solid #a855f7', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                : <BarChart3 size={12} />
              }
              Analyze
            </button>
          )}
        </div>
      </div>
    </motion.div>
  );
};

// ─── Progress bar ──────────────────────────────────────────────────────────────
const ProgressBar = ({ current, total, color = '#fb923c', phase = '' }) => {
  const pct = Math.round((current / Math.max(total, 1)) * 100);
  return (
    <div>
      <div style={{ height: 3, background: 'rgba(255,255,255,0.10)', borderRadius: 3, overflow: 'hidden', marginBottom: 6 }}>
        <div style={{
          height: '100%', width: `${pct}%`, borderRadius: 3,
          background: `linear-gradient(90deg, ${color}88, ${color})`,
          transition: 'width 0.4s ease',
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'monospace', fontSize: 9, color: '#64748b' }}>
        <span>{phase}</span>
        <span>{current}/{total} · {pct}%</span>
      </div>
    </div>
  );
};

// ─── Core panel ────────────────────────────────────────────────────────────────
interface TrendingPanelCoreProps {
  userId: string;
  apiUrl: string;
  onClose: () => void;
  formatNumber: (v: any) => string;
  formatPrice: (v: any) => string;
  onResultsReady: (...args: any[]) => any;
  onAnalysisStart: (info: any) => void;
  onAnalysisProgress: (progress: any) => void;
  onAnalysisComplete: (data: any) => void;
  activeAnalysis: any;
  preloadedRunners?: any[];
  isRefreshingRunners?: boolean;
  lastRefreshed?: number | null;
  onRefreshRunners?: (runners?: any[]) => void;
  onMinimize?: () => void;
}

function TrendingPanelCore({
  userId, apiUrl, onClose, formatNumber, formatPrice, onResultsReady,
  onAnalysisStart, onAnalysisProgress, onAnalysisComplete, activeAnalysis,
  preloadedRunners = [],
  isRefreshingRunners = false,
  lastRefreshed = null,
  onRefreshRunners,
  onMinimize,
}: TrendingPanelCoreProps) {
  const [runners, setRunners]                   = useState<any[]>(preloadedRunners);
  const [isLoading, setIsLoading]               = useState<boolean>(false);
  const [isLiveRefreshing, setIsLiveRefreshing] = useState<boolean>(false);
  const [selectedRunners, setSelectedRunners]   = useState<any[]>([]);
  const [isBatchAnalyzing, setIsBatchAnalyzing] = useState<boolean>(false);
  const [isSingleAnalyzing, setIsSingleAnalyzing] = useState<boolean>(false);
  const [analyzingToken, setAnalyzingToken]     = useState<string | null>(null);
  const [currentJobId, setCurrentJobId]         = useState<string | null>(null);
  const [analysisProgress, setAnalysisProgress] = useState<Record<string, any>>({ current: 0, total: 0, phase: '' });
  const [analysisTimedOut, setAnalysisTimedOut] = useState<boolean>(false);
  const [timeoutMessage, setTimeoutMessage]     = useState<string>('');
  const [queuePosition, setQueuePosition]       = useState<number | null>(null);
  const [estimatedWait, setEstimatedWait]       = useState<number | null>(null);
  const [liveUpdate, setLiveUpdate]             = useState<boolean>(false);
  const [lastUpdated, setLastUpdated]           = useState<Date | null>(lastRefreshed ? new Date(lastRefreshed) : null);
  const [showBatch, setShowBatch]               = useState<boolean>(false);
  const [showFilters, setShowFilters]           = useState<boolean>(false);
  const [filters, setFilters]                   = useState<Record<string, any>>(() => {
    try { return JSON.parse(localStorage.getItem('trendingFilters') || 'null') || defaultFilters(); }
    catch { return defaultFilters(); }
  });

  const liveIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef    = useRef<number>(0);

  function defaultFilters() {
    return { timeframe: '7d', minMultiplier: 5, minLiquidity: 10000, minVolume: 50000 };
  }

  useEffect(() => {
    if (preloadedRunners.length > 0 && runners.length === 0) setRunners(preloadedRunners);
  }, [preloadedRunners]); // eslint-disable-line

  useEffect(() => {
    if (lastRefreshed) setLastUpdated(new Date(lastRefreshed));
  }, [lastRefreshed]);

  useEffect(() => {
    localStorage.setItem('trendingFilters', JSON.stringify(filters));
  }, [filters]);

  useEffect(() => { fetchLeaderboard(); }, [filters.timeframe, filters.minMultiplier]); // eslint-disable-line

  useEffect(() => {
    if (liveUpdate) { liveIntervalRef.current = setInterval(refreshMarketData, LIVE_INTERVAL_MS); }
    else { clearInterval(liveIntervalRef.current); }
    return () => clearInterval(liveIntervalRef.current);
  }, [liveUpdate, filters]); // eslint-disable-line

  useEffect(() => {
    return () => { if (pollIntervalRef.current) clearInterval(pollIntervalRef.current); };
  }, []);

  const fetchLeaderboard = async () => {
    setIsLoading(true);
    setSelectedRunners([]);
    try {
      const params = new URLSearchParams({
        timeframe: filters.timeframe, min_multiplier: filters.minMultiplier,
        min_liquidity: filters.minLiquidity, min_volume: filters.minVolume,
      });
      const res  = await fetch(`${apiUrl}/api/wallets/trending/runners?${params}`);
      const data = await res.json();
      if (data.success) {
        setRunners(data.runners || []);
        setLastUpdated(new Date());
        onRefreshRunners?.(data.runners || []);
      }
    } catch (err) { console.error('Leaderboard fetch error:', err); }
    finally { setIsLoading(false); }
  };

  const refreshMarketData = async () => {
    setIsLiveRefreshing(true);
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/trending/runners/live`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timeframe: filters.timeframe, min_multiplier: filters.minMultiplier, min_liquidity: filters.minLiquidity }),
      });
      const data = await res.json();
      if (data.success && data.runners) {
        setRunners(data.runners);
        setLastUpdated(new Date());
        onRefreshRunners?.(data.runners);
      }
    } catch (err) { console.error('Live refresh error:', err); }
    finally { setIsLiveRefreshing(false); }
  };

  const cancelAnalysis = useCallback(async () => {
    if (currentJobId) {
      try { await fetch(`${apiUrl}/api/wallets/jobs/${currentJobId}/cancel`, { method: 'POST' }); } catch (_) {}
    }
    if (pollIntervalRef.current) { clearInterval(pollIntervalRef.current); pollIntervalRef.current = null; }
    pollCountRef.current = 0;
    setIsBatchAnalyzing(false);
    setIsSingleAnalyzing(false);
    setAnalyzingToken(null);
    setCurrentJobId(null);
    setAnalysisProgress({ current: 0, total: 0, phase: '' });
    setAnalysisTimedOut(false);
    setTimeoutMessage('');
    setQueuePosition(null);
    setEstimatedWait(null);
  }, [currentJobId, apiUrl]);

  const attemptRecovery = async (jobId) => {
    setTimeoutMessage('Attempting to recover result from server…');
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/jobs/${jobId}/recover`, { method: 'POST' });
      const data = await res.json();
      if (data.results) {
        onAnalysisComplete(data.results);
        if (onResultsReady) onResultsReady(data.results, 'trending-batch');
        cancelAnalysis();
        onClose();
        return true;
      }
    } catch (_) {}
    setTimeoutMessage('No recoverable result found. Please retry.');
    return false;
  };

  const startPolling = (jobId, resultType, total) => {
    pollCountRef.current = 0;
    pollIntervalRef.current = setInterval(async () => {
      if (++pollCountRef.current > MAX_POLL_ATTEMPTS) {
        clearInterval(pollIntervalRef.current);
        setAnalysisTimedOut(true);
        setTimeoutMessage('⏱️ Analysis timed out after 20 minutes.');
        await attemptRecovery(jobId);
        return;
      }
      try {
        const res  = await fetch(`${apiUrl}/api/wallets/jobs/${jobId}/progress`);
        const data = await res.json();
        if (data.success) {
          if (data.queue_position) { setQueuePosition(data.queue_position); setEstimatedWait(data.estimated_wait); }
          const progress = { current: data.tokens_completed || 0, total: data.tokens_total || total, phase: data.phase || '' };
          setAnalysisProgress(progress);
          onAnalysisProgress(progress);
          if (data.status === 'completed') {
            clearInterval(pollIntervalRef.current);
            const rRes  = await fetch(`${apiUrl}/api/wallets/jobs/${jobId}`);
            const rData = await rRes.json();
            onAnalysisComplete(rData);
            if (onResultsReady) onResultsReady(rData, resultType);
            cancelAnalysis();
            onClose();
          } else if (data.status === 'failed') {
            clearInterval(pollIntervalRef.current);
            toast.error('Analysis failed');
            cancelAnalysis();
          }
        }
      } catch (err) { console.error('Poll error:', err); }
    }, POLL_INTERVAL_MS);
  };

  const handleSingleAnalysis = async (token) => {
    cancelAnalysis();
    setIsSingleAnalyzing(true);
    setAnalyzingToken(token.address);
    setAnalysisProgress({ current: 0, total: 1, phase: 'Starting…' });
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/trending/analyze`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, runner: { address: token.address, chain: token.chain, symbol: token.ticker || token.symbol } }),
      });
      const data = await res.json();
      if (data.success && data.job_id) {
        setCurrentJobId(data.job_id);
        onAnalysisStart({ jobId: data.job_id, total: 1, analysisType: 'trending-single', token: token.symbol });
        startPolling(data.job_id, 'trending-single', 1);
      } else { toast.error('Failed to start analysis'); cancelAnalysis(); }
    } catch (err) { console.error('Single analysis error:', err); cancelAnalysis(); }
  };

  const handleBatchAnalyze = async () => {
    if (!selectedRunners.length) { toast.warning('Select at least one token'); return; }
    cancelAnalysis();
    setIsBatchAnalyzing(true);
    setAnalysisProgress({ current: 0, total: selectedRunners.length, phase: 'Starting…' });
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/trending/analyze-batch`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId, min_runner_hits: 2, min_roi_multiplier: 3.0,
          runners: selectedRunners.map(t => ({ address: t.address, chain: t.chain, symbol: t.ticker || t.symbol })),
        }),
      });
      const data = await res.json();
      if (data.success && data.job_id) {
        setCurrentJobId(data.job_id);
        onAnalysisStart({ jobId: data.job_id, total: selectedRunners.length, analysisType: 'trending-batch', runners: selectedRunners.map(r => r.symbol) });
        startPolling(data.job_id, 'trending-batch', selectedRunners.length);
      } else { toast.error('Failed to start batch analysis'); cancelAnalysis(); }
    } catch (err) { console.error('Batch error:', err); cancelAnalysis(); }
  };

  const toggleSelect = (token) => {
    const key = `${token.address}:${token.chain}`;
    setSelectedRunners(prev => {
      const exists = prev.some(t => `${t.address}:${t.chain}` === key);
      return exists ? prev.filter(t => `${t.address}:${t.chain}` !== key) : [...prev, token];
    });
  };

  const isAnalysisRunning = isBatchAnalyzing || isSingleAnalyzing;

  // Shared button style helpers
  const filterBtnBase = {
    flex: 1, padding: '6px 0', borderRadius: 6,
    fontFamily: 'monospace', fontSize: 10, fontWeight: 700,
    cursor: 'pointer', transition: 'all 0.15s',
  };
  const sectionLabel = {
    fontFamily: 'monospace', fontSize: 9, color: '#64748b',
    textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 6,
  };

  // ── RENDER ────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>

      {/* ── Header bar ─────────────────────────────────────────────────────── */}
      <div style={{
        padding: '14px 16px',
        background: 'rgba(255,255,255,0.04)',
        borderBottom: '1px solid rgba(255,255,255,0.10)',
        flexShrink: 0,
      }}>
        {/* Title row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 32, height: 32, borderRadius: 8,
              background: 'rgba(251,146,60,0.18)', border: '1px solid rgba(251,146,60,0.35)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <TrendingUp size={15} color="#fb923c" />
            </div>
            <div>
              <div style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: '#f1f5f9', letterSpacing: '0.04em' }}>
                TRENDING RUNNERS
              </div>
              {lastUpdated && (
                <div style={{ fontFamily: 'monospace', fontSize: 9, color: '#64748b', marginTop: 2 }}>
                  {isLiveRefreshing
                    ? <span style={{ color: '#34d399' }}>↻ re-ranking momentum…</span>
                    : `updated ${formatTs(lastUpdated)}`
                  }
                  {liveUpdate && !isLiveRefreshing && <span style={{ color: '#34d399', marginLeft: 6 }}>· auto every 60s</span>}
                </div>
              )}
            </div>
          </div>

          {/* Controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {/* Live toggle */}
            <button
              onClick={() => setLiveUpdate(v => !v)}
              style={{
                display: 'flex', alignItems: 'center', gap: 5,
                padding: '5px 10px', borderRadius: 6,
                background: liveUpdate ? 'rgba(52,211,153,0.15)' : 'rgba(255,255,255,0.06)',
                border: `1px solid ${liveUpdate ? 'rgba(52,211,153,0.40)' : 'rgba(255,255,255,0.12)'}`,
                color: liveUpdate ? '#34d399' : '#94a3b8',
                fontFamily: 'monospace', fontSize: 10, fontWeight: 700,
                cursor: 'pointer', transition: 'all 0.15s',
              }}
            >
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: liveUpdate ? '#34d399' : '#475569', boxShadow: liveUpdate ? '0 0 6px #34d399' : 'none' }} />
              LIVE
            </button>

            {/* Refresh */}
            <button
              onClick={fetchLeaderboard}
              disabled={isLoading}
              style={{
                width: 32, height: 32, borderRadius: 6,
                background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
                color: isLoading ? '#fb923c' : '#94a3b8',
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                opacity: isLoading ? 0.8 : 1,
              }}
            >
              <RefreshCw size={13} style={{ animation: isLoading ? 'spin 1s linear infinite' : 'none' }} />
            </button>

            {/* Minimize */}
            {isAnalysisRunning && onMinimize && (
              <button
                onClick={onMinimize}
                title="Minimize to background"
                style={{
                  width: 32, height: 32, borderRadius: 6,
                  background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
                  color: '#94a3b8', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                <Minimize2 size={13} />
              </button>
            )}
          </div>
        </div>

        {/* Background refresh indicator */}
        {isRefreshingRunners && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '5px 10px', borderRadius: 6,
            background: 'rgba(52,211,153,0.10)', border: '1px solid rgba(52,211,153,0.20)',
            fontFamily: 'monospace', fontSize: 9, color: '#34d399', marginBottom: 10,
          }}>
            <RefreshCw size={9} style={{ animation: 'spin 1s linear infinite' }} />
            refreshing runners in background…
          </div>
        )}

        {/* ── Timeframe selector ── */}
        <div style={{ marginBottom: 10 }}>
          <div style={sectionLabel}>Timeframe</div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {[
              { value: '7d',  label: '7 days'  },
              { value: '14d', label: '14 days' },
              { value: '30d', label: '30 days' },
            ].map(opt => (
              <button
                key={opt.value}
                onClick={() => setFilters(p => ({ ...p, timeframe: opt.value }))}
                disabled={isAnalysisRunning}
                style={{
                  ...filterBtnBase,
                  background: filters.timeframe === opt.value
                    ? 'rgba(251,146,60,0.18)'
                    : 'rgba(255,255,255,0.06)',
                  border: filters.timeframe === opt.value
                    ? '1px solid rgba(251,146,60,0.45)'
                    : '1px solid rgba(255,255,255,0.10)',
                  color: filters.timeframe === opt.value ? '#fb923c' : '#94a3b8',
                  opacity: isAnalysisRunning ? 0.4 : 1,
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Min multiplier selector ── */}
        <div>
          <div style={sectionLabel}>Min multiplier</div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {[5, 10, 20, 50].map(m => {
              const mc     = MULT_COLORS[m];
              const active = filters.minMultiplier === m;
              return (
                <button
                  key={m}
                  onClick={() => setFilters(p => ({ ...p, minMultiplier: m }))}
                  disabled={isAnalysisRunning}
                  style={{
                    ...filterBtnBase,
                    fontSize: 11, fontWeight: 900,
                    background: active ? mc.bg : 'rgba(255,255,255,0.06)',
                    border: active ? `1px solid ${mc.border}` : '1px solid rgba(255,255,255,0.10)',
                    color: active ? mc.text : '#94a3b8',
                    boxShadow: active ? `0 0 10px ${mc.glow}` : 'none',
                    opacity: isAnalysisRunning ? 0.4 : 1,
                  }}
                >
                  {m}x
                </button>
              );
            })}
          </div>
        </div>

        {/* ── Advanced filters toggle ── */}
        <button
          onClick={() => setShowFilters(v => !v)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            width: '100%', marginTop: 10, padding: '6px 10px',
            background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.10)',
            borderRadius: 6, cursor: 'pointer', color: '#94a3b8',
            fontFamily: 'monospace', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.1em',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <Filter size={10} /> Advanced filters
          </span>
          {showFilters ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
        </button>

        <AnimatePresence>
          {showFilters && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.16 }}
              style={{ overflow: 'hidden' }}
            >
              <div style={{ paddingTop: 10, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {[
                  { field: 'minLiquidity', label: 'Min Liquidity ($)' },
                  { field: 'minVolume',    label: 'Min Volume ($)'    },
                ].map(({ field, label }) => (
                  <div key={field}>
                    <div style={{ ...sectionLabel, marginBottom: 5 }}>{label}</div>
                    <input
                      type="number" min="0" value={filters[field]}
                      onChange={e => { const v = parseInt(e.target.value, 10); setFilters(p => ({ ...p, [field]: isNaN(v) || v < 0 ? 0 : v })); }}
                      disabled={isAnalysisRunning}
                      style={{
                        width: '100%', padding: '6px 10px', borderRadius: 6,
                        background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
                        color: '#e2e8f0', fontFamily: 'monospace', fontSize: 11,
                        outline: 'none', boxSizing: 'border-box',
                        opacity: isAnalysisRunning ? 0.4 : 1,
                      }}
                    />
                  </div>
                ))}
                <button
                  onClick={fetchLeaderboard}
                  disabled={isAnalysisRunning}
                  style={{
                    gridColumn: '1 / -1', padding: '7px', borderRadius: 6,
                    border: '1px solid rgba(139,92,246,0.35)',
                    background: 'rgba(139,92,246,0.18)', color: '#c084fc',
                    fontFamily: 'monospace', fontSize: 10, fontWeight: 700,
                    cursor: 'pointer', opacity: isAnalysisRunning ? 0.4 : 1,
                  }}
                >
                  Apply &amp; Refresh
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Analysis banners ─────────────────────────────────────────────────── */}
      <div style={{ flexShrink: 0 }}>
        {/* Timeout banner */}
        {analysisTimedOut && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', background: 'rgba(249,115,22,0.10)', borderBottom: '1px solid rgba(249,115,22,0.25)' }}>
            <AlertTriangle size={14} color="#fb923c" />
            <div style={{ flex: 1, fontFamily: 'monospace', fontSize: 10, color: '#cbd5e1' }}>{timeoutMessage}</div>
            <button
              onClick={() => currentJobId && attemptRecovery(currentJobId)}
              style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 8px', borderRadius: 5, border: '1px solid rgba(249,115,22,0.35)', background: 'rgba(249,115,22,0.15)', color: '#fb923c', fontFamily: 'monospace', fontSize: 9, fontWeight: 700, cursor: 'pointer' }}
            >
              <RotateCcw size={10} /> Retry
            </button>
          </div>
        )}

        {/* Active analysis from parent */}
        {activeAnalysis && !isAnalysisRunning && (
          <div style={{ padding: '10px 16px', background: 'rgba(52,211,153,0.08)', borderBottom: '1px solid rgba(52,211,153,0.20)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Activity size={12} color="#34d399" style={{ animation: 'pulse 2s ease-in-out infinite' }} />
                <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#34d399', fontWeight: 700 }}>ANALYSIS IN PROGRESS</span>
              </div>
              {onMinimize && (
                <button onClick={onMinimize} style={{ display: 'flex', alignItems: 'center', gap: 3, padding: '3px 7px', borderRadius: 4, border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.06)', color: '#94a3b8', fontFamily: 'monospace', fontSize: 9, cursor: 'pointer' }}>
                  <Minimize2 size={9} /> minimize
                </button>
              )}
            </div>
            <ProgressBar current={activeAnalysis.progress?.current || 0} total={activeAnalysis.progress?.total || 1} phase={activeAnalysis.progress?.phase} color="#34d399" />
            {activeAnalysis.in_queue && (
              <div style={{ fontFamily: 'monospace', fontSize: 9, color: '#fbbf24', marginTop: 4 }}>
                ⏳ #{activeAnalysis.queue_position || '?'} in queue{activeAnalysis.estimated_wait && ` · ~${activeAnalysis.estimated_wait}m wait`}
              </div>
            )}
          </div>
        )}

        {/* In-progress banner (local job) */}
        {isAnalysisRunning && (
          <div style={{ padding: '10px 16px', background: 'rgba(99,102,241,0.08)', borderBottom: '1px solid rgba(99,102,241,0.20)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Activity size={12} color="#818cf8" style={{ animation: 'pulse 2s ease-in-out infinite' }} />
                <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#818cf8', fontWeight: 700 }}>
                  {isBatchAnalyzing ? `BATCH · ${selectedRunners.length} tokens` : 'ANALYZING'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 5 }}>
                {onMinimize && (
                  <button onClick={onMinimize} style={{ display: 'flex', alignItems: 'center', gap: 3, padding: '4px 7px', borderRadius: 4, border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.06)', color: '#94a3b8', fontFamily: 'monospace', fontSize: 9, fontWeight: 700, cursor: 'pointer' }}>
                    <Minimize2 size={9} /> minimize
                  </button>
                )}
                <button
                  onClick={cancelAnalysis}
                  style={{ display: 'flex', alignItems: 'center', gap: 3, padding: '4px 7px', borderRadius: 4, border: '1px solid rgba(239,68,68,0.35)', background: 'rgba(239,68,68,0.12)', color: '#f87171', fontFamily: 'monospace', fontSize: 9, fontWeight: 700, cursor: 'pointer' }}
                >
                  <XCircle size={9} /> cancel
                </button>
              </div>
            </div>
            <ProgressBar current={analysisProgress.current} total={Math.max(analysisProgress.total, 1)} phase={analysisProgress.phase} color="#818cf8" />
            {queuePosition && (
              <div style={{ fontFamily: 'monospace', fontSize: 9, color: '#fbbf24', marginTop: 4 }}>
                ⏳ #{queuePosition} in queue{estimatedWait && ` · ~${estimatedWait}m wait`}
              </div>
            )}
            <div style={{ fontFamily: 'monospace', fontSize: 8, color: '#64748b', marginTop: 4 }}>
              Leaderboard stays live while analysis runs — safe to minimize
            </div>
          </div>
        )}

        {/* Live mode info */}
        {liveUpdate && (
          <div style={{ padding: '7px 16px', background: 'rgba(52,211,153,0.06)', borderBottom: '1px solid rgba(52,211,153,0.15)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#34d399', boxShadow: '0 0 6px #34d399', flexShrink: 0 }} />
            <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#34d399' }}>
              Live — price, volume &amp; holders refresh every 60s · re-ranks by momentum surge
            </span>
          </div>
        )}
      </div>

      {/* ── Batch toolbar ─────────────────────────────────────────────────────── */}
      {runners.length > 0 && (
        <div style={{
          flexShrink: 0, borderBottom: '1px solid rgba(255,255,255,0.08)',
          background: 'rgba(255,255,255,0.02)',
        }}>
          <button
            onClick={() => setShowBatch(v => !v)}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              width: '100%', padding: '10px 16px',
              background: 'none', border: 'none', cursor: 'pointer',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Sparkles size={14} color="#818cf8" />
              <span style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 700, color: '#818cf8' }}>BATCH ANALYSIS</span>
              {selectedRunners.length > 0 && (
                <span style={{
                  fontFamily: 'monospace', fontSize: 9, padding: '2px 7px', borderRadius: 10,
                  background: 'rgba(99,102,241,0.18)', border: '1px solid rgba(99,102,241,0.35)',
                  color: '#818cf8',
                }}>
                  {selectedRunners.length} / {runners.length}
                </span>
              )}
            </div>
            {showBatch ? <ChevronUp size={14} color="#64748b" /> : <ChevronDown size={14} color="#64748b" />}
          </button>

          <AnimatePresence>
            {showBatch && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.15 }}
                style={{ overflow: 'hidden' }}
              >
                <div style={{ padding: '0 16px 14px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#64748b' }}>
                      Select tokens to find common smart-money wallets
                    </span>
                    <div style={{ display: 'flex', gap: 5 }}>
                      <button onClick={() => setSelectedRunners([...runners])} disabled={isAnalysisRunning}
                        style={{ padding: '3px 9px', borderRadius: 4, border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.07)', color: '#94a3b8', fontFamily: 'monospace', fontSize: 9, cursor: 'pointer', opacity: isAnalysisRunning ? 0.4 : 1 }}>
                        All
                      </button>
                      <button onClick={() => { setSelectedRunners([]); cancelAnalysis(); }} disabled={isAnalysisRunning}
                        style={{ padding: '3px 9px', borderRadius: 4, border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.07)', color: '#94a3b8', fontFamily: 'monospace', fontSize: 9, cursor: 'pointer', opacity: isAnalysisRunning ? 0.4 : 1 }}>
                        Clear
                      </button>
                    </div>
                  </div>
                  <button
                    onClick={handleBatchAnalyze}
                    disabled={!selectedRunners.length || isAnalysisRunning}
                    style={{
                      width: '100%', padding: '9px', borderRadius: 6,
                      background: selectedRunners.length && !isAnalysisRunning
                        ? 'linear-gradient(135deg, rgba(99,102,241,0.30), rgba(139,92,246,0.30))'
                        : 'rgba(255,255,255,0.04)',
                      border: selectedRunners.length && !isAnalysisRunning
                        ? '1px solid rgba(99,102,241,0.45)'
                        : '1px solid rgba(255,255,255,0.08)',
                      color: selectedRunners.length && !isAnalysisRunning ? '#c084fc' : '#475569',
                      fontFamily: 'monospace', fontSize: 11, fontWeight: 700,
                      cursor: selectedRunners.length && !isAnalysisRunning ? 'pointer' : 'not-allowed',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                      transition: 'all 0.15s',
                    }}
                  >
                    <Sparkles size={13} />
                    Analyze {selectedRunners.length || 0} Selected
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* ── Column headers ────────────────────────────────────────────────────── */}
      {runners.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: showBatch ? '28px 22px 1fr auto' : '28px 1fr auto',
          gap: 10, padding: '7px 16px',
          background: 'rgba(255,255,255,0.04)', borderBottom: '1px solid rgba(255,255,255,0.08)',
          fontFamily: 'monospace', fontSize: 8, textTransform: 'uppercase',
          letterSpacing: '0.1em', color: '#64748b', flexShrink: 0,
        }}>
          <div style={{ textAlign: 'center' }}>#</div>
          {showBatch && <div />}
          <div>Token</div>
          <div style={{ textAlign: 'right' }}>Action</div>
        </div>
      )}

      {/* ── Runner list ───────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.10) transparent' }}>
        {isLoading ? (
          <div style={{ padding: '16px' }}>
            {[...Array(5)].map((_, i) => (
              <div key={`skeleton-${i}`} style={{ height: 84, borderRadius: 6, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)', marginBottom: 6, animation: 'pulse 1.5s ease-in-out infinite' }} />
            ))}
          </div>
        ) : runners.length === 0 ? (
          <div style={{ padding: '48px 24px', textAlign: 'center' }}>
            <TrendingUp size={36} style={{ color: 'rgba(255,255,255,0.12)', margin: '0 auto 12px', display: 'block' }} />
            <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#475569', marginBottom: 4 }}>No trending runners found</div>
            <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#334155', marginBottom: 16 }}>Adjust filters or wait for new tokens to qualify</div>
            <button
              onClick={fetchLeaderboard}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 14px', borderRadius: 6, border: '1px solid rgba(251,146,60,0.35)', background: 'rgba(251,146,60,0.12)', color: '#fb923c', fontFamily: 'monospace', fontSize: 10, fontWeight: 700, cursor: 'pointer' }}
            >
              <RefreshCw size={11} /> Refresh
            </button>
          </div>
        ) : (
          runners.map((token, idx) => (
            <RunnerCard
              key={`${token.chain}-${token.address}`}
              token={token}
              rank={idx + 1}
              isSelected={selectedRunners.some(t => t.address === token.address && t.chain === token.chain)}
              isAnalyzingThis={isSingleAnalyzing && analyzingToken === token.address}
              isAnalysisRunning={isAnalysisRunning}
              showBatch={showBatch}
              onToggle={toggleSelect}
              onAnalyze={handleSingleAnalysis}
              onCancel={cancelAnalysis}
            />
          ))
        )}

        {/* Footer explainer */}
        {runners.length > 0 && (
          <div style={{ padding: '14px 16px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontFamily: 'monospace', fontSize: 9, color: '#475569', lineHeight: 1.8 }}>
              <span style={{ color: '#64748b', fontWeight: 700 }}>Rankings:</span> tokens earn a slot by pumping {filters.minMultiplier}x+ within {filters.timeframe}.
              {' '}<span style={{ color: '#64748b', fontWeight: 700 }}>Live mode</span> re-ranks by momentum — vol surge (40%), price (30%), holders (20%), liq (10%).
              {' '}<span style={{ color: '#64748b', fontWeight: 700 }}>↺ Refresh</span> scans for new qualifiers.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Wrapper: stale-while-revalidate ──────────────────────────────────────────
interface TrendingPanelProps extends Omit<TrendingPanelCoreProps, 'preloadedRunners' | 'isRefreshingRunners' | 'lastRefreshed' | 'onRefreshRunners'> {
  cachedRunners?: any[];
  onRunnersLoaded?: (runners: any[]) => void;
}

export default function TrendingPanel({ cachedRunners = [], onRunnersLoaded, ...coreProps }: TrendingPanelProps) {
  const { data, isFetching, dataUpdatedAt } = useTrendingRunners();
  const runners = data?.runners ?? cachedRunners;
  const lastRefreshed = dataUpdatedAt || null;
  const notifiedRef = useRef<number>(0);

  // Notify parent when fresh runners arrive
  useEffect(() => {
    if (data?.runners && dataUpdatedAt && dataUpdatedAt !== notifiedRef.current) {
      notifiedRef.current = dataUpdatedAt;
      onRunnersLoaded?.(data.runners);
    }
  }, [data, dataUpdatedAt, onRunnersLoaded]);

  const handleRunnersLoaded = useCallback((freshRunners?: any[]) => {
    if (freshRunners) onRunnersLoaded?.(freshRunners);
  }, [onRunnersLoaded]);

  return (
    <TrendingPanelCore
      {...coreProps}
      preloadedRunners={runners}
      isRefreshingRunners={isFetching}
      lastRefreshed={lastRefreshed}
      onRefreshRunners={handleRunnersLoaded}
    />
  );
}