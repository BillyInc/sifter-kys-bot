import React, { useState, useEffect } from 'react';
import { TrendingUp, Filter, Sparkles, ChevronDown, CheckSquare, Square } from 'lucide-react';

export default function TrendingPanel({
  userId,
  apiUrl,
  onClose,
  // Add any other props you need from SifterKYS
  formatNumber,
  formatPrice
}) {
  const [trendingRunners, setTrendingRunners] = useState([]);
  const [isLoadingTrending, setIsLoadingTrending] = useState(false);
  const [selectedRunners, setSelectedRunners] = useState([]);
  const [isBatchAnalyzing, setIsBatchAnalyzing] = useState(false);
  const [batchResults, setBatchResults] = useState(null);

  // Filter states
  const [filters, setFilters] = useState({
    timeframe: '24h',
    minMultiplier: 5,
    minLiquidity: 5000,
    showAdvanced: false,
    minVolume: 0,
    minTxns: 0,
    chains: ['solana']
  });

  useEffect(() => {
    loadTrendingRunners();
  }, [filters.timeframe, filters.minMultiplier]);

  const loadTrendingRunners = async () => {
    setIsLoadingTrending(true);
    try {
      const response = await fetch(
        `${apiUrl}/api/tokens/trending?` + 
        `timeframe=${filters.timeframe}&` +
        `min_multiplier=${filters.minMultiplier}&` +
        `min_liquidity=${filters.minLiquidity}`
      );
      const data = await response.json();
      
      if (data.success) {
        setTrendingRunners(data.tokens || []);
      }
    } catch (error) {
      console.error('Error loading trending runners:', error);
    }
    setIsLoadingTrending(false);
  };

  const toggleRunnerSelection = (token) => {
    const isSelected = selectedRunners.some(
      t => t.address === token.address && t.chain === token.chain
    );
    
    if (isSelected) {
      setSelectedRunners(selectedRunners.filter(
        t => !(t.address === token.address && t.chain === token.chain)
      ));
    } else {
      setSelectedRunners([...selectedRunners, token]);
    }
  };

  const selectAll = () => {
    setSelectedRunners([...trendingRunners]);
  };

  const deselectAll = () => {
    setSelectedRunners([]);
  };

  const handleBatchAnalyze = async () => {
    if (selectedRunners.length === 0) {
      alert('Please select at least one token');
      return;
    }

    setIsBatchAnalyzing(true);
    try {
      const response = await fetch(`${apiUrl}/api/analysis/batch-trending`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          tokens: selectedRunners.map(token => ({
            address: token.address,
            chain: token.chain,
            ticker: token.ticker
          })),
          days_back: 7,
          candle_size: '5m'
        })
      });

      const data = await response.json();
      
      if (data.success) {
        setBatchResults(data.results);
        alert(`✅ Found ${data.results.qualified_wallets || 0} qualified wallets!`);
        onClose(); // Close panel and show results on dashboard
      }
    } catch (error) {
      console.error('Batch analysis error:', error);
      alert('Analysis failed');
    }
    setIsBatchAnalyzing(false);
  };

  const handleSingleAnalysis = async (token) => {
    try {
      const response = await fetch(`${apiUrl}/api/analysis/single`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          token_address: token.address,
          chain: token.chain,
          days_back: 7,
          candle_size: '5m'
        })
      });

      const data = await response.json();
      
      if (data.success) {
        alert(`✅ Analysis complete for ${token.ticker}`);
        onClose(); // Close and show results
      }
    } catch (error) {
      console.error('Single analysis error:', error);
    }
  };

  return (
    <div className="space-y-4">
      {/* Filter Bar */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Filter size={16} className="text-orange-400" />
            Filters
          </h3>
          <button
            onClick={() => setFilters({...filters, showAdvanced: !filters.showAdvanced})}
            className="text-xs text-purple-400 hover:text-purple-300"
          >
            {filters.showAdvanced ? 'Hide' : 'Show'} Advanced
          </button>
        </div>

        {/* Basic Filters */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Timeframe</label>
            <select
              value={filters.timeframe}
              onChange={(e) => setFilters({...filters, timeframe: e.target.value})}
              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
            >
              <option value="1h">Last 1 Hour</option>
              <option value="4h">Last 4 Hours</option>
              <option value="12h">Last 12 Hours</option>
              <option value="24h">Last 24 Hours</option>
              <option value="7d">Last 7 Days</option>
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">Min Multiplier</label>
            <select
              value={filters.minMultiplier}
              onChange={(e) => setFilters({...filters, minMultiplier: parseFloat(e.target.value)})}
              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
            >
              <option value="2">2x</option>
              <option value="5">5x</option>
              <option value="10">10x</option>
              <option value="20">20x</option>
              <option value="50">50x</option>
            </select>
          </div>
        </div>

        {/* Advanced Filters */}
        {filters.showAdvanced && (
          <div className="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-white/10">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Min Liquidity ($)</label>
              <input
                type="number"
                value={filters.minLiquidity}
                onChange={(e) => setFilters({...filters, minLiquidity: parseInt(e.target.value) || 0})}
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
              />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Min Volume ($)</label>
              <input
                type="number"
                value={filters.minVolume}
                onChange={(e) => setFilters({...filters, minVolume: parseInt(e.target.value) || 0})}
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
              />
            </div>
          </div>
        )}

        <button
          onClick={loadTrendingRunners}
          disabled={isLoadingTrending}
          className="w-full mt-3 px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/30 rounded-lg text-sm font-semibold transition"
        >
          {isLoadingTrending ? 'Loading...' : 'Apply Filters'}
        </button>
      </div>

      {/* Batch Selection Controls */}
      {trendingRunners.length > 0 && (
        <div className="bg-gradient-to-r from-orange-900/20 to-orange-800/10 border border-orange-500/30 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="text-sm font-semibold text-orange-400">
                {selectedRunners.length} / {trendingRunners.length} Selected
              </h3>
              <p className="text-xs text-gray-400">Select multiple tokens to find common wallets</p>
            </div>
            
            <div className="flex gap-2">
              <button
                onClick={selectAll}
                className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-semibold transition"
              >
                Select All
              </button>
              <button
                onClick={deselectAll}
                className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-semibold transition"
              >
                Clear
              </button>
            </div>
          </div>

          <button
            onClick={handleBatchAnalyze}
            disabled={isBatchAnalyzing || selectedRunners.length === 0}
            className="w-full px-4 py-3 bg-gradient-to-r from-orange-600 to-orange-500 hover:from-orange-700 hover:to-orange-600 disabled:from-orange-600/30 disabled:to-orange-500/30 rounded-lg font-semibold transition flex items-center justify-center gap-2"
          >
            {isBatchAnalyzing ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Analyzing {selectedRunners.length} Tokens...
              </>
            ) : (
              <>
                <Sparkles size={18} />
                Batch Analyze Selected
              </>
            )}
          </button>
        </div>
      )}

      {/* Trending Runners List */}
      <div className="space-y-2">
        {isLoadingTrending ? (
          <div className="flex justify-center py-12">
            <div className="w-8 h-8 border-2 border-white/30 border-t-purple-500 rounded-full animate-spin" />
          </div>
        ) : trendingRunners.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <TrendingUp size={48} className="mx-auto mb-3 opacity-20" />
            <p className="text-sm">No trending runners found</p>
            <p className="text-xs mt-1">Try adjusting your filters</p>
          </div>
        ) : (
          trendingRunners.map((token, idx) => {
            const isSelected = selectedRunners.some(
              t => t.address === token.address && t.chain === token.chain
            );

            return (
              <div
                key={`${token.chain}-${token.address}-${idx}`}
                className={`bg-white/5 hover:bg-white/10 border rounded-lg p-4 transition ${
                  isSelected ? 'border-orange-500/50 bg-orange-500/10' : 'border-white/10'
                }`}
              >
                <div className="flex items-start gap-3">
                  {/* Selection Checkbox */}
                  <button
                    onClick={() => toggleRunnerSelection(token)}
                    className="mt-1"
                  >
                    {isSelected ? (
                      <CheckSquare size={20} className="text-orange-400" />
                    ) : (
                      <Square size={20} className="text-gray-600 hover:text-gray-400" />
                    )}
                  </button>

                  {/* Token Info */}
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="font-semibold">{token.ticker}</span>
                      <span className="text-xs px-2 py-0.5 bg-white/10 rounded">
                        {token.chain?.toUpperCase()}
                      </span>
                      <span className="text-xs px-2 py-0.5 bg-orange-500/20 text-orange-400 rounded font-bold">
                        {token.multiplier}x
                      </span>
                    </div>

                    <div className="text-sm text-gray-400 mb-2">{token.name}</div>

                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <div>
                        <span className="text-gray-500">Liquidity:</span>
                        <span className="ml-1 text-white font-semibold">
                          {formatNumber(token.liquidity)}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-500">Volume:</span>
                        <span className="ml-1 text-white font-semibold">
                          {formatNumber(token.volume)}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-500">Price:</span>
                        <span className="ml-1 text-white font-semibold">
                          {formatPrice(token.price)}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Single Analysis Button */}
                  <button
                    onClick={() => handleSingleAnalysis(token)}
                    className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold transition whitespace-nowrap"
                  >
                    Analyze
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Info Banner */}
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3">
        <p className="text-xs text-blue-300">
          💡 <strong>Batch Analysis Tip:</strong> Select multiple tokens to find wallets that hit several runners. This reveals the most competent smart money.
        </p>
      </div>
    </div>
  );
}