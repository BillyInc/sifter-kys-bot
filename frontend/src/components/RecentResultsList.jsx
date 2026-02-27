// components/panels/RecentResultsList.jsx
import React from 'react';
import { Clock, Trash2, ChevronRight, BarChart3, TrendingUp, Zap, RefreshCw } from 'lucide-react';

const TYPE_META = {
  'single-token':    { icon: <BarChart3  size={14} className="text-purple-400" />, color: 'border-purple-500/20 bg-purple-500/5'  },
  'batch-token':     { icon: <BarChart3  size={14} className="text-blue-400"   />, color: 'border-blue-500/20 bg-blue-500/5'      },
  'trending-single': { icon: <TrendingUp size={14} className="text-orange-400" />, color: 'border-orange-500/20 bg-orange-500/5'  },
  'trending-batch':  { icon: <TrendingUp size={14} className="text-orange-400" />, color: 'border-orange-500/20 bg-orange-500/5'  },
  'discovery':       { icon: <Zap        size={14} className="text-yellow-400" />, color: 'border-yellow-500/20 bg-yellow-500/5'  },
};

function timeAgo(ts) {
  const diff = Date.now() - new Date(ts).getTime();
  if (isNaN(diff) || diff < 0) return 'just now';
  const m = Math.floor(diff / 60_000);
  const h = Math.floor(diff / 3_600_000);
  const d = Math.floor(diff / 86_400_000);
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  if (h < 24) return `${h}h ago`;
  return `${d}d ago`;
}

function getWalletCount(data) {
  if (!data) return 0;
  return (
    data.wallets?.length             ??
    data.smart_money_wallets?.length ??
    data.top_wallets?.length         ??
    0
  );
}

export default function RecentResultsList({
  recents,
  loading,
  error,
  onOpen,
  onRemove,
  onClear,
  onRefresh,
}) {
  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-gray-600 uppercase font-semibold tracking-wide">Loading…</span>
        </div>
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="animate-pulse bg-white/5 border border-white/10 rounded-xl h-[62px]"
          />
        ))}
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="text-center py-14">
        <Clock size={40} className="mx-auto mb-3 opacity-20 text-red-400" />
        <p className="text-sm text-red-400">Failed to load recents</p>
        <p className="text-xs text-gray-600 mt-1">{error}</p>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="mt-4 flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs text-gray-400 transition mx-auto"
          >
            <RefreshCw size={12} /> Try again
          </button>
        )}
      </div>
    );
  }

  // ── Empty state ───────────────────────────────────────────────────────────
  if (recents.length === 0) {
    return (
      <div className="text-center py-14 text-gray-600">
        <Clock size={40} className="mx-auto mb-3 opacity-30" />
        <p className="text-sm text-gray-500">No recent analyses yet</p>
        <p className="text-xs mt-1">Run an analysis and it'll appear here for 6 hours</p>
      </div>
    );
  }

  // ── List ──────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-gray-500 uppercase font-semibold tracking-wide">
          Recent ({recents.length})
        </span>
        <div className="flex items-center gap-3">
          {onRefresh && (
            <button
              onClick={onRefresh}
              className="text-xs text-gray-600 hover:text-gray-400 transition flex items-center gap-1"
              title="Refresh"
            >
              <RefreshCw size={11} />
            </button>
          )}
          <button
            onClick={onClear}
            className="text-xs text-gray-600 hover:text-red-400 transition"
          >
            Clear all
          </button>
        </div>
      </div>

      {recents.map(entry => {
        const meta        = TYPE_META[entry.resultType] || TYPE_META['single-token'];
        const walletCount = getWalletCount(entry.data);

        return (
          <div
            key={entry.id}
            className={`group flex items-center gap-3 border rounded-xl px-3 py-3 cursor-pointer hover:brightness-125 transition-all ${meta.color}`}
            onClick={() => onOpen(entry)}
          >
            <div className="shrink-0">{meta.icon}</div>

            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-white truncate">{entry.label}</div>
              <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                <span className="text-xs text-gray-500">{entry.sublabel}</span>
                {walletCount > 0 && (
                  <>
                    <span className="text-gray-700">•</span>
                    <span className="text-xs text-gray-500">{walletCount} wallets</span>
                  </>
                )}
                <span className="text-gray-700">•</span>
                <span className="text-xs text-gray-600">{timeAgo(entry.timestamp)}</span>
              </div>
            </div>

            <ChevronRight
              size={14}
              className="text-gray-600 group-hover:text-gray-400 shrink-0 transition"
            />

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

      <p className="text-xs text-gray-700 text-center pt-2">
        Results cached for 6 hours · shared across all your devices
      </p>
    </div>
  );
}