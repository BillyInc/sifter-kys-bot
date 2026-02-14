import React, { useState, useEffect } from 'react';
import { Crown, Lock, Download, TrendingUp, Filter } from 'lucide-react';

export default function PremiumElite100Panel({ 
  userId, 
  apiUrl, 
  isPremium = false,
  onUpgrade,
  onAddToWatchlist 
}) {
  const [eliteWallets, setEliteWallets] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sortBy, setSortBy] = useState('score'); // 'score', 'roi', 'runners'

  useEffect(() => {
    if (isPremium) {
      loadEliteWallets();
    }
  }, [isPremium, sortBy]);

  const loadEliteWallets = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(
        `${apiUrl}/api/wallets/premium-elite-100?user_id=${userId}&sort_by=${sortBy}`
      );
      const data = await response.json();
      
      if (data.success) {
        setEliteWallets(data.wallets || []);
      }
    } catch (error) {
      console.error('Error loading elite 100:', error);
    }
    setIsLoading(false);
  };

  const handleExport = async () => {
    try {
      const response = await fetch(
        `${apiUrl}/api/wallets/premium-elite-100/export?user_id=${userId}`
      );
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `elite-100-${Date.now()}.csv`;
      a.click();
    } catch (error) {
      console.error('Export error:', error);
    }
  };

  // Locked State (Non-Premium)
  if (!isPremium) {
    return (
      <div className="space-y-4">
        <div className="bg-gradient-to-br from-yellow-900/20 to-yellow-800/10 border-2 border-yellow-500/50 rounded-xl p-8 text-center">
          <div className="w-16 h-16 bg-yellow-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
            <Lock className="text-yellow-400" size={32} />
          </div>

          <h3 className="text-xl font-bold mb-2">👑 Premium Feature</h3>
          <p className="text-gray-400 mb-6">
            Access the Top 100 Elite Wallets - Algorithm-ranked by professional performance
          </p>

          {/* Feature List */}
          <div className="bg-black/30 rounded-lg p-4 mb-6 text-left">
            <div className="text-sm font-semibold text-yellow-400 mb-3">What's Included:</div>
            <ul className="space-y-2 text-xs text-gray-300">
              <li>✓ Top 100 most competent wallets (real-time ranked)</li>
              <li>✓ Professional Score weighted by multiple factors</li>
              <li>✓ Consistency across 30+ tokens</li>
              <li>✓ Realized profit multipliers</li>
              <li>✓ 7/30/60/90 day performance tracking</li>
              <li>✓ Export to CSV</li>
              <li>✓ "Add All Top 10" bulk action</li>
            </ul>
          </div>

          {/* Preview Top 3 (Blurred) */}
          <div className="bg-white/5 rounded-lg p-4 mb-6">
            <div className="text-xs font-semibold text-gray-400 mb-2">Preview: Top 3</div>
            <div className="space-y-2 blur-sm select-none">
              <div className="flex items-center justify-between text-xs">
                <span>🥇 #1: ████████...</span>
                <span className="text-yellow-400">956 ⭐</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span>🥈 #2: ████████...</span>
                <span className="text-yellow-400">948 ⭐</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span>🥉 #3: ████████...</span>
                <span className="text-yellow-400">942 ⭐</span>
              </div>
            </div>
          </div>

          <button
            onClick={onUpgrade}
            className="w-full px-6 py-3 bg-gradient-to-r from-yellow-600 to-yellow-500 hover:from-yellow-700 hover:to-yellow-600 rounded-xl font-bold text-lg transition shadow-lg shadow-yellow-500/30"
          >
            Upgrade to Premium - $49/mo
          </button>
        </div>
      </div>
    );
  }

  // Unlocked State (Premium)
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold flex items-center gap-2">
            <Crown className="text-yellow-400" size={20} />
            Premium Elite 100
          </h3>
          <p className="text-xs text-gray-400">Real-time • Multi-factor weighted</p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleExport}
            className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-semibold transition flex items-center gap-1"
          >
            <Download size={14} />
            Export CSV
          </button>
        </div>
      </div>

      {/* Sort Options */}
      <div className="flex items-center gap-2">
        <Filter size={14} className="text-gray-400" />
        <span className="text-xs text-gray-400">Sort by:</span>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="px-3 py-1.5 bg-black/50 border border-white/10 rounded-lg text-xs focus:outline-none focus:border-purple-500"
        >
          <option value="score">Professional Score</option>
          <option value="roi">30d ROI</option>
          <option value="runners">Runner Hits</option>
        </select>
      </div>

      {/* Elite Wallets List */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="w-8 h-8 border-2 border-white/30 border-t-purple-500 rounded-full animate-spin" />
        </div>
      ) : (
        <div className="space-y-2">
          {eliteWallets.map((wallet, idx) => (
            <div
              key={wallet.wallet_address}
              className="bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg p-3 transition"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 flex-1">
                  {/* Rank */}
                  <div className={`text-sm font-bold ${
                    idx < 3 ? 'text-yellow-400' : 'text-gray-400'
                  }`}>
                    {idx < 3 ? ['🥇', '🥈', '🥉'][idx] : `#${idx + 1}`}
                  </div>

                  {/* Wallet */}
                  <div className="flex-1">
                    <code className="text-sm font-mono text-gray-300">
                      {wallet.wallet_address?.slice(0, 16)}...
                    </code>
                    <div className="flex items-center gap-3 mt-1 text-xs">
                      <span className="text-yellow-400 font-bold">
                        {wallet.professional_score} ⭐
                      </span>
                      <span className="text-green-400">
                        +{wallet.roi_30d}% ROI
                      </span>
                      <span className="text-blue-400">
                        {wallet.runner_hits_30d} runners
                      </span>
                      <span className="text-purple-400">
                        {wallet.win_streak}W streak
                      </span>
                    </div>
                  </div>
                </div>

                {/* Track Button */}
                <button
                  onClick={() => onAddToWatchlist(wallet)}
                  className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold transition"
                >
                  Track
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Bulk Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => {
            eliteWallets.slice(0, 10).forEach(w => onAddToWatchlist(w));
          }}
          className="flex-1 px-4 py-2 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 rounded-lg font-semibold text-sm transition"
        >
          Add Top 10 to Watchlist
        </button>
      </div>

      {/* Hot Movers */}
      <div className="bg-gradient-to-r from-orange-900/20 to-orange-800/10 border border-orange-500/30 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-orange-400 mb-2 flex items-center gap-2">
          <TrendingUp size={14} />
          Hot Movers This Week
        </h4>
        <div className="space-y-1 text-xs text-gray-300">
          <div>• #12 → #4 (████... | +8 positions)</div>
          <div>• #28 → #15 (████... | +13 positions)</div>
        </div>
      </div>
    </div>
  );
}