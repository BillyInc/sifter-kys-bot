import React, { useState, useEffect } from 'react';
import { Copy, Share2, TrendingUp, Users, Award } from 'lucide-react';

export default function ReferralDashboardSubPanel({ userId, apiUrl, onBack }) {
  const [dashboard, setDashboard] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    loadDashboard();
  }, [userId]);

  const loadDashboard = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/referral-points/dashboard`, {
        headers: { 'Authorization': `Bearer ${getAccessToken()}` }
      });
      const data = await response.json();
      if (data.success) {
        setDashboard(data);
      }
    } catch (error) {
      console.error('Dashboard error:', error);
    }
    setIsLoading(false);
  };

  const copyLink = () => {
    navigator.clipboard.writeText(dashboard.referrals.link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isLoading) {
    return <div className="flex justify-center py-12">
      <div className="w-8 h-8 border-2 border-white/30 border-t-purple-500 rounded-full animate-spin" />
    </div>;
  }

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-sm text-purple-400 hover:text-purple-300">
        ← Back to Profile
      </button>

      {/* Referral Code Card */}
      <div className="bg-gradient-to-br from-purple-900/30 to-purple-800/20 border border-purple-500/30 rounded-xl p-6">
        <h3 className="text-lg font-bold mb-4">🎁 Your Referral Code</h3>
        <div className="bg-black/50 border border-white/10 rounded-lg p-3 mb-3">
          <code className="text-2xl font-bold text-purple-400">
            {dashboard.referrals.code}
          </code>
        </div>
        
        <div className="flex gap-2">
          <input
            value={dashboard.referrals.link}
            readOnly
            className="flex-1 bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
          />
          <button
            onClick={copyLink}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded transition flex items-center gap-2"
          >
            <Copy size={16} />
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <Users className="text-blue-400" size={20} />
            <span className="text-2xl font-bold">{dashboard.referrals.stats.clicks}</span>
          </div>
          <div className="text-xs text-gray-400">Clicks</div>
        </div>

        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <TrendingUp className="text-green-400" size={20} />
            <span className="text-2xl font-bold">{dashboard.referrals.stats.signups}</span>
          </div>
          <div className="text-xs text-gray-400">Signups</div>
        </div>

        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <Award className="text-yellow-400" size={20} />
            <span className="text-2xl font-bold">{dashboard.referrals.conversions}</span>
          </div>
          <div className="text-xs text-gray-400">Conversions</div>
        </div>

        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-green-400 text-2xl">💰</span>
            <span className="text-2xl font-bold text-green-400">
              ${dashboard.referrals.total_earnings}
            </span>
          </div>
          <div className="text-xs text-gray-400">Earnings</div>
        </div>
      </div>

      {/* Points Section */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3">🏆 Your Points</h3>
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Total Points:</span>
            <span className="text-2xl font-bold text-purple-400">
              {dashboard.points.total.toLocaleString()}
            </span>
          </div>
          <div className="flex justify-between items-center text-sm">
            <span className="text-gray-400">Global Rank:</span>
            <span className="font-bold text-yellow-400">#{dashboard.points.rank}</span>
          </div>
          <div className="flex justify-between items-center text-sm">
            <span className="text-gray-400">Daily Streak:</span>
            <span className="font-bold text-orange-400">{dashboard.points.streak} 🔥</span>
          </div>
        </div>
      </div>

      {/* Share Options */}
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3 text-blue-400">📢 Share & Earn</h3>
        <div className="grid grid-cols-2 gap-2">
          <button className="px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm transition">
            Twitter
          </button>
          <button className="px-3 py-2 bg-purple-600 hover:bg-purple-700 rounded text-sm transition">
            Discord
          </button>
          <button className="px-3 py-2 bg-green-600 hover:bg-green-700 rounded text-sm transition">
            Telegram
          </button>
          <button className="px-3 py-2 bg-orange-600 hover:bg-orange-700 rounded text-sm transition">
            Copy Link
          </button>
        </div>
      </div>
    </div>
  );
}