import React, { useState, useEffect, useRef } from 'react';
import { BarChart3, TrendingUp, Target, Award, Calendar, Activity, X } from 'lucide-react';

// Simple in-memory cache so re-opening the panel feels instant
const statsCache = {};

function SkeletonBox({ className = '' }) {
  return (
    <div className={`animate-pulse bg-white/10 rounded-lg ${className}`} />
  );
}

export default function MyDashboardPanel({ userId, apiUrl }) {
  const [stats, setStats] = useState(statsCache[userId] || null);
  const [isLoading, setIsLoading] = useState(!statsCache[userId]);
  // Dismissible welcome banner (per user)
  const storageKey = `dash_welcome_dismissed_${userId}`;
  const [showWelcome, setShowWelcome] = useState(() => {
    try { return localStorage.getItem(storageKey) !== 'true'; } catch { return true; }
  });

  const dismissWelcome = () => {
    setShowWelcome(false);
    try { localStorage.setItem(storageKey, 'true'); } catch {}
  };

  useEffect(() => {
    // If we already have cached data, show it immediately and refresh silently
    if (statsCache[userId]) {
      setStats(statsCache[userId]);
      setIsLoading(false);
      loadStats(true); // silent background refresh
    } else {
      loadStats(false);
    }
  }, [userId]);

  const loadStats = async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      const response = await fetch(`${apiUrl}/api/user/dashboard-stats?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        statsCache[userId] = data.stats; // cache it
        setStats(data.stats);
      }
    } catch (error) {
      console.error('Error loading stats:', error);
    }
    if (!silent) setIsLoading(false);
  };

  // ── Skeleton UI (first load only) ────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="space-y-4">
        <SkeletonBox className="h-24 w-full" />
        <div className="grid grid-cols-2 gap-4">
          {[...Array(4)].map((_, i) => <SkeletonBox key={i} className="h-20" />)}
        </div>
        <SkeletonBox className="h-40 w-full" />
        <SkeletonBox className="h-32 w-full" />
      </div>
    );
  }

  // ── Loaded UI ─────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">

      {/* Dismissible Welcome Banner */}
      {showWelcome && (
        <div className="relative bg-gradient-to-br from-purple-900/30 to-purple-800/20 border border-purple-500/30 rounded-xl p-6">
          <button
            onClick={dismissWelcome}
            className="absolute top-3 right-3 p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition"
          >
            <X size={16} />
          </button>
          <h2 className="text-2xl font-bold mb-2">Welcome back! 👋</h2>
          <p className="text-gray-400">Here's your performance overview</p>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <BarChart3 className="text-purple-400" size={20} />
            <span className="text-2xl font-bold text-purple-400">{stats?.tokens_analyzed || 0}</span>
          </div>
          <div className="text-xs text-gray-400">Tokens Analyzed (This Week)</div>
        </div>

        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <Activity className="text-green-400" size={20} />
            <span className="text-2xl font-bold text-green-400">{stats?.watchlist_count || 0}</span>
          </div>
          <div className="text-xs text-gray-400">Wallets in Watchlist</div>
        </div>

        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <TrendingUp className="text-blue-400" size={20} />
            <span className="text-2xl font-bold text-blue-400">{stats?.success_rate || 0}%</span>
          </div>
          <div className="text-xs text-gray-400">Success Rate</div>
        </div>

        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <Target className="text-yellow-400" size={20} />
            <span className="text-2xl font-bold text-yellow-400">{stats?.avg_roi || 0}%</span>
          </div>
          <div className="text-xs text-gray-400">Avg Watchlist ROI</div>
        </div>
      </div>

      {/* Recent Activity */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Calendar className="text-purple-400" size={16} />
          Recent Activity
        </h3>
        <div className="space-y-2">
          {(stats?.recent_activity || []).map((activity, idx) => (
            <div key={idx} className="flex items-center justify-between p-2 bg-black/30 rounded">
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${
                  activity.type === 'analysis' ? 'bg-purple-500' :
                  activity.type === 'watchlist' ? 'bg-blue-500' : 'bg-green-500'
                }`} />
                <span className="text-sm">{activity.description}</span>
              </div>
              <span className="text-xs text-gray-400">{activity.time}</span>
            </div>
          ))}
          {(!stats?.recent_activity || stats.recent_activity.length === 0) && (
            <div className="text-center py-6 text-gray-500 text-sm">No recent activity</div>
          )}
        </div>
      </div>

      {/* Top Performers */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Award className="text-yellow-400" size={16} />
          Your Top Performing Wallets
        </h3>
        <div className="space-y-2">
          {(stats?.top_performers || []).slice(0, 3).map((wallet, idx) => (
            <div key={idx} className="flex items-center justify-between p-2 bg-black/30 rounded">
              <div className="flex items-center gap-2">
                <span className="text-lg">{idx === 0 ? '🥇' : idx === 1 ? '🥈' : '🥉'}</span>
                <code className="text-sm font-mono text-gray-300">{wallet.address?.slice(0, 8)}…</code>
              </div>
              <span className="text-sm font-bold text-green-400">+{wallet.roi}%</span>
            </div>
          ))}
          {(!stats?.top_performers || stats.top_performers.length === 0) && (
            <div className="text-center py-6 text-gray-500 text-sm">
              Add wallets to your watchlist to see top performers
            </div>
          )}
        </div>
      </div>

      {/* This Week Summary */}
      <div className="bg-gradient-to-r from-blue-900/20 to-blue-800/10 border border-blue-500/30 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3 text-blue-400">📊 This Week Summary</h3>
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div><span className="text-gray-400">Analyses Run:</span><span className="ml-2 font-bold text-white">{stats?.analyses_this_week || 0}</span></div>
          <div><span className="text-gray-400">Wallets Added:</span><span className="ml-2 font-bold text-white">{stats?.wallets_added_this_week || 0}</span></div>
          <div><span className="text-gray-400">Alerts Received:</span><span className="ml-2 font-bold text-white">{stats?.alerts_this_week || 0}</span></div>
          <div><span className="text-gray-400">Most Analyzed:</span><span className="ml-2 font-bold text-yellow-400">{stats?.most_analyzed_token || 'N/A'}</span></div>
        </div>
      </div>
    </div>
  );
}