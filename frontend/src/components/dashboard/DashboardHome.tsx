import React, { useState, useEffect } from 'react';
import { Search, TrendingUp, Zap, BookmarkPlus, Trophy, Crown, Plus, X, LucideIcon } from 'lucide-react';

interface ActivityItem {
  description: string;
  time: string;
}

interface DashboardHomeProps {
  user: any;
  onOpenPanel: (id: string) => void;
  recentActivity?: ActivityItem[];
}

interface QuickAction {
  id: string;
  icon: LucideIcon;
  label: string;
  color: string;
}

export default function DashboardHome({
  user,
  onOpenPanel,
  recentActivity = []
}: DashboardHomeProps) {
  // Persist the dismissed state so it survives re-renders (but resets on sign-out)
  const storageKey = `welcome_dismissed_${user?.id || 'guest'}`;
  const [showWelcome, setShowWelcome] = useState<boolean>(() => {
    try { return localStorage.getItem(storageKey) !== 'true'; } catch { return true; }
  });

  const dismissWelcome = () => {
    setShowWelcome(false);
    try { localStorage.setItem(storageKey, 'true'); } catch {}
  };

  const quickActions: QuickAction[] = [
    { id: 'analyze',    icon: Search,      label: 'Analyze Tokens',       color: 'purple' },
    { id: 'trending',   icon: TrendingUp,  label: 'Trending Runners',      color: 'orange' },
    { id: 'discovery',  icon: Zap,         label: 'Auto Discovery',        color: 'yellow' },
    { id: 'watchlist',  icon: BookmarkPlus,label: 'Watchlist',             color: 'blue'   },
    { id: 'top100',     icon: Trophy,      label: 'Top 100 Community',     color: 'green'  },
    { id: 'premium100', icon: Crown,       label: 'Premium Elite 100',     color: 'pink'   },
    { id: 'quickadd',   icon: Plus,        label: 'Quick Add Wallet',      color: 'cyan'   },
  ];

  // Prefer display name -> email prefix -> 'User'
  const displayName =
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split('@')[0] ||
    'User';

  return (
    <div className="space-y-6" style={{ color: 'var(--text-primary)' }}>

      {/* ── Dismissible Welcome Header ── */}
      {showWelcome && (
        <div className="relative bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-6">
          {/* Close button */}
          <button
            onClick={dismissWelcome}
            title="Dismiss welcome banner"
            className="absolute top-3 right-3 p-1.5 rounded-lg transition"
            style={{ color: 'var(--text-secondary)' }}
            onMouseEnter={(e: React.MouseEvent<HTMLButtonElement>) => e.currentTarget.style.backgroundColor = 'var(--bg-secondary)'}
            onMouseLeave={(e: React.MouseEvent<HTMLButtonElement>) => e.currentTarget.style.backgroundColor = 'transparent'}
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
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {quickActions.map((action) => (
            <button
              key={action.id}
              onClick={() => onOpenPanel(action.id)}
              className="group relative hover:border-purple-500/50 border rounded-xl p-3 sm:p-6 transition-all duration-300"
              style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
            >
              <div className="flex sm:flex-col items-center gap-2 sm:gap-3">
                <div className={`p-2 sm:p-4 bg-${action.color}-500/20 rounded-xl group-hover:scale-110 transition-transform flex-shrink-0`}>
                  <action.icon className={`w-5 h-5 sm:w-8 sm:h-8 text-${action.color}-400`} />
                </div>
                <span className="font-semibold text-sm sm:text-base sm:text-center truncate max-w-full">{action.label}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* ── Recent Activity ── */}
      {recentActivity.length > 0 && (
        <div className="border rounded-xl p-4" style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
          <h3 className="text-lg font-semibold mb-3">Recent Activity</h3>
          <div className="space-y-2">
            {recentActivity.slice(0, 5).map((activity, idx) => (
              <div key={`${activity.description}-${activity.time}-${idx}`} className="flex items-center justify-between p-2 rounded" style={{ backgroundColor: 'var(--bg-secondary)' }}>
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
