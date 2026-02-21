import React, { useState, useEffect, useRef } from 'react';
import { TrendingUp, Filter, Sparkles, ChevronDown, CheckSquare, Square, BarChart3, Shield, RefreshCw, XCircle, ChevronUp, AlertTriangle, RotateCcw } from 'lucide-react';

const LIVE_INTERVAL_MS  = 60_000;
const POLL_INTERVAL_MS  = 3_000;
const MAX_POLL_ATTEMPTS = 400;   // 400 × 3s = 20 minutes

export default function TrendingPanel({ userId, apiUrl, onClose, formatNumber, formatPrice, onResultsReady }) {
  const [trendingRunners, setTrendingRunners] = useState([]);
  const [isLoadingTrending, setIsLoadingTrending] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedRunners, setSelectedRunners] = useState([]);
  const [isBatchAnalyzing, setIsBatchAnalyzing] = useState(false);
  const [isSingleAnalyzing, setIsSingleAnalyzing] = useState(false);
  const [analyzingToken, setAnalyzingToken] = useState(null);
  const [liveUpdate, setLiveUpdate] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [currentJobId, setCurrentJobId] = useState(null);
  const [showBatchSelection, setShowBatchSelection] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState({ current: 0, total: 0, phase: '' });
  // ✅ NEW: timeout / error state
  const [analysisTimedOut, setAnalysisTimedOut] = useState(false);
  const [timeoutMessage, setTimeoutMessage] = useState('');

  const liveIntervalRef = useRef(null);
  const pollIntervalRef = useRef(null);
  const pollCountRef    = useRef(0);

  const [filters, setFilters] = useState({
    timeframe: '7d',
    minMultiplier: 5,
    showAdvanced: false,
    minLiquidity: 10000,
    minVolume: 50000,
    chains: ['solana']
  });

  // Cache on mount
  useEffect(() => {
    const cachedRunners   = localStorage.getItem('trendingRunners');
    const cachedTimestamp = localStorage.getItem('trendingRunnersTimestamp');
    const cachedFilters   = localStorage.getItem('trendingFilters');

    if (cachedRunners && cachedTimestamp) {
      const age = Date.now() - parseInt(cachedTimestamp);
      if (age < 5 * 60 * 1000) {
        setTrendingRunners(JSON.parse(cachedRunners));
        setLastUpdated(new Date(parseInt(cachedTimestamp)));
      }
    }
    if (cachedFilters) setFilters(JSON.parse(cachedFilters));
  }, []);

  useEffect(() => {
    if (trendingRunners.length > 0) {
      localStorage.setItem('trendingRunners', JSON.stringify(trendingRunners));
      localStorage.setItem('trendingRunnersTimestamp', Date.now().toString());
    }
  }, [trendingRunners]);

  useEffect(() => {
    localStorage.setItem('trendingFilters', JSON.stringify(filters));
  }, [filters]);

  useEffect(() => { loadTrendingRunners(false); }, [filters.timeframe, filters.minMultiplier]);

  useEffect(() => {
    if (liveUpdate) {
      liveIntervalRef.current = setInterval(() => loadTrendingRunners(true), LIVE_INTERVAL_MS);
    } else {
      clearInterval(liveIntervalRef.current);
    }
    return () => clearInterval(liveIntervalRef.current);
  }, [liveUpdate, filters]);

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const loadTrendingRunners = async (silent = false) => {
    if (silent) { setIsRefreshing(true); } else { setIsLoadingTrending(true); setSelectedRunners([]); }
    try {
      const params = new URLSearchParams({
        timeframe:      filters.timeframe,
        min_multiplier: filters.minMultiplier,
        min_liquidity:  filters.minLiquidity,
        min_volume:     filters.minVolume,
      });
      const response = await fetch(`${apiUrl}/api/wallets/trending/runners?${params}`);
      const data = await response.json();
      if (data.success) { setTrendingRunners(data.runners || []); setLastUpdated(new Date()); }
    } catch (error) {
      console.error('Error loading trending runners:', error);
    } finally {
      setIsLoadingTrending(false);
      setIsRefreshing(false);
    }
  };

  const handleNumberInput = (field, rawValue) => {
    const parsed = parseInt(rawValue, 10);
    setFilters(prev => ({ ...prev, [field]: isNaN(parsed) || parsed < 0 ? 0 : parsed }));
  };

  const toggleRunnerSelection = (token) => {
    const isSelected = selectedRunners.some(t => t.address === token.address && t.chain === token.chain);
    if (isSelected) {
      setSelectedRunners(prev => prev.filter(t => !(t.address === token.address && t.chain === token.chain)));
    } else {
      setSelectedRunners(prev => [...prev, token]);
    }
  };

  const selectAll   = () => setSelectedRunners([...trendingRunners]);
  const deselectAll = () => { setSelectedRunners([]); cancelAnalysis(); };

  const cancelAnalysis = async () => {
    if (currentJobId) {
      try {
        await fetch(`${apiUrl}/api/wallets/jobs/${currentJobId}/cancel`, { method: 'POST' });
      } catch (error) {
        console.error('Error cancelling job:', error);
      }
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
  };

  // ─── Recovery helper ────────────────────────────────────────────────────────
  const attemptRecovery = async (jobId) => {
    setTimeoutMessage('Attempting to recover result from server…');
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/jobs/${jobId}/recover`, { method: 'POST' });
      const data = await res.json();
      if (data.results) {
        if (onResultsReady) onResultsReady(data.results, 'trending-batch');
        setIsBatchAnalyzing(false);
        setIsSingleAnalyzing(false);
        setAnalyzingToken(null);
        setCurrentJobId(null);
        setAnalysisTimedOut(false);
        setTimeoutMessage('');
        onClose();
        return true;
      }
    } catch (err) {
      console.warn('[TRENDING] Recovery failed:', err);
    }
    setTimeoutMessage('No recoverable result found. Please retry.');
    return false;
  };

  // ─── Shared polling starter ─────────────────────────────────────────────────
  const startPolling = (jobId, resultType) => {
    pollCountRef.current = 0;

    pollIntervalRef.current = setInterval(async () => {
      pollCountRef.current++;

      // ── Timeout guard ────────────────────────────────────────────────────────
      if (pollCountRef.current > MAX_POLL_ATTEMPTS) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
        setAnalysisTimedOut(true);
        setTimeoutMessage('⏱️ Analysis timed out after 20 minutes.');
        setAnalysisProgress(p => ({ ...p, phase: 'Timed out' }));
        // Auto-attempt recovery
        await attemptRecovery(jobId);
        return;
      }

      try {
        const response = await fetch(`${apiUrl}/api/wallets/jobs/${jobId}/progress`);
        const data = await response.json();

        if (data.success) {
          setAnalysisProgress({
            current: data.tokens_completed || 0,
            total:   data.tokens_total || 1,
            phase:   data.phase || ''
          });

          if (data.status === 'completed') {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;

            const resultRes  = await fetch(`${apiUrl}/api/wallets/jobs/${jobId}`);
            const resultData = await resultRes.json();

            if (onResultsReady) onResultsReady(resultData, resultType);

            setIsBatchAnalyzing(false);
            setIsSingleAnalyzing(false);
            setAnalyzingToken(null);
            setCurrentJobId(null);
            onClose();

          } else if (data.status === 'failed') {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
            alert('❌ Analysis failed');
            setIsBatchAnalyzing(false);
            setIsSingleAnalyzing(false);
            setAnalyzingToken(null);
            setCurrentJobId(null);
          }
        }
      } catch (error) {
        console.error('Polling error:', error);
      }
    }, POLL_INTERVAL_MS);
  };

  const handleSingleAnalysis = async (token) => {
    cancelAnalysis();
    setIsSingleAnalyzing(true);
    setAnalyzingToken(token.address);
    setAnalysisProgress({ current: 0, total: 1, phase: 'Starting...' });

    try {
      const response = await fetch(`${apiUrl}/api/wallets/trending/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          runner: {
            address: token.address,
            chain:   token.chain,
            symbol:  token.ticker || token.symbol
          }
        })
      });
      const data = await response.json();

      if (data.success && data.job_id) {
        setCurrentJobId(data.job_id);
        startPolling(data.job_id, 'trending-single');
      } else {
        alert('Failed to start analysis');
        setIsSingleAnalyzing(false);
        setAnalyzingToken(null);
      }
    } catch (error) {
      console.error('Single analysis error:', error);
      alert('Analysis failed');
      setIsSingleAnalyzing(false);
      setAnalyzingToken(null);
    }
  };

  const handleBatchAnalyze = async () => {
    if (selectedRunners.length === 0) { alert('Please select at least one token'); return; }
    cancelAnalysis();
    setIsBatchAnalyzing(true);
    setAnalysisProgress({ current: 0, total: selectedRunners.length, phase: 'Starting...' });

    try {
      const response = await fetch(`${apiUrl}/api/wallets/trending/analyze-batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id:          userId,
          min_runner_hits:  2,
          min_roi_multiplier: 3.0,
          runners: selectedRunners.map(token => ({
            address: token.address,
            chain:   token.chain,
            symbol:  token.ticker || token.symbol
          })),
        })
      });
      const data = await response.json();

      if (data.success && data.job_id) {
        setCurrentJobId(data.job_id);
        startPolling(data.job_id, 'trending-batch');
      } else {
        alert('Failed to start batch analysis');
        setIsBatchAnalyzing(false);
      }
    } catch (error) {
      console.error('Batch analysis error:', error);
      alert('Analysis failed');
      setIsBatchAnalyzing(false);
    }
  };

  const formatTime = (date) => date
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null;

  const isAnalysisRunning = isBatchAnalyzing || isSingleAnalyzing;

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-gray-500 min-h-[16px]">
          {isRefreshing && <span className="text-orange-400 flex items-center gap-1"><RefreshCw size={11} className="animate-spin" /> Refreshing…</span>}
          {!isRefreshing && lastUpdated && <span>Updated {formatTime(lastUpdated)}</span>}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => loadTrendingRunners(false)}
            disabled={isLoadingTrending || isRefreshing || isAnalysisRunning}
            className="p-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg transition disabled:opacity-40"
          >
            <RefreshCw size={15} className={isRefreshing || isLoadingTrending ? 'animate-spin text-orange-400' : 'text-gray-400'} />
          </button>
          <button
            onClick={() => setLiveUpdate(v => !v)}
            disabled={isAnalysisRunning}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
              liveUpdate
                ? 'bg-green-500/20 border-green-500/50 text-green-400'
                : 'bg-white/5 border-white/10 text-gray-400 hover:bg-white/10'
            } ${isAnalysisRunning ? 'opacity-40 cursor-not-allowed' : ''}`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${liveUpdate ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
            {liveUpdate ? 'Live' : 'Live Off'}
          </button>
        </div>
      </div>

      {/* ✅ NEW: Timeout / recovery banner */}
      {analysisTimedOut && (
        <div className="bg-orange-500/10 border border-orange-500/30 rounded-xl p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} className="text-orange-400 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-orange-400">Analysis Timed Out</div>
              <p className="text-xs text-gray-400 mt-1">{timeoutMessage}</p>
            </div>
            <button
              onClick={() => {
                cancelAnalysis();
                if (currentJobId) attemptRecovery(currentJobId);
              }}
              className="shrink-0 flex items-center gap-1 px-3 py-1.5 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/30 rounded-lg text-xs font-semibold text-orange-400 transition"
            >
              <RotateCcw size={12} /> Retry Recovery
            </button>
          </div>
        </div>
      )}

      {/* Timeframe */}
      <div className="bg-gradient-to-br from-orange-900/20 to-orange-800/10 border border-orange-500/30 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <TrendingUp className="text-orange-400" size={16} /> Select Timeframe
        </h3>
        <div className="grid grid-cols-3 gap-2">
          {[
            { value: '7d',  label: '7 Days',  emoji: '📅' },
            { value: '14d', label: '14 Days', emoji: '📆' },
            { value: '30d', label: '30 Days', emoji: '🗓️' }
          ].map((option) => (
            <button
              key={option.value}
              onClick={() => setFilters(prev => ({ ...prev, timeframe: option.value }))}
              disabled={isAnalysisRunning}
              className={`px-4 py-3 rounded-lg font-semibold text-sm transition-all duration-300 ${
                filters.timeframe === option.value
                  ? 'bg-gradient-to-r from-orange-600 to-orange-500 shadow-lg shadow-orange-500/30 scale-105'
                  : 'bg-white/5 hover:bg-white/10 border border-white/10'
              } ${isAnalysisRunning ? 'opacity-40 cursor-not-allowed' : ''}`}
            >
              <div className="text-lg mb-1">{option.emoji}</div>
              <div>{option.label}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Multiplier */}
      <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/30 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Sparkles className="text-purple-400" size={16} /> Minimum Multiplier
        </h3>
        <div className="grid grid-cols-4 gap-2">
          {[
            { value: 5,  label: '5x',  color: 'yellow' },
            { value: 10, label: '10x', color: 'green'  },
            { value: 20, label: '20x', color: 'blue'   },
            { value: 50, label: '50x', color: 'purple' }
          ].map((option) => (
            <button
              key={option.value}
              onClick={() => setFilters(prev => ({ ...prev, minMultiplier: option.value }))}
              disabled={isAnalysisRunning}
              className={`px-3 py-2 rounded-lg font-bold text-sm transition-all duration-300 ${
                filters.minMultiplier === option.value
                  ? `bg-gradient-to-r from-${option.color}-600 to-${option.color}-500 shadow-lg scale-105`
                  : 'bg-white/5 hover:bg-white/10 border border-white/10'
              } ${isAnalysisRunning ? 'opacity-40 cursor-not-allowed' : ''}`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {/* Advanced filters */}
      <button
        onClick={() => setFilters(prev => ({ ...prev, showAdvanced: !prev.showAdvanced }))}
        disabled={isAnalysisRunning}
        className="w-full px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm font-semibold transition flex items-center justify-between disabled:opacity-40"
      >
        <span className="flex items-center gap-2"><Filter size={14} /> Advanced Filters</span>
        <ChevronDown size={16} className={`transition-transform ${filters.showAdvanced ? 'rotate-180' : ''}`} />
      </button>

      {filters.showAdvanced && (
        <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Min Liquidity ($) <span className="text-gray-600">default 10k</span></label>
              <input
                type="number" min="0" value={filters.minLiquidity}
                onChange={(e) => handleNumberInput('minLiquidity', e.target.value)}
                disabled={isAnalysisRunning}
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500 disabled:opacity-40"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Min Volume ($) <span className="text-gray-600">default 50k</span></label>
              <input
                type="number" min="0" value={filters.minVolume}
                onChange={(e) => handleNumberInput('minVolume', e.target.value)}
                disabled={isAnalysisRunning}
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500 disabled:opacity-40"
              />
            </div>
          </div>
          <button
            onClick={() => loadTrendingRunners(false)}
            disabled={isAnalysisRunning}
            className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-semibold transition disabled:opacity-40"
          >
            Apply Filters
          </button>
          <button
            onClick={() => setFilters(prev => ({ ...prev, minLiquidity: 10000, minVolume: 50000 }))}
            disabled={isAnalysisRunning}
            className="w-full px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs text-gray-400 transition disabled:opacity-40"
          >
            Reset to defaults
          </button>
        </div>
      )}

      {/* Batch selection header */}
      {trendingRunners.length > 0 && (
        <div className="border border-white/10 rounded-xl overflow-hidden">
          <button
            onClick={() => setShowBatchSelection(!showBatchSelection)}
            disabled={isAnalysisRunning}
            className="w-full px-4 py-3 bg-gradient-to-r from-blue-900/20 to-blue-800/10 hover:from-blue-900/30 hover:to-blue-800/20 flex items-center justify-between transition disabled:opacity-40"
          >
            <div className="flex items-center gap-2">
              <Sparkles size={18} className="text-blue-400" />
              <span className="font-semibold text-blue-400">Batch Analysis</span>
              {selectedRunners.length > 0 && (
                <span className="text-xs bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded-full">
                  {selectedRunners.length} selected
                </span>
              )}
            </div>
            {showBatchSelection ? <ChevronUp size={18} className="text-gray-400" /> : <ChevronDown size={18} className="text-gray-400" />}
          </button>

          {showBatchSelection && (
            <div className="p-4 bg-gradient-to-r from-blue-900/20 to-blue-800/10 border-t border-blue-500/30">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="text-sm font-semibold text-blue-400">{selectedRunners.length} / {trendingRunners.length} Selected</h3>
                  <p className="text-xs text-gray-400">Select multiple tokens to find common wallets</p>
                </div>
                <div className="flex gap-2">
                  <button onClick={selectAll}   disabled={isAnalysisRunning} className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-semibold transition disabled:opacity-40">Select All</button>
                  <button onClick={deselectAll} disabled={isAnalysisRunning} className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-semibold transition disabled:opacity-40">Clear</button>
                </div>
              </div>

              {isBatchAnalyzing ? (
                <div className="space-y-3">
                  <button
                    onClick={cancelAnalysis}
                    className="w-full px-4 py-3 bg-gradient-to-r from-red-600 to-red-500 hover:from-red-700 hover:to-red-600 rounded-lg font-semibold transition flex items-center justify-center gap-2 shadow-lg shadow-red-500/30"
                  >
                    <XCircle size={18} /> Cancel Analysis
                  </button>
                  <div className="bg-white/10 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-blue-500 h-2 transition-all duration-500"
                      style={{ width: `${(analysisProgress.current / Math.max(analysisProgress.total, 1)) * 100}%` }}
                    />
                  </div>
                  <div className="text-xs text-gray-400 text-center">
                    {analysisProgress.phase} ({analysisProgress.current}/{analysisProgress.total})
                  </div>
                  <p className="text-xs text-gray-600 text-center">
                    Times out after 20 min — auto-recovery will trigger
                  </p>
                </div>
              ) : (
                <button
                  onClick={handleBatchAnalyze}
                  disabled={selectedRunners.length === 0 || isSingleAnalyzing}
                  className="w-full px-4 py-3 bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 disabled:from-blue-600/30 disabled:to-blue-500/30 rounded-lg font-semibold transition flex items-center justify-center gap-2 shadow-lg shadow-blue-500/30"
                >
                  <Sparkles size={18} />
                  Batch Analyze Selected ({selectedRunners.length})
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Token list */}
      <div className="space-y-2">
        {isLoadingTrending ? (
          <div className="space-y-2">
            {[...Array(4)].map((_, i) => <div key={i} className="animate-pulse bg-white/5 border border-white/10 rounded-lg p-4 h-20" />)}
          </div>
        ) : trendingRunners.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <TrendingUp size={48} className="mx-auto mb-3 opacity-20" />
            <p className="text-sm">No trending runners found</p>
            <p className="text-xs mt-1">Try adjusting filters or check the security requirements</p>
            <button
              onClick={() => loadTrendingRunners(false)}
              disabled={isAnalysisRunning}
              className="mt-4 px-4 py-2 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/30 rounded-lg text-sm text-orange-400 font-semibold transition flex items-center gap-2 mx-auto disabled:opacity-40"
            >
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        ) : (
          trendingRunners.map((token, idx) => {
            const isSelected      = selectedRunners.some(t => t.address === token.address && t.chain === token.chain);
            const isAnalyzingThis = isSingleAnalyzing && analyzingToken === token.address;

            return (
              <div
                key={`${token.chain}-${token.address}-${idx}`}
                className={`bg-white/5 hover:bg-white/10 border rounded-lg p-4 transition ${
                  isSelected ? 'border-orange-500/50 bg-orange-500/10' : 'border-white/10'
                } ${isAnalyzingThis ? 'opacity-60' : ''}`}
              >
                <div className="flex items-start gap-3">
                  {showBatchSelection && (
                    <button onClick={() => toggleRunnerSelection(token)} className="mt-1" disabled={isAnalysisRunning}>
                      {isSelected
                        ? <CheckSquare size={20} className="text-orange-400" />
                        : <Square size={20} className="text-gray-600 hover:text-gray-400" />
                      }
                    </button>
                  )}

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2 flex-wrap">
                      <span className="font-semibold">{token.ticker || token.symbol}</span>
                      <span className="text-xs px-2 py-0.5 bg-white/10 rounded">{token.chain?.toUpperCase()}</span>
                      <span className="text-xs px-2 py-0.5 bg-orange-500/20 text-orange-400 rounded font-bold">{token.multiplier}x</span>
                      <span className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded font-bold flex items-center gap-1">
                        <Shield size={10} /> Verified
                      </span>
                    </div>
                    <div className="text-sm text-gray-400 mb-2 truncate">{token.name}</div>
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <div><span className="text-gray-500">Liquidity:</span><span className="ml-1 text-white font-semibold">{formatNumber(token.liquidity)}</span></div>
                      <div><span className="text-gray-500">Volume:</span><span className="ml-1 text-white font-semibold">{formatNumber(token.volume_24h || token.volume)}</span></div>
                      <div><span className="text-gray-500">Price:</span><span className="ml-1 text-white font-semibold">{formatPrice(token.current_price || token.price)}</span></div>
                    </div>
                    {isAnalyzingThis && (
                      <div className="mt-2">
                        <div className="bg-white/10 rounded-full h-1 overflow-hidden">
                          <div className="bg-purple-500 h-1 w-3/4 animate-pulse" />
                        </div>
                        <p className="text-xs text-gray-600 mt-1">Times out after 20 min — auto-recovery on timeout</p>
                      </div>
                    )}
                  </div>

                  {isSingleAnalyzing && isAnalyzingThis ? (
                    <button
                      onClick={cancelAnalysis}
                      className="px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded-lg text-xs font-semibold transition whitespace-nowrap flex items-center gap-1 flex-shrink-0"
                    >
                      <XCircle size={14} /> Cancel
                    </button>
                  ) : (
                    <button
                      onClick={() => handleSingleAnalysis(token)}
                      disabled={isAnalysisRunning}
                      className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold transition whitespace-nowrap flex items-center gap-1 flex-shrink-0 disabled:opacity-50"
                    >
                      {isSingleAnalyzing && !isAnalyzingThis
                        ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        : <BarChart3 size={14} />
                      }
                      {isSingleAnalyzing && !isAnalyzingThis ? 'Analyzing...' : 'Analyze'}
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
          💡 <strong>Batch Analysis Tip:</strong> Select multiple tokens to find wallets that hit several runners. This reveals the most competent smart money.
        </p>
      </div>
    </div>
  );
}