import React, { useState, useEffect } from 'react';
import { Search, TrendingUp, Zap, BookmarkPlus, Trophy, Crown, Plus, X } from 'lucide-react';

export default function DashboardHome({ 
  user, 
  onOpenPanel,
  recentActivity = []
}) {
  // Persist the dismissed state so it survives re-renders (but resets on sign-out)
  const storageKey = `welcome_dismissed_${user?.id || 'guest'}`;
  const [showWelcome, setShowWelcome] = useState(() => {
    try { return localStorage.getItem(storageKey) !== 'true'; } catch { return true; }
  });

  const dismissWelcome = () => {
    setShowWelcome(false);
    try { localStorage.setItem(storageKey, 'true'); } catch {}
  };

  const quickActions = [
    { id: 'analyze',    icon: Search,      label: 'Analyze Tokens',       color: 'purple' },
    { id: 'trending',   icon: TrendingUp,  label: 'Trending Runners',      color: 'orange' },
    { id: 'discovery',  icon: Zap,         label: 'Auto Discovery',        color: 'yellow' },
    { id: 'watchlist',  icon: BookmarkPlus,label: 'Watchlist',             color: 'blue'   },
    { id: 'top100',     icon: Trophy,      label: 'Top 100 Community',     color: 'green'  },
    { id: 'premium100', icon: Crown,       label: 'Premium Elite 100',     color: 'pink'   },
    { id: 'quickadd',   icon: Plus,        label: 'Quick Add Wallet',      color: 'cyan'   },
  ];

  // Prefer display name → email prefix → 'User'
  const displayName =
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split('@')[0] ||
    'User';

  return (
    <div className="space-y-6">

      {/* ── Dismissible Welcome Header ── */}
      {showWelcome && (
        <div className="relative bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-6">
          {/* Close button */}
          <button
            onClick={dismissWelcome}
            title="Dismiss welcome banner"
            className="absolute top-3 right-3 p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition"
          >
            <X size={16} />
          </button>

          <h1 className="text-2xl font-bold mb-2">
            Welcome back, {displayName}! 👋
          </h1>
          <p className="text-gray-400">What would you like to do today?</p>
        </div>
      )}

      {/* ── Quick Actions Grid ── */}
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

      {/* ── Recent Activity ── */}
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