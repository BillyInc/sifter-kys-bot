import React from 'react';
import { Search, BarChart3 } from 'lucide-react';
import AnalysisSettings from '../../Analysis_Setting';

export default function AnalyzePanel({
  // Props passed from SifterKYS
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
  onClose, // NEW: to close panel after starting analysis
  formatNumber,
  setSelectedTokens,   // ← ADD THIS LINE
  formatPrice
}) {
  return (
    <div className="space-y-4">
      {/* Token Search */}
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
        
        <div className="relative flex-1" ref={searchRef}>
          <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by token name, ticker, or contract address..."
            className="w-full bg-black/50 border border-white/10 rounded-lg pl-12 pr-4 py-3 text-sm focus:outline-none focus:border-purple-500 transition"
          />
          {isSearching && (
            <div className="absolute right-4 top-1/2 transform -translate-y-1/2">
              <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            </div>
          )}
          
          {/* Search Dropdown - YOUR EXISTING CODE */}
          {showDropdown && searchResults.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-gray-900 border border-white/20 rounded-xl shadow-2xl max-h-96 overflow-y-auto z-50">
              {searchResults.map((token, idx) => {
                const isSelected = selectedTokens.some(
                  t => t.address.toLowerCase() === token.address.toLowerCase() && t.chain === token.chain
                );
                
                return (
                  <div
                    key={`${token.chain}-${token.address}-${idx}`}
                    onClick={() => toggleTokenSelection(token)}
                    className={`p-3 border-b border-white/5 hover:bg-white/5 cursor-pointer transition ${
                      isSelected ? 'bg-purple-500/10' : ''
                    }`}
                  >
                    {/* YOUR EXISTING TOKEN DISPLAY CODE */}
                    <div className="flex items-start gap-2">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-semibold text-sm">{token.ticker}</span>
                          <span className="text-xs px-2 py-0.5 bg-white/10 rounded">{token.chain.toUpperCase()}</span>
                        </div>
                        <div className="text-xs text-gray-400">{token.name}</div>
                        <div className="text-xs text-gray-500 mt-1">Liq: {formatNumber(token.liquidity)}</div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Selected Tokens - YOUR EXISTING CODE */}
      {selectedTokens.length > 0 && (
        <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-4">
          <div className="flex justify-between items-center mb-3">
            <h3 className="text-base font-semibold">
              Selected Tokens ({selectedTokens.length})
            </h3>
            <button
              onClick={() => setSelectedTokens([])}
              className="text-xs text-gray-400 hover:text-white"
            >
              Clear All
            </button>
          </div>

          {/* Token List */}
          <div className="space-y-2 mb-4">
            {selectedTokens.map((token) => (
              <div key={`${token.chain}-${token.address}`} className="bg-black/30 rounded-lg p-3">
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="font-semibold text-sm">{token.ticker}</div>
                    <div className="text-xs text-gray-400">{token.chain.toUpperCase()}</div>
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

          {/* Analysis Settings - YOUR EXISTING COMPONENT */}
          <AnalysisSettings
            analysisType={analysisType}
            selectedTokens={selectedTokens}
            useGlobalSettings={useGlobalSettings}
            setUseGlobalSettings={setUseGlobalSettings}
            tokenSettings={tokenSettings}
            updateTokenSetting={updateTokenSetting}
            globalSettings={{ daysBack, candleSize, tMinusWindow, tPlusWindow }}
            onGlobalSettingsChange={(settings) => {
              if (settings.daysBack !== undefined) setDaysBack(settings.daysBack);
              if (settings.candleSize !== undefined) setCandleSize(settings.candleSize);
              if (settings.tMinusWindow !== undefined) setTMinusWindow(settings.tMinusWindow);
              if (settings.tPlusWindow !== undefined) setTPlusWindow(settings.tPlusWindow);
            }}
          />

          {/* Run Analysis Button */}
          <button
            onClick={() => {
              handleAnalysisStreaming();
              onClose(); // Close panel after starting
            }}
            disabled={isAnalyzing}
            className="w-full mt-4 px-4 py-3 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 disabled:from-purple-600/30 disabled:to-purple-500/30 rounded-lg font-semibold transition-all duration-300 flex items-center justify-center gap-2 shadow-lg shadow-purple-500/30"
          >
            {isAnalyzing ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <BarChart3 size={18} />
                Run Analysis (Streaming)
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}