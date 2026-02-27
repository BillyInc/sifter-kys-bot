import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  TrendingUp, Filter, Sparkles, ChevronDown, CheckSquare, Square,
  BarChart3, Shield, RefreshCw, XCircle, ChevronUp, AlertTriangle, RotateCcw, Activity
} from 'lucide-react';

const LIVE_INTERVAL_MS  = 60_000;
const POLL_INTERVAL_MS  = 3_000;
const MAX_POLL_ATTEMPTS = 400;      // 400 × 3s = 20 min

// ─── Inner panel (pure display — receives runners as props) ────────────────────
function TrendingPanelCore({
  userId, apiUrl, onClose, formatNumber, formatPrice, onResultsReady,
  onAnalysisStart, onAnalysisProgress, onAnalysisComplete, activeAnalysis,
  // Cache-aware props injected by the wrapper:
  preloadedRunners = [],
  isRefreshingRunners = false,
  lastRefreshed = null,
  onRefreshRunners,
}) {
  const [runners, setRunners]         = useState(preloadedRunners);
  const [isLoading, setIsLoading]     = useState(false);
  const [isLiveRefreshing, setIsLiveRefreshing] = useState(false);

  const [selectedRunners, setSelectedRunners]   = useState([]);
  const [isBatchAnalyzing, setIsBatchAnalyzing] = useState(false);
  const [isSingleAnalyzing, setIsSingleAnalyzing] = useState(false);
  const [analyzingToken, setAnalyzingToken]     = useState(null);
  const [currentJobId, setCurrentJobId]         = useState(null);
  const [analysisProgress, setAnalysisProgress] = useState({ current: 0, total: 0, phase: '' });
  const [analysisTimedOut, setAnalysisTimedOut] = useState(false);
  const [timeoutMessage, setTimeoutMessage]     = useState('');

  const [queuePosition, setQueuePosition]       = useState(null);
  const [estimatedWait, setEstimatedWait]       = useState(null);

  const [liveUpdate, setLiveUpdate]     = useState(false);
  const [lastUpdated, setLastUpdated]   = useState(lastRefreshed ? new Date(lastRefreshed) : null);
  const [showBatch, setShowBatch]       = useState(false);

  const [filters, setFilters] = useState(() => {
    try { return JSON.parse(localStorage.getItem('trendingFilters')) || defaultFilters(); }
    catch { return defaultFilters(); }
  });

  const liveIntervalRef = useRef(null);
  const pollIntervalRef = useRef(null);
  const pollCountRef    = useRef(0);

  function defaultFilters() {
    return { timeframe: '7d', minMultiplier: 5, minLiquidity: 10000, minVolume: 50000, showAdvanced: false };
  }

  // Sync preloaded runners when wrapper passes them in
  useEffect(() => {
    if (preloadedRunners.length > 0 && runners.length === 0) {
      setRunners(preloadedRunners);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preloadedRunners]);

  // Also sync lastRefreshed → lastUpdated
  useEffect(() => {
    if (lastRefreshed) setLastUpdated(new Date(lastRefreshed));
  }, [lastRefreshed]);

  useEffect(() => {
    localStorage.setItem('trendingFilters', JSON.stringify(filters));
  }, [filters]);

  // Trigger full leaderboard fetch when timeframe / multiplier changes
  useEffect(() => { fetchLeaderboard(); }, [filters.timeframe, filters.minMultiplier]); // eslint-disable-line

  // Live interval — re-rank market data
  useEffect(() => {
    if (liveUpdate) {
      liveIntervalRef.current = setInterval(() => refreshMarketData(), LIVE_INTERVAL_MS);
    } else {
      clearInterval(liveIntervalRef.current);
    }
    return () => clearInterval(liveIntervalRef.current);
  }, [liveUpdate, filters]); // eslint-disable-line

  useEffect(() => {
    return () => { if (pollIntervalRef.current) clearInterval(pollIntervalRef.current); };
  }, []);

  // ── FULL LEADERBOARD FETCH ────────────────────────────────────────────────
  const fetchLeaderboard = async () => {
    setIsLoading(true);
    setSelectedRunners([]);
    try {
      const params = new URLSearchParams({
        timeframe:      filters.timeframe,
        min_multiplier: filters.minMultiplier,
        min_liquidity:  filters.minLiquidity,
        min_volume:     filters.minVolume,
      });
      const res  = await fetch(`${apiUrl}/api/wallets/trending/runners?${params}`);
      const data = await res.json();
      if (data.success) {
        setRunners(data.runners || []);
        setLastUpdated(new Date());
        onRefreshRunners?.(data.runners || []); // notify wrapper to cache
      }
    } catch (err) {
      console.error('Leaderboard fetch error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // ── LIVE MARKET DATA REFRESH ──────────────────────────────────────────────
  const refreshMarketData = async () => {
    setIsLiveRefreshing(true);
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/trending/runners/live`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          timeframe:      filters.timeframe,
          min_multiplier: filters.minMultiplier,
          min_liquidity:  filters.minLiquidity,
        }),
      });
      const data = await res.json();
      if (data.success && data.runners) {
        setRunners(data.runners);
        setLastUpdated(new Date());
        onRefreshRunners?.(data.runners); // notify wrapper to cache
      }
    } catch (err) {
      console.error('Live refresh error:', err);
    } finally {
      setIsLiveRefreshing(false);
    }
  };

  // ── ANALYSIS HELPERS ──────────────────────────────────────────────────────
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
            alert('❌ Analysis failed');
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
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          runner:  { address: token.address, chain: token.chain, symbol: token.ticker || token.symbol },
        }),
      });
      const data = await res.json();
      if (data.success && data.job_id) {
        setCurrentJobId(data.job_id);
        onAnalysisStart({ jobId: data.job_id, total: 1, analysisType: 'trending-single', token: token.symbol });
        startPolling(data.job_id, 'trending-single', 1);
      } else { alert('Failed to start analysis'); cancelAnalysis(); }
    } catch (err) { console.error('Single analysis error:', err); cancelAnalysis(); }
  };

  const handleBatchAnalyze = async () => {
    if (!selectedRunners.length) { alert('Select at least one token'); return; }
    cancelAnalysis();
    setIsBatchAnalyzing(true);
    setAnalysisProgress({ current: 0, total: selectedRunners.length, phase: 'Starting…' });
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/trending/analyze-batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          min_runner_hits: 2,
          min_roi_multiplier: 3.0,
          runners: selectedRunners.map(t => ({ address: t.address, chain: t.chain, symbol: t.ticker || t.symbol })),
        }),
      });
      const data = await res.json();
      if (data.success && data.job_id) {
        setCurrentJobId(data.job_id);
        onAnalysisStart({ jobId: data.job_id, total: selectedRunners.length, analysisType: 'trending-batch', runners: selectedRunners.map(r => r.symbol) });
        startPolling(data.job_id, 'trending-batch', selectedRunners.length);
      } else { alert('Failed to start batch analysis'); cancelAnalysis(); }
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
  const formatTs = (d) => d ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';

  // ── RENDER ────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">

      {/* Analysis in progress banner */}
      {isAnalysisRunning && (
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 mb-2">
          <div className="flex items-center gap-2 text-blue-400">
            <Activity size={16} className="animate-pulse" />
            <span className="text-sm font-semibold">Analysis in progress</span>
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Leaderboard continues updating while analysis runs on selected tokens.
            {queuePosition && (
              <span className="block mt-1 text-yellow-400">
                ⏳ Queue position: #{queuePosition} {estimatedWait && `• ~${estimatedWait}m wait`}
              </span>
            )}
          </p>
        </div>
      )}

      {/* Stale-cache indicator — shown if wrapper pre-loaded data */}
      {isRefreshingRunners && (
        <div className="flex items-center gap-2 px-3 py-2 bg-green-500/10 border border-green-500/20 rounded-lg text-xs text-green-400">
          <RefreshCw size={11} className="animate-spin" />
          Refreshing runners in background…
        </div>
      )}

      {/* Status bar */}
      <div className="flex items-center justify-between gap-2 min-h-[28px]">
        <div className="text-xs text-gray-500">
          {isLiveRefreshing && (
            <span className="text-green-400 flex items-center gap-1">
              <RefreshCw size={11} className="animate-spin" /> Re-ranking by momentum…
            </span>
          )}
          {!isLiveRefreshing && lastUpdated && (
            <span>
              Updated {formatTs(lastUpdated)}
              {liveUpdate && <span className="ml-2 text-green-400">· Auto-refresh every 60s</span>}
              {isAnalysisRunning && <span className="ml-2 text-blue-400">· Live updates continue</span>}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button onClick={fetchLeaderboard} disabled={isLoading} title="Rescan for new qualifying tokens"
            className="p-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg transition disabled:opacity-40">
            <RefreshCw size={15} className={isLoading ? 'animate-spin text-orange-400' : 'text-gray-400'} />
          </button>
          <button onClick={() => setLiveUpdate(v => !v)} disabled={isLoading}
            title={liveUpdate ? 'Stop auto-refresh' : 'Auto-refresh price/volume every 60s'}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
              liveUpdate ? 'bg-green-500/20 border-green-500/50 text-green-400' : 'bg-white/5 border-white/10 text-gray-400 hover:bg-white/10'
            } disabled:opacity-40 disabled:cursor-not-allowed`}>
            <span className={`w-1.5 h-1.5 rounded-full ${liveUpdate ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
            Live
          </button>
        </div>
      </div>

      {/* Parent-managed active analysis */}
      {activeAnalysis && !isAnalysisRunning && (
        <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
            <BarChart3 className="text-green-400" size={16} /> Analysis in Progress
          </h3>
          <div className="space-y-2">
            <div className="bg-white/10 rounded-full h-2 overflow-hidden">
              <div className="bg-green-500 h-2 transition-all duration-500"
                style={{ width: `${(activeAnalysis.progress?.current / activeAnalysis.progress?.total) * 100}%` }} />
            </div>
            <p className="text-xs text-gray-400 text-center">
              {activeAnalysis.progress?.phase} ({activeAnalysis.progress?.current}/{activeAnalysis.progress?.total})
            </p>
            {activeAnalysis.in_queue && (
              <p className="text-xs text-yellow-400 text-center">
                ⏳ Queue position: #{activeAnalysis.queue_position || '?'}
                {activeAnalysis.estimated_wait && ` • ~${activeAnalysis.estimated_wait}m wait`}
              </p>
            )}
          </div>
        </div>
      )}

      {liveUpdate && (
        <div className="bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2">
          <p className="text-xs text-green-400">
            🟢 Live: price, volume &amp; holders refresh every 60s.
            Rankings update based on momentum — surging tokens rise, dead tokens sink.
          </p>
        </div>
      )}

      {/* Timeout banner */}
      {analysisTimedOut && (
        <div className="bg-orange-500/10 border border-orange-500/30 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle size={18} className="text-orange-400 shrink-0 mt-0.5" />
          <div className="flex-1">
            <div className="text-sm font-semibold text-orange-400">Analysis Timed Out</div>
            <p className="text-xs text-gray-400 mt-1">{timeoutMessage}</p>
          </div>
          <button onClick={() => currentJobId && attemptRecovery(currentJobId)}
            className="shrink-0 flex items-center gap-1 px-3 py-1.5 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/30 rounded-lg text-xs font-semibold text-orange-400 transition">
            <RotateCcw size={12} /> Retry Recovery
          </button>
        </div>
      )}

      {/* Timeframe selector */}
      <div className="bg-gradient-to-br from-orange-900/20 to-orange-800/10 border border-orange-500/30 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <TrendingUp className="text-orange-400" size={16} /> Timeframe
        </h3>
        <div className="grid grid-cols-3 gap-2">
          {[{ value: '7d', label: '7 Days', emoji: '📅' }, { value: '14d', label: '14 Days', emoji: '📆' }, { value: '30d', label: '30 Days', emoji: '🗓️' }].map(opt => (
            <button key={opt.value} onClick={() => setFilters(p => ({ ...p, timeframe: opt.value }))}
              disabled={isAnalysisRunning}
              className={`px-4 py-3 rounded-lg font-semibold text-sm transition-all ${filters.timeframe === opt.value ? 'bg-gradient-to-r from-orange-600 to-orange-500 shadow-lg shadow-orange-500/30 scale-105' : 'bg-white/5 hover:bg-white/10 border border-white/10'} disabled:opacity-40 disabled:cursor-not-allowed`}>
              <div className="text-lg mb-1">{opt.emoji}</div>{opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Min multiplier */}
      <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/30 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Sparkles className="text-purple-400" size={16} /> Minimum Multiplier
        </h3>
        <div className="grid grid-cols-4 gap-2">
          {[{ value: 5, label: '5x', cls: 'from-yellow-600 to-yellow-500 shadow-yellow-500/30' }, { value: 10, label: '10x', cls: 'from-green-600 to-green-500 shadow-green-500/30' }, { value: 20, label: '20x', cls: 'from-blue-600 to-blue-500 shadow-blue-500/30' }, { value: 50, label: '50x', cls: 'from-purple-600 to-purple-500 shadow-purple-500/30' }].map(opt => (
            <button key={opt.value} onClick={() => setFilters(p => ({ ...p, minMultiplier: opt.value }))}
              disabled={isAnalysisRunning}
              className={`px-3 py-2 rounded-lg font-bold text-sm transition-all ${filters.minMultiplier === opt.value ? `bg-gradient-to-r ${opt.cls} shadow-lg scale-105` : 'bg-white/5 hover:bg-white/10 border border-white/10'} disabled:opacity-40`}>
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Advanced filters */}
      <button onClick={() => setFilters(p => ({ ...p, showAdvanced: !p.showAdvanced }))} disabled={isAnalysisRunning}
        className="w-full px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm font-semibold transition flex items-center justify-between disabled:opacity-40">
        <span className="flex items-center gap-2"><Filter size={14} /> Advanced Filters</span>
        <ChevronDown size={16} className={`transition-transform ${filters.showAdvanced ? 'rotate-180' : ''}`} />
      </button>

      {filters.showAdvanced && (
        <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            {[{ field: 'minLiquidity', label: 'Min Liquidity ($)', hint: 'default 10k' }, { field: 'minVolume', label: 'Min Volume ($)', hint: 'default 50k' }].map(({ field, label, hint }) => (
              <div key={field}>
                <label className="block text-xs text-gray-400 mb-1">{label} <span className="text-gray-600">{hint}</span></label>
                <input type="number" min="0" value={filters[field]}
                  onChange={e => { const v = parseInt(e.target.value, 10); setFilters(p => ({ ...p, [field]: isNaN(v) || v < 0 ? 0 : v })); }}
                  disabled={isAnalysisRunning}
                  className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500 disabled:opacity-40" />
              </div>
            ))}
          </div>
          <button onClick={fetchLeaderboard} disabled={isAnalysisRunning}
            className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-semibold transition disabled:opacity-40">
            Apply Filters &amp; Refresh
          </button>
          <button onClick={() => setFilters(p => ({ ...p, minLiquidity: 10000, minVolume: 50000 }))} disabled={isAnalysisRunning}
            className="w-full px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs text-gray-400 transition disabled:opacity-40">
            Reset to defaults
          </button>
        </div>
      )}

      {/* Batch panel */}
      {runners.length > 0 && (
        <div className="border border-white/10 rounded-xl overflow-hidden">
          <button onClick={() => setShowBatch(v => !v)}
            className="w-full px-4 py-3 bg-gradient-to-r from-blue-900/20 to-blue-800/10 hover:from-blue-900/30 flex items-center justify-between transition">
            <div className="flex items-center gap-2">
              <Sparkles size={18} className="text-blue-400" />
              <span className="font-semibold text-blue-400">Batch Analysis</span>
              {selectedRunners.length > 0 && (
                <span className="text-xs bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded-full">
                  {selectedRunners.length} / {runners.length}
                </span>
              )}
            </div>
            {showBatch ? <ChevronUp size={18} className="text-gray-400" /> : <ChevronDown size={18} className="text-gray-400" />}
          </button>

          {showBatch && (
            <div className="p-4 bg-gradient-to-r from-blue-900/20 to-blue-800/10 border-t border-blue-500/30 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs text-gray-400">Select tokens to find common smart-money wallets</p>
                <div className="flex gap-2">
                  <button onClick={() => setSelectedRunners([...runners])} disabled={isAnalysisRunning}
                    className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-semibold transition disabled:opacity-40">All</button>
                  <button onClick={() => { setSelectedRunners([]); cancelAnalysis(); }} disabled={isAnalysisRunning}
                    className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-semibold transition disabled:opacity-40">Clear</button>
                </div>
              </div>

              {isBatchAnalyzing ? (
                <div className="space-y-2">
                  <button onClick={cancelAnalysis}
                    className="w-full px-4 py-3 bg-gradient-to-r from-red-600 to-red-500 hover:from-red-700 rounded-lg font-semibold flex items-center justify-center gap-2">
                    <XCircle size={18} /> Cancel Analysis
                  </button>
                  <div className="bg-white/10 rounded-full h-2 overflow-hidden">
                    <div className="bg-blue-500 h-2 transition-all duration-500"
                      style={{ width: `${(analysisProgress.current / Math.max(analysisProgress.total, 1)) * 100}%` }} />
                  </div>
                  <p className="text-xs text-gray-400 text-center">
                    {analysisProgress.phase} ({analysisProgress.current}/{analysisProgress.total})
                  </p>
                  {queuePosition && (
                    <p className="text-xs text-yellow-400 text-center">
                      ⏳ Queue position: #{queuePosition} {estimatedWait && `• ~${estimatedWait}m wait`}
                    </p>
                  )}
                </div>
              ) : (
                <button onClick={handleBatchAnalyze} disabled={!selectedRunners.length || isSingleAnalyzing}
                  className="w-full px-4 py-3 bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 disabled:opacity-40 rounded-lg font-semibold flex items-center justify-center gap-2">
                  <Sparkles size={18} /> Analyze {selectedRunners.length} Selected
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Leaderboard */}
      <div className="space-y-2">
        {isLoading ? (
          [...Array(4)].map((_, i) => (
            <div key={i} className="animate-pulse bg-white/5 border border-white/10 rounded-lg p-4 h-20" />
          ))
        ) : runners.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <TrendingUp size={48} className="mx-auto mb-3 opacity-20" />
            <p className="text-sm">No trending runners found</p>
            <p className="text-xs mt-1">Adjust filters or wait for new tokens to qualify</p>
            <button onClick={fetchLeaderboard} disabled={isAnalysisRunning}
              className="mt-4 mx-auto px-4 py-2 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/30 rounded-lg text-sm text-orange-400 font-semibold flex items-center gap-2 disabled:opacity-40">
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        ) : (
          runners.map((token, idx) => {
            const rank            = idx + 1;
            const isSelected      = selectedRunners.some(t => t.address === token.address && t.chain === token.chain);
            const isAnalyzingThis = isSingleAnalyzing && analyzingToken === token.address;

            return (
              <div key={`${token.chain}-${token.address}`}
                className={`bg-white/5 hover:bg-white/10 border rounded-lg p-4 transition ${isSelected ? 'border-orange-500/50 bg-orange-500/10' : 'border-white/10'} ${isAnalyzingThis ? 'opacity-60' : ''}`}>
                <div className="flex items-start gap-3">
                  <div className="w-6 text-center mt-0.5 flex-shrink-0">
                    <span className={`text-xs font-bold ${rank <= 3 ? 'text-yellow-400' : 'text-gray-600'}`}>#{rank}</span>
                  </div>

                  {showBatch && (
                    <button onClick={() => toggleSelect(token)} disabled={isAnalysisRunning} className="mt-1 flex-shrink-0">
                      {isSelected ? <CheckSquare size={20} className="text-orange-400" /> : <Square size={20} className="text-gray-600 hover:text-gray-400" />}
                    </button>
                  )}

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                      <span className="font-semibold">{token.ticker || token.symbol}</span>
                      <span className="text-xs px-2 py-0.5 bg-white/10 rounded">{token.chain?.toUpperCase()}</span>
                      <span className="text-xs px-2 py-0.5 bg-orange-500/20 text-orange-400 rounded font-bold">{token.multiplier}x</span>
                      <span className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded font-bold flex items-center gap-1">
                        <Shield size={10} /> Verified
                      </span>
                    </div>
                    <div className="text-sm text-gray-400 mb-2 truncate">{token.name}</div>
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <div><span className="text-gray-500">Price </span><span className="text-white font-semibold">{formatPrice(token.current_price)}</span></div>
                      <div><span className="text-gray-500">Vol </span><span className="text-white font-semibold">{formatNumber(token.volume_24h)}</span></div>
                      <div><span className="text-gray-500">Liq </span><span className="text-white font-semibold">{formatNumber(token.liquidity)}</span></div>
                    </div>
                    {token.holders && (
                      <div className="text-xs mt-1"><span className="text-gray-500">Holders </span><span className="text-white font-semibold">{token.holders.toLocaleString()}</span></div>
                    )}
                    {token.momentum_score && (
                      <div className="text-xs mt-1"><span className="text-gray-500">Momentum </span><span className="text-green-400 font-semibold">{token.momentum_score}</span></div>
                    )}
                    {isAnalyzingThis && <div className="mt-2 bg-white/10 rounded-full h-1 overflow-hidden"><div className="bg-purple-500 h-1 w-3/4 animate-pulse" /></div>}
                  </div>

                  {isSingleAnalyzing && isAnalyzingThis ? (
                    <button onClick={cancelAnalysis}
                      className="px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded-lg text-xs font-semibold flex items-center gap-1 flex-shrink-0">
                      <XCircle size={14} /> Cancel
                    </button>
                  ) : (
                    <button onClick={() => handleSingleAnalysis(token)} disabled={isAnalysisRunning}
                      className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold flex items-center gap-1 flex-shrink-0 disabled:opacity-50 transition">
                      {isSingleAnalyzing && !isAnalyzingThis
                        ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        : <BarChart3 size={14} />}
                      {isSingleAnalyzing && !isAnalyzingThis ? '…' : 'Analyze'}
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3">
        <p className="text-xs text-blue-300">
          💡 <strong>How rankings work:</strong> Tokens earn a slot by pumping {filters.minMultiplier}x+ within {filters.timeframe}.
          <span className="block mt-1">
            <strong>Live mode</strong> refreshes every 60s and re-ranks by momentum — volume surge (40%), price momentum (30%), holder growth (20%), liquidity (10%).
          </span>
          <span className="block mt-1">
            <strong>Refresh button (↺)</strong> scans for new qualifiers — can add/remove tokens.
          </span>
        </p>
      </div>
    </div>
  );
}


// ─── Wrapper: stale-while-revalidate cache layer ───────────────────────────────
// Usage in parent:
//   <TrendingPanel
//     {...existingProps}
//     cachedRunners={cachedTrendingRunners}        // from localStorage / state
//     onRunnersLoaded={runners => saveToCache(runners)}
//   />
export default function TrendingPanel({
  cachedRunners = [],
  onRunnersLoaded,
  ...coreProps
}) {
  const [runners, setRunners]         = useState(cachedRunners);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState(null);
  const fetchedRef = useRef(false);

  const fetchRunners = useCallback(async (force = false) => {
    if (isRefreshing && !force) return;
    setIsRefreshing(true);
    try {
      const params = new URLSearchParams({
        timeframe:      'TODO_MATCH_FILTER', // NOTE: wrapper uses its own quick fetch;
        // the full filter-aware fetch is handled inside TrendingPanelCore.
        // This background fetch is just to warm the cache on panel open.
      });
      const res  = await fetch(`${coreProps.apiUrl}/api/wallets/trending/runners`);
      const data = await res.json();
      if (data.success && data.runners) {
        setRunners(data.runners);
        setLastRefreshed(Date.now());
        onRunnersLoaded?.(data.runners);
      }
    } catch (e) {
      console.error('[TrendingPanel wrapper] fetch error:', e);
    } finally {
      setIsRefreshing(false);
    }
  }, [coreProps.apiUrl, onRunnersLoaded, isRefreshing]);

  useEffect(() => {
    if (!fetchedRef.current) {
      fetchedRef.current = true;
      // If we have cached runners, show them instantly then refresh in background.
      // If no cache, fetch immediately (no delay).
      setTimeout(() => fetchRunners(), cachedRunners.length > 0 ? 500 : 0);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRunnersLoaded = useCallback((freshRunners) => {
    setRunners(freshRunners);
    setLastRefreshed(Date.now());
    onRunnersLoaded?.(freshRunners);
  }, [onRunnersLoaded]);

  return (
    <TrendingPanelCore
      {...coreProps}
      preloadedRunners={runners}
      isRefreshingRunners={isRefreshing}
      lastRefreshed={lastRefreshed}
      onRefreshRunners={handleRunnersLoaded}
    />
  );
}