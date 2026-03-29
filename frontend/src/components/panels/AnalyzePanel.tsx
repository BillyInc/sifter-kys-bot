// components/panels/AnalyzePanel.tsx
import React from 'react';
import { Search, BarChart3, X, RefreshCw, Minimize2, Activity } from 'lucide-react';
import AnalysisSettings from '../../Analysis_Setting';

interface AnalyzePanelProps {
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  searchResults: any[];
  isSearching: boolean;
  showDropdown: boolean;
  searchRef: React.RefObject<HTMLDivElement | null>;
  selectedTokens: any[];
  toggleTokenSelection: (token: any) => void;
  removeToken: (address: string, chain: string) => void;
  analysisType: string;
  setAnalysisType: (type: string) => void;
  useGlobalSettings: boolean;
  setUseGlobalSettings: (v: boolean) => void;
  tokenSettings: Record<string, any>;
  updateTokenSetting: (...args: any[]) => void;
  daysBack: number;
  setDaysBack: (v: number) => void;
  candleSize: string;
  setCandleSize: (v: string) => void;
  tMinusWindow: number;
  setTMinusWindow: (v: number) => void;
  tPlusWindow: number;
  setTPlusWindow: (v: number) => void;
  handleAnalysisStreaming: () => Promise<void>;
  isAnalyzing: boolean;
  onClose: () => void;
  formatNumber: (v: any) => string;
  setSelectedTokens: (tokens: any[]) => void;
  formatPrice: (v: any) => string;
  onResultsReady: (...args: any[]) => any;
  onRefreshSearch?: () => void;
  activeAnalysis: any;
  onMinimize: () => void;
}

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
  activeAnalysis,
  onMinimize,
}: AnalyzePanelProps) {
  const handleRunAnalysis = async () => {
    // Fire and forget — handleAnalysisStreaming queues the job and registers
    // it with the global poll loop, then returns immediately.
    await handleAnalysisStreaming();
    // Close the panel so the user can keep working.
    // The active analyses box in the navbar will show progress.
    onClose();
  };

  const pct = activeAnalysis
    ? Math.round(((activeAnalysis.progress?.current || 0) / (activeAnalysis.progress?.total || 1)) * 100)
    : 0;

  return (
    <div className="space-y-4">

      {/* ── In-flight banner — shown when a job is running ── */}
      {isAnalyzing && activeAnalysis && (
        <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="flex items-center gap-2">
              <Activity size={16} className="text-green-400 animate-pulse shrink-0" />
              <span className="text-sm font-semibold text-green-400">Analysis Running</span>
            </div>
            <button
              onClick={onMinimize}
              title="Minimize to background"
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition shrink-0"
              style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}
            >
              <Minimize2 size={12} /> Minimize
            </button>
          </div>

          {/* Token chips */}
          {activeAnalysis.tokens?.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-3">
              {activeAnalysis.tokens.slice(0, 5).map((t, i) => (
                <span key={t} className="text-xs px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded-full">{t}</span>
              ))}
              {activeAnalysis.tokens.length > 5 && (
                <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}>+{activeAnalysis.tokens.length - 5}</span>
              )}
            </div>
          )}

          {/* Progress bar */}
          <div className="rounded-full h-2 overflow-hidden mb-2" style={{ backgroundColor: 'var(--bg-secondary)' }}>
            <div
              className="bg-gradient-to-r from-green-500 to-emerald-400 h-2 rounded-full transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-gray-400">
            <span>{activeAnalysis.progress?.phase || 'Processing…'}</span>
            <span>{activeAnalysis.progress?.current}/{activeAnalysis.progress?.total} · {pct}%</span>
          </div>

          {activeAnalysis.in_queue && (
            <div className="mt-2 text-xs text-yellow-400 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse" />
              Queue position #{activeAnalysis.queue_position || '?'}
              {activeAnalysis.estimated_wait && ` · ~${activeAnalysis.estimated_wait}m wait`}
            </div>
          )}

          <p className="mt-3 text-xs text-gray-600 text-center">
            You can close this panel — analysis runs in the background
          </p>
        </div>
      )}

      {/* ── Token Search ── */}
      <div className="rounded-xl p-4" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold">Token Search</h3>
          <select
            value={analysisType}
            onChange={(e) => setAnalysisType(e.target.value)}
            className="rounded-lg px-4 py-2.5 text-sm"
            style={{ backgroundColor: 'var(--input-bg)', color: 'var(--text-primary)', borderColor: 'var(--border-color-strong)', border: '1px solid var(--border-color-strong)' }}
          >
            <option value="general">📊 General Analysis</option>
            <option value="pump_window">🎯 Pump Window</option>
          </select>
        </div>

        <div className="relative flex items-center gap-2" ref={searchRef}>
          <div className="relative flex-1">
            <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400 pointer-events-none" size={18} />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && onRefreshSearch) onRefreshSearch(); }}
              placeholder="Search by token name, ticker, or contract address..."
              className="w-full rounded-lg pl-12 pr-4 py-3 text-sm focus:outline-none focus:border-purple-500 transition"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--text-primary)', border: '1px solid var(--border-color-strong)' }}
              autoComplete="off"
            />
            {isSearching && (
              <div className="absolute right-4 top-1/2 transform -translate-y-1/2">
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              </div>
            )}
          </div>

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
            <div className="absolute top-full left-0 right-0 mt-2 rounded-xl shadow-2xl max-h-96 overflow-y-auto z-50" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color-strong)', color: 'var(--text-primary)' }}>
              {searchResults.map((token, idx) => {
                const isSelected = selectedTokens.some(
                  t => t.address?.toLowerCase() === (token.address || token.mint)?.toLowerCase() && t.chain === token.chain
                );
                const address   = token.address || token.mint || token.poolAddress;
                const ticker    = token.ticker || token.symbol;
                const liquidity = token.liquidity || token.liquidityUsd;
                return (
                  <div
                    key={`${token.chain}-${address}-${idx}`}
                    onClick={() => toggleTokenSelection({ ...token, address, ticker })}
                    className={`p-3 cursor-pointer transition ${isSelected ? 'bg-purple-500/10' : ''}`}
                    style={{ borderBottom: '1px solid var(--border-color)' }}
                    onMouseEnter={e => { if (!isSelected) e.currentTarget.style.backgroundColor = 'var(--bg-secondary)'; }}
                    onMouseLeave={e => { if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent'; }}
                  >
                    <div className="flex items-start gap-2">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-semibold text-sm">{ticker}</span>
                          <span className="text-xs px-2 py-0.5 rounded" style={{ backgroundColor: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}>{(token.chain || 'SOLANA').toUpperCase()}</span>
                          {token.hasSocials && <span className="text-xs px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded">✓ Social</span>}
                        </div>
                        <div className="text-xs text-gray-400">{token.name}</div>
                        <div className="text-xs text-gray-500 mt-1 font-mono">{address?.slice(0, 12)}…</div>
                        {liquidity && <div className="text-xs text-gray-500">Liq: {formatNumber(liquidity)}</div>}
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
            <div className="absolute top-full left-0 right-0 mt-2 rounded-xl shadow-2xl z-50 p-4 text-center text-sm text-gray-500" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color-strong)', color: 'var(--text-secondary)' }}>
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
            <button onClick={() => setSelectedTokens([])} className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Clear All
            </button>
          </div>

          <div className="space-y-2 mb-4">
            {selectedTokens.map((token) => (
              <div key={`${token.chain}-${token.address}`} className="rounded-lg p-3" style={{ backgroundColor: 'var(--bg-secondary)' }}>
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="font-semibold text-sm">{token.ticker || token.symbol}</div>
                    <div className="text-xs text-gray-400">{(token.chain || 'SOLANA').toUpperCase()}</div>
                  </div>
                  <button onClick={() => removeToken(token.address, token.chain)} className="p-1 hover:bg-white/10 rounded transition">
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

          {/* ── Run / Minimize button row ── */}
          <div className="mt-4 flex gap-2">
            <button
              onClick={handleRunAnalysis}
              disabled={isAnalyzing}
              className="flex-1 px-4 py-3 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 disabled:from-purple-600/30 disabled:to-purple-500/30 rounded-lg font-semibold transition-all duration-300 flex items-center justify-center gap-2 shadow-lg shadow-purple-500/30"
            >
              {isAnalyzing ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Running…
                </>
              ) : (
                <>
                  <BarChart3 size={18} />
                  Run Analysis
                </>
              )}
            </button>

            {/* Minimize button — only shown while a job is in flight */}
            {isAnalyzing && (
              <button
                onClick={onMinimize}
                title="Minimize to background"
                className="px-3 py-3 rounded-lg transition flex items-center gap-1.5 text-sm"
                style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}
              >
                <Minimize2 size={16} />
              </button>
            )}
          </div>

          {isAnalyzing && (
            <p className="mt-2 text-xs text-gray-600 text-center">
              Analysis runs in the background — safe to close this panel
            </p>
          )}
        </div>
      )}
    </div>
  );
}