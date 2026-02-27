import React, { useState } from 'react';
import { Plus, CheckCircle, Zap, AlertCircle } from 'lucide-react';

export default function QuickAddWalletPanel({ 
  userId, 
  apiUrl, 
  onSuccess,
  getAccessToken,
}) {
  const [walletAddress, setWalletAddress] = useState('');
  const [tags, setTags] = useState('');
  const [notes, setNotes] = useState('');
  const [alertSettings, setAlertSettings] = useState({
    enabled: true,
    onBuy: true,
    onSell: true,
    minTradeUsd: 100
  });
  const [isAdding, setIsAdding] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState(null);

  const presets = [
    { 
      label: 'Binance Hot Wallet', 
      address: '5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9',
      description: 'High volume exchange wallet'
    },
    { 
      label: 'Jupiter Aggregator', 
      address: 'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4',
      description: 'DEX aggregator protocol'
    },
    { 
      label: 'Raydium AMM', 
      address: '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8',
      description: 'Automated market maker'
    },
    {
      label: 'Phantom Wallet Test',
      address: 'GThUX1Atko4tqhN2NaiTazWSeFWMuiUvfFnyJyUghFMJ',
      description: 'Popular wallet for testing'
    }
  ];

  const handleAdd = async () => {
    if (!walletAddress.trim()) {
      setError('Please enter a wallet address');
      return;
    }

    if (walletAddress.trim().length < 32 || walletAddress.trim().length > 44) {
      setError('Invalid Solana wallet address format');
      return;
    }

    setError(null);
    setIsAdding(true);

    try {
      const token = getAccessToken?.();
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/add`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          user_id: userId,
          wallet: {
            wallet: walletAddress.trim(),
            tier: 'C',
            tags: tags.split(',').map(t => t.trim()).filter(Boolean),
            notes: notes.trim() || null,
            alert_enabled: alertSettings.enabled,
            alert_on_buy: alertSettings.onBuy,
            alert_on_sell: alertSettings.onSell,
            min_trade_usd: alertSettings.minTradeUsd
          }
        })
      });

      const data = await response.json();

      if (data.success) {
        setSuccess(true);
        setTimeout(() => {
          setSuccess(false);
          setWalletAddress('');
          setTags('');
          setNotes('');
          setAlertSettings({ enabled: true, onBuy: true, onSell: true, minTradeUsd: 100 });
          if (onSuccess) onSuccess();
        }, 2000);
      } else {
        setError(data.error || 'Failed to add wallet');
      }
    } catch (err) {
      console.error('Add wallet error:', err);
      setError('Network error. Please try again.');
    } finally {
      setIsAdding(false);
    }
  };

  const applyPreset = (preset) => {
    setWalletAddress(preset.address);
    setTags('stress-test, high-volume');
    setNotes(`Preset: ${preset.label} - ${preset.description}`);
  };

  return (
    <div className="space-y-4">
      {/* Quick Presets */}
      <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Zap className="text-purple-400" size={16} />
          <h3 className="text-sm font-semibold">Quick Presets (Stress Testing)</h3>
        </div>
        
        <p className="text-xs text-gray-400 mb-3">
          Manually Add Wallets To Your Watchlist
        </p>

        <div className="space-y-2">
          {presets.map((preset, idx) => (
            <button
              key={idx}
              onClick={() => applyPreset(preset)}
              className="w-full px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-left text-sm transition group"
            >
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <div className="font-semibold text-purple-400 group-hover:text-purple-300">
                    {preset.label}
                  </div>
                  <div className="text-xs text-gray-500">{preset.description}</div>
                </div>
                <Zap size={14} className="text-purple-400 opacity-50 group-hover:opacity-100" />
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Manual Input */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3">Manual Entry</h3>
        
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium mb-2">
              Wallet Address <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={walletAddress}
              onChange={(e) => setWalletAddress(e.target.value)}
              placeholder="Enter Solana wallet address..."
              className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500 font-mono"
            />
            {error && (
              <div className="flex items-center gap-1 mt-1 text-xs text-red-400">
                <AlertCircle size={12} />
                {error}
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              Tags <span className="text-gray-500 text-xs">(optional)</span>
            </label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="e.g., exchange, high-volume, whale"
              className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
            />
            <p className="text-xs text-gray-500 mt-1">Separate multiple tags with commas</p>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              Notes <span className="text-gray-500 text-xs">(optional)</span>
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Why you're monitoring this wallet..."
              rows={3}
              className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500 resize-none"
            />
          </div>
        </div>
      </div>

      {/* Alert Settings */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          🔔 Alert Settings
        </h3>
        
        <div className="space-y-3">
          <label className="flex items-center justify-between cursor-pointer">
            <span className="text-sm">Enable alerts</span>
            <div 
              onClick={() => setAlertSettings({...alertSettings, enabled: !alertSettings.enabled})}
              className={`relative w-12 h-6 rounded-full transition ${
                alertSettings.enabled ? 'bg-purple-600' : 'bg-gray-600'
              }`}
            >
              <div className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition transform ${
                alertSettings.enabled ? 'translate-x-6' : ''
              }`} />
            </div>
          </label>

          <div className={`space-y-2 ${!alertSettings.enabled ? 'opacity-50' : ''}`}>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={alertSettings.onBuy}
                onChange={(e) => setAlertSettings({...alertSettings, onBuy: e.target.checked})}
                disabled={!alertSettings.enabled}
                className="w-4 h-4 rounded"
              />
              <span className="text-sm">Alert on buys</span>
            </label>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={alertSettings.onSell}
                onChange={(e) => setAlertSettings({...alertSettings, onSell: e.target.checked})}
                disabled={!alertSettings.enabled}
                className="w-4 h-4 rounded"
              />
              <span className="text-sm">Alert on sells</span>
            </label>
          </div>

          <div className={!alertSettings.enabled ? 'opacity-50' : ''}>
            <label className="block text-xs text-gray-400 mb-1">
              Minimum Trade Amount ($)
            </label>
            <input
              type="number"
              value={alertSettings.minTradeUsd}
              onChange={(e) => setAlertSettings({...alertSettings, minTradeUsd: parseInt(e.target.value) || 0})}
              disabled={!alertSettings.enabled}
              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
              min="0"
              step="10"
            />
            <p className="text-xs text-gray-500 mt-1">Only alert for trades above this amount</p>
          </div>
        </div>
      </div>

      {/* Add Button */}
      <button
        onClick={handleAdd}
        disabled={isAdding || success || !walletAddress.trim()}
        className="w-full px-4 py-3 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 disabled:from-purple-600/30 disabled:to-purple-500/30 rounded-lg font-semibold transition flex items-center justify-center gap-2 shadow-lg shadow-purple-500/30"
      >
        {isAdding ? (
          <>
            <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Adding to Watchlist...
          </>
        ) : success ? (
          <>
            <CheckCircle size={18} />
            Added Successfully!
          </>
        ) : (
          <>
            <Plus size={18} />
            Add to Watchlist
          </>
        )}
      </button>

      {/* Info Banner */}
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3">
        <p className="text-xs text-blue-300">
          💡 <strong>Monitoring begins within 2 minutes.</strong> You'll receive Telegram alerts based on your settings. High-volume wallets may generate many alerts — adjust thresholds accordingly.
        </p>
      </div>

      {/* How It Works */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-4">
        <h4 className="text-sm font-semibold mb-2">How It Works</h4>
        <ol className="space-y-2 text-xs text-gray-400">
          <li className="flex gap-2">
            <span className="text-purple-400 font-bold">1.</span>
            <span>Wallet is added to your watchlist immediately</span>
          </li>
          <li className="flex gap-2">
            <span className="text-purple-400 font-bold">2.</span>
            <span>Background monitoring starts within 2 minutes</span>
          </li>
          <li className="flex gap-2">
            <span className="text-purple-400 font-bold">3.</span>
            <span>All transactions are tracked in real-time</span>
          </li>
          <li className="flex gap-2">
            <span className="text-purple-400 font-bold">4.</span>
            <span>Telegram alerts sent based on your settings</span>
          </li>
        </ol>
      </div>

      {/* Stress Test Warning */}
      <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3">
        <p className="text-xs text-yellow-300">
          ⚠️ <strong>Warning:</strong> High Volume Wallets may generate hundreds of alerts per hour. Use these with Caution
        </p>
      </div>
    </div>
  );
}