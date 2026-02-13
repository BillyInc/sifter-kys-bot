import React, { useState } from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  ExternalLink, 
  Copy, 
  CheckCircle, 
  Clock, 
  DollarSign,
  ArrowRight,
  Activity
} from 'lucide-react';

export default function WalletAlertCard({ notification, onCopyTrade, onViewChart }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = (text, label) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(false), 2000);
  };

  const formatTime = (timestamp) => {
    const date = new Date(timestamp * 1000);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const formatUSD = (value) => {
    if (value >= 1000000) return `$${(value / 1000000).toFixed(2)}M`;
    if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
    return `$${value.toFixed(2)}`;
  };

  const isBuy = notification.side === 'buy';

  return (
    <div className={`bg-gradient-to-br ${
      isBuy 
        ? 'from-green-900/20 to-green-950/10 border-green-500/30' 
        : 'from-red-900/20 to-red-950/10 border-red-500/30'
    } border-2 rounded-2xl p-6 shadow-xl hover:shadow-2xl transition-all duration-300`}>
      
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={`p-3 rounded-xl ${
            isBuy ? 'bg-green-500/20' : 'bg-red-500/20'
          }`}>
            {isBuy ? (
              <TrendingUp className="text-green-400" size={24} />
            ) : (
              <TrendingDown className="text-red-400" size={24} />
            )}
          </div>

          <div>
            <h3 className={`text-lg font-bold ${
              isBuy ? 'text-green-400' : 'text-red-400'
            }`}>
              {isBuy ? 'BUY' : 'SELL'} ALERT
            </h3>
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <Clock size={12} />
              {formatTime(notification.block_time || notification.sent_at)}
            </div>
          </div>
        </div>

        <div className={`px-3 py-1 rounded-lg text-xs font-bold ${
          isBuy 
            ? 'bg-green-500/20 text-green-400' 
            : 'bg-red-500/20 text-red-400'
        }`}>
          LIVE
        </div>
      </div>

      {/* Transaction Details */}
      <div className="bg-black/40 border border-white/10 rounded-xl p-4 mb-4">
        <div className="grid grid-cols-2 gap-4 mb-3">
          <div>
            <p className="text-xs text-gray-400 mb-1">Wallet</p>
            <div className="flex items-center gap-2">
              <code className="text-sm text-purple-300 font-mono">
                {notification.wallet_address?.slice(0, 8)}...
              </code>
              <button
                onClick={() => handleCopy(notification.wallet_address, 'wallet')}
                className="p-1 hover:bg-white/10 rounded transition"
                title="Copy wallet address"
              >
                {copied === 'wallet' ? (
                  <CheckCircle className="text-green-400" size={14} />
                ) : (
                  <Copy className="text-gray-400" size={14} />
                )}
              </button>
            </div>
          </div>

          <div>
            <p className="text-xs text-gray-400 mb-1">Token</p>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-yellow-400">
                ${notification.token_ticker}
              </span>
              {notification.token_name && (
                <span className="text-xs text-gray-500 truncate">
                  {notification.token_name}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-gray-400 mb-1">USD Value</p>
            <div className="flex items-center gap-1">
              <DollarSign className="text-green-400" size={16} />
              <span className="text-lg font-bold text-white">
                {formatUSD(notification.usd_value)}
              </span>
            </div>
          </div>

          <div>
            <p className="text-xs text-gray-400 mb-1">Price</p>
            <span className="text-sm text-gray-300">
              {notification.price 
                ? `$${notification.price < 0.000001 
                    ? notification.price.toExponential(2) 
                    : notification.price.toFixed(6)}`
                : 'N/A'}
            </span>
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-2 gap-2">
        <button
          onClick={() => onCopyTrade && onCopyTrade(notification)}
          className="px-4 py-3 bg-gradient-to-r from-purple-600 to-purple-700 hover:from-purple-700 hover:to-purple-800 rounded-xl font-semibold transition flex items-center justify-center gap-2 group"
        >
          <Copy size={16} />
          <span>Copy Entry</span>
          <ArrowRight size={16} className="opacity-0 group-hover:opacity-100 transition" />
        </button>

        <button
          onClick={() => onViewChart && onViewChart(notification)}
          className="px-4 py-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl font-semibold transition flex items-center justify-center gap-2"
        >
          <Activity size={16} />
          <span>View Chart</span>
        </button>
      </div>

      {/* Transaction Link */}
      {notification.tx_hash && (
        <div className="mt-3 pt-3 border-t border-white/10">
          <a
            href={`https://solscan.io/tx/${notification.tx_hash}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-purple-400 hover:text-purple-300 transition flex items-center gap-1"
          >
            <ExternalLink size={12} />
            View Transaction on Solscan
          </a>
        </div>
      )}

      {/* Token Address (for copying) */}
      {notification.token_address && (
        <div className="mt-2 flex items-center gap-2">
          <code className="text-xs text-gray-500 font-mono flex-1 truncate">
            Token: {notification.token_address}
          </code>
          <button
            onClick={() => handleCopy(notification.token_address, 'token')}
            className="p-1 hover:bg-white/10 rounded transition"
            title="Copy token address"
          >
            {copied === 'token' ? (
              <CheckCircle className="text-green-400" size={12} />
            ) : (
              <Copy className="text-gray-400" size={12} />
            )}
          </button>
        </div>
      )}
    </div>
  );
}