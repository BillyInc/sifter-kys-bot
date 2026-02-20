// components/panels/RecentResultsList.jsx
import React from 'react';
import { Clock, Trash2, ChevronRight, BarChart3, TrendingUp, Zap } from 'lucide-react';

const TYPE_META = {
  'single-token':    { icon: <BarChart3 size={14} className="text-purple-400" />, color: 'border-purple-500/20 bg-purple-500/5' },
  'batch-token':     { icon: <BarChart3 size={14} className="text-blue-400" />,   color: 'border-blue-500/20 bg-blue-500/5' },
  'trending-single': { icon: <TrendingUp size={14} className="text-orange-400" />, color: 'border-orange-500/20 bg-orange-500/5' },
  'trending-batch':  { icon: <TrendingUp size={14} className="text-orange-400" />, color: 'border-orange-500/20 bg-orange-500/5' },
  'discovery':       { icon: <Zap size={14} className="text-yellow-400" />,        color: 'border-yellow-500/20 bg-yellow-500/5' },
};

function timeAgo(ts) {
  const diff = Date.now() - ts;
  const m = Math.floor(diff / 60000);
  const h = Math.floor(diff / 3600000);
  const d = Math.floor(diff / 86400000);
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  if (h < 24) return `${h}h ago`;
  return `${d}d ago`;
}

export default function RecentResultsList({ recents, loading, onOpen, onRemove, onClear }) {
  if (loading) {
    return (
      <div className="space-y-2">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="animate-pulse bg-white/5 border border-white/10 rounded-lg h-16" />
        ))}
      </div>
    );
  }

  if (recents.length === 0) {
    return (
      <div className="text-center py-14 text-gray-600">
        <Clock size={40} className="mx-auto mb-3 opacity-30" />
        <p className="text-sm text-gray-500">No recent analyses yet</p>
        <p className="text-xs mt-1">Run an analysis and it'll appear here</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-gray-500 uppercase font-semibold">Recent ({recents.length})</span>
        <button
          onClick={onClear}
          className="text-xs text-gray-600 hover:text-red-400 transition"
        >
          Clear all
        </button>
      </div>

      {recents.map(entry => {
        const meta = TYPE_META[entry.resultType] || TYPE_META['single-token'];
        const walletCount = entry.data?.wallets?.length
          ?? entry.data?.smart_money_wallets?.length
          ?? entry.data?.top_wallets?.length
          ?? 0;

        return (
          <div
            key={entry.id}
            className={`group flex items-center gap-3 border rounded-xl px-3 py-3 cursor-pointer hover:brightness-125 transition-all ${meta.color}`}
            onClick={() => onOpen(entry)}
          >
            <div className="shrink-0">{meta.icon}</div>

            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-white truncate">{entry.label}</div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-gray-500">{entry.sublabel}</span>
                <span className="text-gray-700">•</span>
                <span className="text-xs text-gray-500">{walletCount} wallets</span>
                <span className="text-gray-700">•</span>
                <span className="text-xs text-gray-600">{timeAgo(entry.timestamp)}</span>
              </div>
            </div>

            <ChevronRight size={14} className="text-gray-600 group-hover:text-gray-400 shrink-0 transition" />

            <button
              onClick={e => { e.stopPropagation(); onRemove(entry.id); }}
              className="shrink-0 p-1 text-gray-700 hover:text-red-400 transition opacity-0 group-hover:opacity-100"
              title="Remove"
            >
              <Trash2 size={12} />
            </button>
          </div>
        );
      })}
    </div>
  );
}