// components/panels/AnalyzePanel.jsx
import React from 'react';
import { Search, BarChart3, X, RefreshCw } from 'lucide-react';
import AnalysisSettings from '../../Analysis_Setting';

/**
 * Props:
 *  ...existing props...
 *  onRefreshSearch  — () => void  — triggers a fresh search with the current query
 *  streamingMessage — string      — forwarded from SifterKYS so AnalyzePanel can show
 *                                   progress inline (optional; parent also shows a full overlay)
 *  onAnalysisStart  — (data) => void — called when analysis starts with jobId and total
 *  onAnalysisProgress — (progress) => void — called on progress updates
 *  onAnalysisComplete — (results) => void — called when analysis completes
 *  activeAnalysis   — object      — current active analysis data
 */
export default function AnalyzePanel({
  searchQuery,
  setSearchQuery,
  searchResults,
  isSearching,
  showDropdown,
  searchRef,
  selectedTokens,
  toggleTokenSelection,
  removeToken,
  analysisType,
  setAnalysisType,
  useGlobalSettings,
  setUseGlobalSettings,
  tokenSettings,
  updateTokenSetting,
  daysBack,
  setDaysBack,
  candleSize,
  setCandleSize,
  tMinusWindow,
  setTMinusWindow,
  tPlusWindow,
  setTPlusWindow,
  handleAnalysisStreaming,
  isAnalyzing,
  onClose,
  formatNumber,
  setSelectedTokens,
  formatPrice,
  onResultsReady,
  onRefreshSearch,
  streamingMessage,
  onAnalysisStart,
  onAnalysisProgress,
  onAnalysisComplete,
  activeAnalysis,
}) {
  // Wrap the original handleAnalysisStreaming to inject tracking
  const handleAnalysisWithTracking = async () => {
    // Call the original function which should return job data
    const result = await handleAnalysisStreaming();
    
    // The actual tracking happens in the parent's polling,
    // but we need to ensure onAnalysisStart is called with jobId
    // This assumes handleAnalysisStreaming returns job data
    if (result?.jobId) {
      onAnalysisStart({
        jobId: result.jobId,
        total: selectedTokens.length,
        analysisType: analysisType
      });
    }
  };

  return (
    <div className="space-y-4">

      {/* ── Token Search ── */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold">Token Search</h3>
          <select
            value={analysisType}
            onChange={(e) => setAnalysisType(e.target.value)}
            className="bg-gradient-to-br from-gray-800 to-gray-900 border border-gray-700 rounded-lg px-4 py-2.5 text-sm"
          >
            <option value="general">📊 General Analysis</option>
            <option value="pump_window">🎯 Pump Window</option>
          </select>
        </div>

        <div className="relative flex items-center gap-2" ref={searchRef}>
          {/* Input wrapper */}
          <div className="relative flex-1">
            <Search
              className="absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400 pointer-events-none"
              size={18}
            />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                // Allow Enter to manually trigger a search refresh
                if (e.key === 'Enter' && onRefreshSearch) onRefreshSearch();
              }}
              placeholder="Search by token name, ticker, or contract address..."
              className="w-full bg-black/50 border border-white/10 rounded-lg pl-12 pr-4 py-3 text-sm focus:outline-none focus:border-purple-500 transition"
              autoComplete="off"
            />
            {isSearching && (
              <div className="absolute right-4 top-1/2 transform -translate-y-1/2">
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              </div>
            )}
          </div>

          {/* ✅ NEW: Search-again button — visible when there is a query */}
          
            <button
              onClick={() => onRefreshSearch && onRefreshSearch()}
              disabled={isSearching}
              title="Search"
              className="flex-shrink-0 p-3 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 rounded-lg transition"
            >
              <RefreshCw size={16} className={isSearching ? 'animate-spin' : ''} />
            </button>
          

          {/* Search Dropdown */}
          {showDropdown && searchResults.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-gray-900 border border-white/20 rounded-xl shadow-2xl max-h-96 overflow-y-auto z-50">
              {searchResults.map((token, idx) => {
                const isSelected = selectedTokens.some(
                  t =>
                    t.address?.toLowerCase() === (token.address || token.mint)?.toLowerCase() &&
                    t.chain === token.chain
                );
                const address   = token.address || token.mint || token.poolAddress;
                const ticker    = token.ticker || token.symbol;
                const liquidity = token.liquidity || token.liquidityUsd;

                return (
                  <div
                    key={`${token.chain}-${address}-${idx}`}
                    onClick={() => toggleTokenSelection({ ...token, address, ticker })}
                    className={`p-3 border-b border-white/5 hover:bg-white/5 cursor-pointer transition ${isSelected ? 'bg-purple-500/10' : ''}`}
                  >
                    <div className="flex items-start gap-2">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-semibold text-sm">{ticker}</span>
                          <span className="text-xs px-2 py-0.5 bg-white/10 rounded">
                            {(token.chain || 'SOLANA').toUpperCase()}
                          </span>
                          {token.hasSocials && (
                            <span className="text-xs px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded">
                              ✓ Social
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-gray-400">{token.name}</div>
                        <div className="text-xs text-gray-500 mt-1 font-mono">{address?.slice(0, 12)}…</div>
                        {liquidity && (
                          <div className="text-xs text-gray-500">Liq: {formatNumber(liquidity)}</div>
                        )}
                      </div>
                      {isSelected && <div className="text-purple-400 text-xs mt-1">✓</div>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* No results */}
          {showDropdown && !isSearching && searchResults.length === 0 && searchQuery.length >= 2 && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-gray-900 border border-white/20 rounded-xl shadow-2xl z-50 p-4 text-center text-sm text-gray-500">
              <p>No tokens found for "{searchQuery}"</p>
              {onRefreshSearch && (
                <button
                  onClick={onRefreshSearch}
                  className="mt-2 px-3 py-1.5 bg-purple-600/30 hover:bg-purple-600/50 border border-purple-500/30 rounded-lg text-xs text-purple-400 font-semibold transition flex items-center gap-1 mx-auto"
                >
                  <RefreshCw size={12} /> Try again
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Selected Tokens ── */}
      {selectedTokens.length > 0 && (
        <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-4">
          <div className="flex justify-between items-center mb-3">
            <h3 className="text-base font-semibold">Selected Tokens ({selectedTokens.length})</h3>
            <button
              onClick={() => setSelectedTokens([])}
              className="text-xs text-gray-400 hover:text-white"
            >
              Clear All
            </button>
          </div>

          <div className="space-y-2 mb-4">
            {selectedTokens.map((token) => (
              <div key={`${token.chain}-${token.address}`} className="bg-black/30 rounded-lg p-3">
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="font-semibold text-sm">{token.ticker || token.symbol}</div>
                    <div className="text-xs text-gray-400">{(token.chain || 'SOLANA').toUpperCase()}</div>
                  </div>
                  <button
                    onClick={() => removeToken(token.address, token.chain)}
                    className="p-1 hover:bg-white/10 rounded transition"
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>

          <AnalysisSettings
            analysisType={analysisType}
            selectedTokens={selectedTokens}
            useGlobalSettings={useGlobalSettings}
            setUseGlobalSettings={setUseGlobalSettings}
            tokenSettings={tokenSettings}
            updateTokenSetting={updateTokenSetting}
            globalSettings={{ daysBack, candleSize, tMinusWindow, tPlusWindow }}
            onGlobalSettingsChange={(settings) => {
              if (settings.daysBack     !== undefined) setDaysBack(settings.daysBack);
              if (settings.candleSize   !== undefined) setCandleSize(settings.candleSize);
              if (settings.tMinusWindow !== undefined) setTMinusWindow(settings.tMinusWindow);
              if (settings.tPlusWindow  !== undefined) setTPlusWindow(settings.tPlusWindow);
            }}
          />

          {/* ── Run Analysis button ── */}
          <button
            onClick={() => { 
              handleAnalysisWithTracking(); 
              onClose(); 
            }}
            disabled={isAnalyzing}
            className="w-full mt-4 px-4 py-3 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 disabled:from-purple-600/30 disabled:to-purple-500/30 rounded-lg font-semibold transition-all duration-300 flex items-center justify-center gap-2 shadow-lg shadow-purple-500/30"
          >
            {isAnalyzing ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Analyzing…
              </>
            ) : (
              <>
                <BarChart3 size={18} />
                Run Analysis
              </>
            )}
          </button>

          {/* Show active analysis progress if any */}
          {activeAnalysis && (
            <div className="mt-3 space-y-2">
              <div className="bg-white/10 rounded-full h-1.5 overflow-hidden">
                <div 
                  className="bg-green-500 h-1.5 rounded-full transition-all"
                  style={{ 
                    width: `${(activeAnalysis.progress?.current / activeAnalysis.progress?.total) * 100}%` 
                  }}
                />
              </div>
              <p className="text-xs text-gray-400 text-center">
                {activeAnalysis.progress?.phase || 'Processing...'} ({activeAnalysis.progress?.current}/{activeAnalysis.progress?.total})
              </p>
            </div>
          )}

          {/* ✅ NEW: Inline progress forwarded from SifterKYS polling */}
          {isAnalyzing && streamingMessage && (
            <div className="mt-3 text-xs text-gray-400 text-center animate-pulse">
              {streamingMessage}
            </div>
          )}
        </div>
      )}
    </div>
  );
}