import React, { useState, useEffect } from 'react';
import { Trophy, TrendingUp, BookmarkPlus, RefreshCw } from 'lucide-react';

export default function Top100CommunityPanel({ userId, apiUrl, onAddToWatchlist }) {
  const [leaderboard, setLeaderboard] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);

  useEffect(() => {
    loadLeaderboard();
  }, []);

  const loadLeaderboard = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`${apiUrl}/api/wallets/top-100-community?user_id=${userId}`);
      const data = await response.json();
      
      if (data.success) {
        setLeaderboard(data.wallets || []);
        setLastUpdate(new Date());
      }
    } catch (error) {
      console.error('Error loading top 100:', error);
    }
    setIsLoading(false);
  };

  const formatTimeSince = (date) => {
    if (!date) return 'Never';
    const hours = Math.floor((Date.now() - date.getTime()) / 1000 / 60 / 60);
    return hours < 1 ? 'Just now' : `${hours}h ago`;
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold">🔥 Most Added Wallets (This Week)</h3>
          <p className="text-xs text-gray-400">Updated: {formatTimeSince(lastUpdate)}</p>
        </div>
        <button
          onClick={loadLeaderboard}
          disabled={isLoading}
          className="p-2 hover:bg-white/10 rounded-lg transition"
        >
          <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Info Banner */}
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3">
        <p className="text-xs text-blue-300">
          💡 See what the community is watching - these wallets have been added most by other users this week
        </p>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <div className="w-8 h-8 border-2 border-white/30 border-t-purple-500 rounded-full animate-spin" />
        </div>
      )}

      {/* Leaderboard */}
      {!isLoading && (
        <div className="space-y-2">
          {leaderboard.map((wallet, idx) => (
            <div
              key={wallet.wallet_address}
              className="bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg p-3 transition"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 flex-1">
                  {/* Rank */}
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold ${
                    idx === 0 ? 'bg-yellow-500/20 text-yellow-400' :
                    idx === 1 ? 'bg-gray-400/20 text-gray-400' :
                    idx === 2 ? 'bg-orange-500/20 text-orange-400' :
                    'bg-white/10 text-gray-400'
                  }`}>
                    {idx < 3 ? ['🥇', '🥈', '🥉'][idx] : idx + 1}
                  </div>

                  {/* Wallet Info */}
                  <div className="flex-1">
                    <code className="text-sm font-mono text-gray-300">
                      {wallet.wallet_address?.slice(0, 12)}...
                    </code>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-gray-400">
                        <TrendingUp size={12} className="inline mr-1" />
                        {wallet.times_added} adds
                      </span>
                      {wallet.avg_score && (
                        <span className="text-xs text-purple-400">
                          {wallet.avg_score} ⭐ avg
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Add Button */}
                <button
                  onClick={() => onAddToWatchlist(wallet)}
                  className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold transition flex items-center gap-1"
                >
                  <BookmarkPlus size={14} />
                  Add
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Trending Section */}
      {!isLoading && leaderboard.length > 0 && (
        <div className="bg-gradient-to-r from-green-900/20 to-green-800/10 border border-green-500/30 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-green-400 mb-2">📈 Trending Up This Week</h4>
          <div className="space-y-1 text-xs text-gray-300">
            {leaderboard.slice(0, 3).map((wallet, idx) => (
              <div key={idx}>
                • {wallet.wallet_address?.slice(0, 8)}... (+{wallet.rank_change || 0} positions)
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}