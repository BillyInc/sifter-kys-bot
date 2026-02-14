import React, { useState } from 'react';
import { Zap, Search, Sparkles, CheckCircle, AlertCircle } from 'lucide-react';

export default function DiscoveryPanel({
  userId,
  apiUrl,
  onClose,
  onAddToWatchlist, // Function to add discovered wallets to watchlist
  formatNumber
}) {
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discoveryResults, setDiscoveryResults] = useState(null);
  const [discoveryConfig, setDiscoveryConfig] = useState({
    minRunners: 3,
    minScore: 70,
    timeframe: '30d',
    maxWallets: 50,
    chains: ['solana']
  });

  const handleAutoDiscovery = async () => {
    setIsDiscovering(true);
    setDiscoveryResults(null);

    try {
      const response = await fetch(`${apiUrl}/api/wallets/auto-discover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          min_runners_hit: discoveryConfig.minRunners,
          min_professional_score: discoveryConfig.minScore,
          timeframe: discoveryConfig.timeframe,
          max_results: discoveryConfig.maxWallets,
          chains: discoveryConfig.chains
        })
      });

      const data = await response.json();
      
      if (data.success) {
        setDiscoveryResults(data.wallets || []);
      } else {
        alert(`Discovery failed: ${data.error}`);
      }
    } catch (error) {
      console.error('Auto discovery error:', error);
      alert('Discovery failed due to network error');
    }
    
    setIsDiscovering(false);
  };

  const handleAddWallet = async (wallet) => {
    try {
      await onAddToWatchlist({
        wallet_address: wallet.wallet_address,
        tags: ['auto-discovery', `${wallet.runners_hit}-runners`],
        notes: `Auto-discovered: ${wallet.runners_hit} runners hit, ${wallet.professional_score} score`
      });
      
      alert(`✅ Added ${wallet.wallet_address.slice(0, 8)}... to watchlist`);
    } catch (error) {
      console.error('Add to watchlist error:', error);
      alert('Failed to add wallet to watchlist');
    }
  };

  const handleAddAll = async () => {
    if (!discoveryResults || discoveryResults.length === 0) return;
    
    const confirm = window.confirm(
      `Add all ${discoveryResults.length} wallets to your watchlist?`
    );
    
    if (!confirm) return;

    for (const wallet of discoveryResults) {
      await handleAddWallet(wallet);
    }
    
    alert(`✅ Added ${discoveryResults.length} wallets to your watchlist!`);
  };

  return (
    <div className="space-y-4">
      {/* Discovery Configuration */}
      <div className="bg-gradient-to-br from-yellow-900/20 to-yellow-800/10 border border-yellow-500/30 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Zap className="text-yellow-400" size={20} />
          <h3 className="text-base font-semibold">Auto Discovery Settings</h3>
        </div>

        <p className="text-xs text-gray-400 mb-4">
          Automatically scan recent trending tokens to find wallets that consistently hit multiple runners
        </p>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Min Runners Hit</label>
              <select
                value={discoveryConfig.minRunners}
                onChange={(e) => setDiscoveryConfig({...discoveryConfig, minRunners: parseInt(e.target.value)})}
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
              >
                <option value="2">2+ Runners</option>
                <option value="3">3+ Runners</option>
                <option value="5">5+ Runners</option>
                <option value="10">10+ Runners</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Min Professional Score</label>
              <select
                value={discoveryConfig.minScore}
                onChange={(e) => setDiscoveryConfig({...discoveryConfig, minScore: parseInt(e.target.value)})}
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
              >
                <option value="60">60+ (C-Tier)</option>
                <option value="70">70+ (B-Tier)</option>
                <option value="80">80+ (A-Tier)</option>
                <option value="90">90+ (S-Tier)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Timeframe</label>
              <select
                value={discoveryConfig.timeframe}
                onChange={(e) => setDiscoveryConfig({...discoveryConfig, timeframe: e.target.value})}
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
              >
                <option value="7d">Last 7 Days</option>
                <option value="30d">Last 30 Days</option>
                <option value="60d">Last 60 Days</option>
                <option value="90d">Last 90 Days</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Max Results</label>
              <select
                value={discoveryConfig.maxWallets}
                onChange={(e) => setDiscoveryConfig({...discoveryConfig, maxWallets: parseInt(e.target.value)})}
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
              >
                <option value="10">10 Wallets</option>
                <option value="25">25 Wallets</option>
                <option value="50">50 Wallets</option>
                <option value="100">100 Wallets</option>
              </select>
            </div>
          </div>
        </div>

        <button
          onClick={handleAutoDiscovery}
          disabled={isDiscovering}
          className="w-full mt-4 px-4 py-3 bg-gradient-to-r from-yellow-600 to-yellow-500 hover:from-yellow-700 hover:to-yellow-600 disabled:from-yellow-600/30 disabled:to-yellow-500/30 rounded-lg font-semibold transition flex items-center justify-center gap-2 shadow-lg shadow-yellow-500/30"
        >
          {isDiscovering ? (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Discovering...
            </>
          ) : (
            <>
              <Search size={18} />
              Start Auto Discovery
            </>
          )}
        </button>
      </div>

      {/* Discovery Results */}
      {discoveryResults && (
        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold flex items-center gap-2">
                <Sparkles className="text-yellow-400" size={18} />
                Discovery Results
              </h3>
              <p className="text-xs text-gray-400 mt-1">
                Found {discoveryResults.length} qualifying wallets
              </p>
            </div>

            {discoveryResults.length > 0 && (
              <button
                onClick={handleAddAll}
                className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold transition"
              >
                Add All to Watchlist
              </button>
            )}
          </div>

          {/* Results List */}
          {discoveryResults.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <AlertCircle size={48} className="mx-auto mb-3 opacity-20" />
              <p className="text-sm">No wallets found matching your criteria</p>
              <p className="text-xs mt-1">Try lowering your minimum thresholds</p>
            </div>
          ) : (
            <div className="space-y-2">
              {discoveryResults.map((wallet, idx) => (
                <div
                  key={wallet.wallet_address}
                  className="bg-black/30 border border-white/10 rounded-lg p-3 hover:bg-black/40 transition"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-yellow-400 font-bold">#{idx + 1}</span>
                        <code className="text-sm font-mono text-gray-300">
                          {wallet.wallet_address?.slice(0, 16)}...
                        </code>
                        
                        {/* Tier Badge */}
                        {wallet.tier && (
                          <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                            wallet.tier === 'S' ? 'bg-yellow-500/20 text-yellow-400' :
                            wallet.tier === 'A' ? 'bg-green-500/20 text-green-400' :
                            wallet.tier === 'B' ? 'bg-blue-500/20 text-blue-400' :
                            'bg-gray-500/20 text-gray-400'
                          }`}>
                            {wallet.tier}-Tier
                          </span>
                        )}
                      </div>

                      <div className="grid grid-cols-3 gap-3 text-xs">
                        <div>
                          <span className="text-gray-500">Runners Hit:</span>
                          <span className="ml-1 text-yellow-400 font-bold">
                            {wallet.runners_hit}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500">Score:</span>
                          <span className="ml-1 text-white font-bold">
                            {wallet.professional_score}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500">Avg ROI:</span>
                          <span className="ml-1 text-green-400 font-bold">
                            +{wallet.avg_roi_multiplier}x
                          </span>
                        </div>
                      </div>

                      {/* Recent Runners */}
                      {wallet.recent_runners && wallet.recent_runners.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-white/10">
                          <div className="text-xs text-gray-500 mb-1">Recent Hits:</div>
                          <div className="flex flex-wrap gap-1">
                            {wallet.recent_runners.slice(0, 5).map((token, tidx) => (
                              <span
                                key={tidx}
                                className="text-xs px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded"
                              >
                                {token}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Add Button */}
                    <button
                      onClick={() => handleAddWallet(wallet)}
                      className="ml-3 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold transition flex items-center gap-1"
                    >
                      <CheckCircle size={14} />
                      Add
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Info Banner */}
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3">
        <p className="text-xs text-blue-300">
          💡 <strong>Discovery Tip:</strong> Auto Discovery scans the last 30-60 days of trending tokens to find wallets with consistent performance. This is the fastest way to build a high-quality watchlist.
        </p>
      </div>

      {/* How It Works */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-4">
        <h4 className="text-sm font-semibold mb-2">How Auto Discovery Works</h4>
        <ol className="space-y-2 text-xs text-gray-400">
          <li className="flex gap-2">
            <span className="text-purple-400">1.</span>
            <span>Scans all trending tokens from the past {discoveryConfig.timeframe}</span>
          </li>
          <li className="flex gap-2">
            <span className="text-purple-400">2.</span>
            <span>Identifies wallets that hit {discoveryConfig.minRunners}+ runners</span>
          </li>
          <li className="flex gap-2">
            <span className="text-purple-400">3.</span>
            <span>Filters by professional score ({discoveryConfig.minScore}+)</span>
          </li>
          <li className="flex gap-2">
            <span className="text-purple-400">4.</span>
            <span>Returns top {discoveryConfig.maxWallets} most consistent performers</span>
          </li>
        </ol>
      </div>
    </div>
  );
}