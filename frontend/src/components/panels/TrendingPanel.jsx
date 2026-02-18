import React, { useState, useEffect, useRef } from 'react';
import { TrendingUp, Filter, Sparkles, ChevronDown, CheckSquare, Square, BarChart3, Shield, RefreshCw } from 'lucide-react';

const LIVE_INTERVAL_MS = 60_000;

export default function TrendingPanel({ userId, apiUrl, onClose, formatNumber, formatPrice }) {
  const [trendingRunners, setTrendingRunners] = useState([]);
  const [isLoadingTrending, setIsLoadingTrending] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedRunners, setSelectedRunners] = useState([]);
  const [isBatchAnalyzing, setIsBatchAnalyzing] = useState(false);
  const [liveUpdate, setLiveUpdate] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const liveIntervalRef = useRef(null);

  const [filters, setFilters] = useState({
    timeframe: '7d',
    minMultiplier: 5,
    showAdvanced: false,
    minLiquidity: 10000,
    minVolume: 50000,
    chains: ['solana']
  });

  useEffect(() => { loadTrendingRunners(false); }, [filters.timeframe, filters.minMultiplier]);

  useEffect(() => {
    if (liveUpdate) {
      liveIntervalRef.current = setInterval(() => loadTrendingRunners(true), LIVE_INTERVAL_MS);
    } else {
      clearInterval(liveIntervalRef.current);
    }
    return () => clearInterval(liveIntervalRef.current);
  }, [liveUpdate, filters]);

  const loadTrendingRunners = async (silent = false) => {
    if (silent) { setIsRefreshing(true); }
    else { setIsLoadingTrending(true); setSelectedRunners([]); }
    try {
      const params = new URLSearchParams({
        timeframe: filters.timeframe,
        min_multiplier: filters.minMultiplier,
        min_liquidity: filters.minLiquidity,
        min_volume: filters.minVolume,
      });
      const response = await fetch(`${apiUrl}/api/wallets/trending/runners?${params}`);
      const data = await response.json();
      if (data.success) {
        setTrendingRunners(data.runners || []);
        setLastUpdated(new Date());
      }
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

  const selectAll = () => setSelectedRunners([...trendingRunners]);
  const deselectAll = () => setSelectedRunners([]);

  const handleBatchAnalyze = async () => {
    if (selectedRunners.length === 0) { alert('Please select at least one token'); return; }
    setIsBatchAnalyzing(true);
    try {
      const response = await fetch(`${apiUrl}/api/wallets/trending/analyze-batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          runners: selectedRunners.map(token => ({ address: token.address, chain: token.chain, symbol: token.ticker || token.symbol })),
        })
      });
      const data = await response.json();
      if (data.success) { alert(`✅ Found ${data.wallets_discovered || 0} smart money wallets!`); onClose(); }
    } catch (error) { console.error('Batch analysis error:', error); alert('Analysis failed'); }
    setIsBatchAnalyzing(false);
  };

  const handleSingleAnalysis = async (token) => {
    try {
      const response = await fetch(`${apiUrl}/api/wallets/trending/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, runner: { address: token.address, chain: token.chain, symbol: token.ticker || token.symbol } })
      });
      const data = await response.json();
      if (data.success) { alert(`✅ Analysis complete for ${token.ticker || token.symbol}`); onClose(); }
    } catch (error) { console.error('Single analysis error:', error); }
  };

  const formatTime = (date) => date ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : null;

  return (
    <div className="space-y-4">

      {/* Header: last updated + refresh + live toggle */}
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-gray-500 min-h-[16px]">
          {isRefreshing && <span className="text-orange-400 flex items-center gap-1"><RefreshCw size={11} className="animate-spin" /> Refreshing…</span>}
          {!isRefreshing && lastUpdated && <span>Updated {formatTime(lastUpdated)}</span>}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => loadTrendingRunners(false)}
            disabled={isLoadingTrending || isRefreshing}
            title="Refresh now"
            className="p-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg transition disabled:opacity-40"
          >
            <RefreshCw size={15} className={isRefreshing || isLoadingTrending ? 'animate-spin text-orange-400' : 'text-gray-400'} />
          </button>
          <button
            onClick={() => setLiveUpdate(v => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
              liveUpdate ? 'bg-green-500/20 border-green-500/50 text-green-400' : 'bg-white/5 border-white/10 text-gray-400 hover:bg-white/10'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${liveUpdate ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
            {liveUpdate ? 'Live' : 'Live Off'}
          </button>
        </div>
      </div>

      {/* Timeframe */}
      <div className="bg-gradient-to-br from-orange-900/20 to-orange-800/10 border border-orange-500/30 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <TrendingUp className="text-orange-400" size={16} /> Select Timeframe
        </h3>
        <div className="grid grid-cols-3 gap-2">
          {[{ value: '7d', label: '7 Days', emoji: '📅' }, { value: '14d', label: '14 Days', emoji: '📆' }, { value: '30d', label: '30 Days', emoji: '🗓️' }].map((option) => (
            <button key={option.value} onClick={() => setFilters(prev => ({ ...prev, timeframe: option.value }))}
              className={`px-4 py-3 rounded-lg font-semibold text-sm transition-all duration-300 ${filters.timeframe === option.value ? 'bg-gradient-to-r from-orange-600 to-orange-500 shadow-lg shadow-orange-500/30 scale-105' : 'bg-white/5 hover:bg-white/10 border border-white/10'}`}>
              <div className="text-lg mb-1">{option.emoji}</div><div>{option.label}</div>
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
          {[{ value: 5, label: '5x', color: 'yellow' }, { value: 10, label: '10x', color: 'green' }, { value: 20, label: '20x', color: 'blue' }, { value: 50, label: '50x', color: 'purple' }].map((option) => (
            <button key={option.value} onClick={() => setFilters(prev => ({ ...prev, minMultiplier: option.value }))}
              className={`px-3 py-2 rounded-lg font-bold text-sm transition-all duration-300 ${filters.minMultiplier === option.value ? `bg-gradient-to-r from-${option.color}-600 to-${option.color}-500 shadow-lg scale-105` : 'bg-white/5 hover:bg-white/10 border border-white/10'}`}>
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {/* Advanced filters */}
      <button onClick={() => setFilters(prev => ({ ...prev, showAdvanced: !prev.showAdvanced }))}
        className="w-full px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm font-semibold transition flex items-center justify-between">
        <span className="flex items-center gap-2"><Filter size={14} /> Advanced Filters</span>
        <ChevronDown size={16} className={`transition-transform ${filters.showAdvanced ? 'rotate-180' : ''}`} />
      </button>

      {filters.showAdvanced && (
        <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Min Liquidity ($) <span className="text-gray-600">default 10k</span></label>
              <input type="number" min="0" value={filters.minLiquidity}
                onChange={(e) => handleNumberInput('minLiquidity', e.target.value)}
                onBlur={(e) => { const v = parseInt(e.target.value, 10); setFilters(prev => ({ ...prev, minLiquidity: isNaN(v) || v < 0 ? 0 : v })); }}
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500" />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Min Volume ($) <span className="text-gray-600">default 50k</span></label>
              <input type="number" min="0" value={filters.minVolume}
                onChange={(e) => handleNumberInput('minVolume', e.target.value)}
                onBlur={(e) => { const v = parseInt(e.target.value, 10); setFilters(prev => ({ ...prev, minVolume: isNaN(v) || v < 0 ? 0 : v })); }}
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500" />
            </div>
          </div>
          <button onClick={() => loadTrendingRunners(false)} className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-semibold transition">Apply Filters</button>
          <button onClick={() => setFilters(prev => ({ ...prev, minLiquidity: 10000, minVolume: 50000 }))}
            className="w-full px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs text-gray-400 transition">Reset to defaults</button>
        </div>
      )}

      {/* Batch selection */}
      {trendingRunners.length > 0 && (
        <div className="bg-gradient-to-r from-blue-900/20 to-blue-800/10 border border-blue-500/30 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="text-sm font-semibold text-blue-400">{selectedRunners.length} / {trendingRunners.length} Selected</h3>
              <p className="text-xs text-gray-400">Select multiple tokens to find common wallets</p>
            </div>
            <div className="flex gap-2">
              <button onClick={selectAll} className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-semibold transition">Select All</button>
              <button onClick={deselectAll} className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-semibold transition">Clear</button>
            </div>
          </div>
          <button onClick={handleBatchAnalyze} disabled={isBatchAnalyzing || selectedRunners.length === 0}
            className="w-full px-4 py-3 bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 disabled:from-blue-600/30 disabled:to-blue-500/30 rounded-lg font-semibold transition flex items-center justify-center gap-2 shadow-lg shadow-blue-500/30">
            {isBatchAnalyzing ? (<><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Analyzing {selectedRunners.length} Tokens…</>) : (<><Sparkles size={18} /> Batch Analyze Selected ({selectedRunners.length})</>)}
          </button>
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
            <button onClick={() => loadTrendingRunners(false)}
              className="mt-4 px-4 py-2 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/30 rounded-lg text-sm text-orange-400 font-semibold transition flex items-center gap-2 mx-auto">
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        ) : (
          trendingRunners.map((token, idx) => {
            const isSelected = selectedRunners.some(t => t.address === token.address && t.chain === token.chain);
            return (
              <div key={`${token.chain}-${token.address}-${idx}`}
                className={`bg-white/5 hover:bg-white/10 border rounded-lg p-4 transition ${isSelected ? 'border-orange-500/50 bg-orange-500/10' : 'border-white/10'}`}>
                <div className="flex items-start gap-3">
                  <button onClick={() => toggleRunnerSelection(token)} className="mt-1">
                    {isSelected ? <CheckSquare size={20} className="text-orange-400" /> : <Square size={20} className="text-gray-600 hover:text-gray-400" />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2 flex-wrap">
                      <span className="font-semibold">{token.ticker || token.symbol}</span>
                      <span className="text-xs px-2 py-0.5 bg-white/10 rounded">{token.chain?.toUpperCase()}</span>
                      <span className="text-xs px-2 py-0.5 bg-orange-500/20 text-orange-400 rounded font-bold">{token.multiplier}x</span>
                      <span className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded font-bold flex items-center gap-1"><Shield size={10} /> Verified</span>
                    </div>
                    <div className="text-sm text-gray-400 mb-2 truncate">{token.name}</div>
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <div><span className="text-gray-500">Liquidity:</span><span className="ml-1 text-white font-semibold">{formatNumber(token.liquidity)}</span></div>
                      <div><span className="text-gray-500">Volume:</span><span className="ml-1 text-white font-semibold">{formatNumber(token.volume_24h || token.volume)}</span></div>
                      <div><span className="text-gray-500">Price:</span><span className="ml-1 text-white font-semibold">{formatPrice(token.current_price || token.price)}</span></div>
                    </div>
                  </div>
                  <button onClick={() => handleSingleAnalysis(token)}
                    className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold transition whitespace-nowrap flex items-center gap-1 flex-shrink-0">
                    <BarChart3 size={14} /> Analyze
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3">
        <p className="text-xs text-blue-300">💡 <strong>Batch Analysis Tip:</strong> Select multiple tokens to find wallets that hit several runners. This reveals the most competent smart money.</p>
      </div>
    </div>
  );
}