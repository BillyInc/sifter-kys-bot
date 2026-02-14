import React from 'react';
import { Search, TrendingUp, Zap, BookmarkPlus, Trophy, Crown, Plus } from 'lucide-react';

export default function DashboardHome({ 
  user, 
  onOpenPanel,
  recentActivity = [],
  // NEW: Add results props
  analysisResults = null,
  isAnalyzing = false
}) {
  const quickActions = [
    { id: 'analyze', icon: Search, label: 'Analyze Tokens', color: 'purple' },
    { id: 'trending', icon: TrendingUp, label: 'Trending Runners', color: 'orange' },
    { id: 'discovery', icon: Zap, label: 'Auto Discovery', color: 'yellow' },
    { id: 'watchlist', icon: BookmarkPlus, label: 'Watchlist', color: 'blue' },
    { id: 'top100', icon: Trophy, label: 'Top 100 Community', color: 'green' },
    { id: 'premium100', icon: Crown, label: 'Premium Elite 100', color: 'pink' },
    { id: 'quickadd', icon: Plus, label: 'Quick Add Wallet', color: 'cyan' },
  ];

  return (
    <div className="space-y-6">
      {/* Welcome Header */}
      <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-6">
        <h1 className="text-2xl font-bold mb-2">Welcome back, {user?.email?.split('@')[0] || 'User'}! 👋</h1>
        <p className="text-gray-400">What would you like to do today?</p>
      </div>

      {/* Quick Actions Grid */}
      <div>
        <h2 className="text-lg font-semibold mb-4">Quick Actions</h2>
        <div className="grid grid-cols-3 gap-4">
          {quickActions.map((action) => (
            <button
              key={action.id}
              onClick={() => onOpenPanel(action.id)}
              className="group relative bg-white/5 hover:bg-white/10 border border-white/10 hover:border-purple-500/50 rounded-xl p-6 transition-all duration-300"
            >
              <div className="flex flex-col items-center gap-3">
                <div className={`p-4 bg-${action.color}-500/20 rounded-xl group-hover:scale-110 transition-transform`}>
                  <action.icon size={32} className={`text-${action.color}-400`} />
                </div>
                <span className="font-semibold text-center">{action.label}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* ANALYSIS RESULTS SECTION */}
      {(isAnalyzing || analysisResults) && (
        <div className="bg-white/5 border border-white/10 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">Analysis Results</h2>
          
          {isAnalyzing ? (
            <div className="flex flex-col items-center justify-center py-12">
              <div className="w-12 h-12 border-4 border-white/20 border-t-purple-500 rounded-full animate-spin mb-4" />
              <p className="text-gray-400">Analyzing wallets...</p>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Results Summary */}
              {analysisResults?.summary && (
                <div className="grid grid-cols-4 gap-4 p-4 bg-gradient-to-r from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-lg">
                  <div>
                    <div className="text-2xl font-bold text-green-400">
                      {analysisResults.summary.qualified_wallets || 0}
                    </div>
                    <div className="text-xs text-gray-400">Qualified Wallets</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-yellow-400">
                      {analysisResults.summary.real_winners || 0}
                    </div>
                    <div className="text-xs text-gray-400">S-Tier Wallets</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-blue-400">
                      {analysisResults.summary.total_rallies || 0}
                    </div>
                    <div className="text-xs text-gray-400">Total Rallies</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-purple-400">
                      {analysisResults.summary.tokens_analyzed || 0}
                    </div>
                    <div className="text-xs text-gray-400">Tokens Analyzed</div>
                  </div>
                </div>
              )}

              {/* Top Wallets */}
              {analysisResults?.top_wallets?.slice(0, 5).map((wallet, idx) => (
                <div key={wallet.wallet} className="bg-black/30 border border-white/10 rounded-lg p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-purple-400 font-bold">#{idx + 1}</span>
                      <code className="text-sm font-mono">{wallet.wallet?.slice(0, 12)}...</code>
                      {wallet.professional_grade && (
                        <span className="px-2 py-1 bg-purple-500/20 text-purple-400 rounded text-xs font-bold">
                          {wallet.professional_grade} • {wallet.professional_score}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              <button
                onClick={() => analysisResults = null}
                className="w-full px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm font-semibold transition"
              >
                Clear Results
              </button>
            </div>
          )}
        </div>
      )}

      {/* Recent Activity */}
      {recentActivity.length > 0 && (
        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <h3 className="text-lg font-semibold mb-3">Recent Activity</h3>
          <div className="space-y-2">
            {recentActivity.slice(0, 5).map((activity, idx) => (
              <div key={idx} className="flex items-center justify-between p-2 bg-black/30 rounded">
                <span className="text-sm">{activity.description}</span>
                <span className="text-xs text-gray-400">{activity.time}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}