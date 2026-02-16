import React, { useState } from 'react';
import { Zap, Search, Sparkles, CheckCircle, AlertCircle, Shield} from 'lucide-react';

export default function DiscoveryPanel({
  userId,
  apiUrl,
  onClose,
  onAddToWatchlist,
  formatNumber
}) {
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discoveryResults, setDiscoveryResults] = useState(null);
  const [minRunners, setMinRunners] = useState(2);
  const [minRoiMultiplier, setMinRoiMultiplier] = useState(3.0);

  const handleAutoDiscovery = async () => {
    setIsDiscovering(true);
    setDiscoveryResults(null);

    try {
      const response = await fetch(`${apiUrl}/api/wallets/discover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          min_runner_hits: minRunners,
          min_roi_multiplier: minRoiMultiplier
        })
      });

      const data = await response.json();
      
      if (data.success) {
        setDiscoveryResults(data.top_wallets || data.smart_money_wallets || []);
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
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          wallet: {
            wallet: wallet.wallet,
            tier: wallet.tier || 'C',
            pump_count: wallet.runner_hits_30d || wallet.runner_count || 0,
            avg_distance_to_peak: wallet.avg_distance_to_ath_pct || 0,
            avg_roi_to_peak: wallet.avg_roi || 0,
            professional_score: wallet.avg_professional_score || wallet.professional_score || 0,
            consistency_score: wallet.consistency_score || 0,
            tokens_hit: wallet.runners_hit || []
          }
        })
      });

      const data = await response.json();
      
      if (data.success) {
        alert(`✅ Added ${wallet.wallet.slice(0, 8)}... to watchlist`);
      } else {
        alert(`Failed: ${data.error}`);
      }
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

    let successCount = 0;
    for (const wallet of discoveryResults) {
      try {
        await handleAddWallet(wallet);
        successCount++;
      } catch (error) {
        console.error('Failed to add wallet:', error);
      }
    }
    
    alert(`✅ Added ${successCount}/${discoveryResults.length} wallets to your watchlist!`);
  };

  return (
    <div className="space-y-4">
      {/* Discovery Configuration */}
      <div className="bg-gradient-to-br from-yellow-900/20 to-yellow-800/10 border border-yellow-500/30 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Zap className="text-yellow-400" size={20} />
          <h3 className="text-base font-semibold">Auto Discovery</h3>
        </div>

        <p className="text-xs text-gray-400 mb-4">
          Automatically scan the last 30 days of trending tokens to find wallets that consistently hit multiple runners
        </p>

        
          <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-3 mb-4">
            <div className="flex items-center gap-2 text-xs">
              <Shield className="text-green-400" size={14} />
              <span className="text-green-400 font-semibold">Security Filter Active</span>
            </div>
            <p className="text-xs text-gray-400 mt-1">
              All tokens are verified for: Liquidity locked • Mint authority revoked • Social presence
            </p>
          </div>

        
     

        <button
          onClick={handleAutoDiscovery}
          disabled={isDiscovering}
          className="w-full px-4 py-3 bg-gradient-to-r from-yellow-600 to-yellow-500 hover:from-yellow-700 hover:to-yellow-600 disabled:from-yellow-600/30 disabled:to-yellow-500/30 rounded-lg font-semibold transition flex items-center justify-center gap-2 shadow-lg shadow-yellow-500/30"
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
                  key={wallet.wallet}
                  className="bg-black/30 border border-white/10 rounded-lg p-3 hover:bg-black/40 transition"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-yellow-400 font-bold">#{idx + 1}</span>
                        <code className="text-sm font-mono text-gray-300">
                          {wallet.wallet?.slice(0, 16)}...
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
                          <span className="text-gray-500">Runners:</span>
                          <span className="ml-1 text-yellow-400 font-bold">
                            {wallet.runner_count || wallet.runner_hits_30d || 0}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500">Score:</span>
                          <span className="ml-1 text-white font-bold">
                            {wallet.avg_professional_score || wallet.professional_score || 0}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500">Avg ROI:</span>
                          <span className="ml-1 text-green-400 font-bold">
                            +{wallet.avg_roi || 0}%
                          </span>
                        </div>
                      </div>

                      {/* Recent Runners */}
                      {wallet.runners_hit && wallet.runners_hit.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-white/10">
                          <div className="text-xs text-gray-500 mb-1">Recent Hits:</div>
                          <div className="flex flex-wrap gap-1">
                            {wallet.runners_hit.slice(0, 5).map((token, tidx) => (
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

      {/* How It Works */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-4">
        <h4 className="text-sm font-semibold mb-2">How Auto Discovery Works</h4>
        <ol className="space-y-2 text-xs text-gray-400">
          <li className="flex gap-2">
            <span className="text-purple-400">1.</span>
            <span>Scans all trending tokens from the past 30 days</span>
          </li>
          <li className="flex gap-2">
            <span className="text-purple-400">2.</span>
            <span>Identifies wallets that hit {minRunners}+ runners</span>
          </li>
          <li className="flex gap-2">
            <span className="text-purple-400">3.</span>
            <span>Filters by {minRoiMultiplier}x minimum ROI multiplier</span>
          </li>
          <li className="flex gap-2">
            <span className="text-purple-400">4.</span>
            <span>Returns top 50 most consistent performers</span>
          </li>
        </ol>
      </div>
    </div>
  );
}