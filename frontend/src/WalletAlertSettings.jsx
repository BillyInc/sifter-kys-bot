import React, { useState, useEffect } from 'react';
import { Settings, Bell, BellOff, DollarSign, TrendingUp, TrendingDown, Save, X } from 'lucide-react';
import walletActivityService from './WalletActivityService';

export default function WalletAlertSettings({ walletAddress, onClose, onSave }) {
  const [settings, setSettings] = useState({
    alert_enabled: true,
    alert_on_buy: true,
    alert_on_sell: false,
    min_trade_usd: 100
  });
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Close on ESC key
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape' && !isSaving && onClose) {
        onClose();
      }
    };
    
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isSaving, onClose]);

  const presetValues = [
    { label: 'Any Amount', value: 0 },
    { label: '$100+', value: 100 },
    { label: '$250+', value: 250 },
    { label: '$500+', value: 500 },
    { label: '$1,000+', value: 1000 },
    { label: '$5,000+', value: 5000 },
  ];

  // Close on ESC key
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape' && !isSaving) {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [onClose, isSaving]);

  const handleSave = async () => {
    setIsSaving(true);
    setSaveSuccess(false);

    try {
      const success = await walletActivityService.updateAlertSettings(
        walletAddress,
        settings
      );

      if (success) {
        setSaveSuccess(true);
        setTimeout(() => {
          if (onSave) onSave(settings);
          if (onClose) onClose();
        }, 1000);
      } else {
        alert('Failed to save alert settings');
      }
    } catch (error) {
      console.error('Error saving settings:', error);
      alert('Error saving settings');
    }

    setIsSaving(false);
  };

  return (
    <div 
      className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in"
      onClick={(e) => {
        // Close when clicking the backdrop (outer div), not the modal
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div 
        className="bg-gradient-to-br from-gray-900 to-gray-950 border border-white/10 rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden animate-scale-in"
        onClick={(e) => e.stopPropagation()} // Prevent closing when clicking inside modal
      >
        {/* Header */}
        <div className="bg-gradient-to-r from-purple-900/50 to-purple-800/30 border-b border-white/10 p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-bold flex items-center gap-3">
              <Settings className="text-purple-400" size={24} />
              Alert Settings
            </h2>
            <button
              onClick={onClose}
              className="p-2 hover:bg-white/10 rounded-lg transition"
              title="Close (ESC)"
            >
              <X size={20} />
            </button>
          </div>

          <div className="mt-2 text-sm text-gray-400 font-mono">
            {walletAddress?.slice(0, 12)}...{walletAddress?.slice(-8)}
          </div>
          
          <div className="mt-2 text-xs text-gray-500">
            Click outside or press ESC to close
          </div>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Master Toggle */}
          <div className="bg-white/5 border border-white/10 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {settings.alert_enabled ? (
                  <Bell className="text-purple-400" size={20} />
                ) : (
                  <BellOff className="text-gray-400" size={20} />
                )}
                <div>
                  <h3 className="font-semibold">Enable Alerts</h3>
                  <p className="text-xs text-gray-400">
                    Get notified when this wallet trades
                  </p>
                </div>
              </div>

              <button
                onClick={() => setSettings({ ...settings, alert_enabled: !settings.alert_enabled })}
                className={`relative w-14 h-7 rounded-full transition ${
                  settings.alert_enabled ? 'bg-purple-600' : 'bg-gray-600'
                }`}
              >
                <div className={`absolute top-1 left-1 w-5 h-5 bg-white rounded-full transition transform ${
                  settings.alert_enabled ? 'translate-x-7' : ''
                }`} />
              </button>
            </div>
          </div>

          {/* Alert Types */}
          <div className="space-y-3">
            <h3 className="font-semibold text-sm text-gray-300">Notify me when this wallet:</h3>

            <div className="space-y-2">
              <label className={`flex items-center gap-3 p-4 border rounded-xl cursor-pointer transition ${
                settings.alert_on_buy
                  ? 'bg-green-500/10 border-green-500/30'
                  : 'bg-white/5 border-white/10 hover:border-white/20'
              }`}>
                <input
                  type="checkbox"
                  checked={settings.alert_on_buy}
                  onChange={(e) => setSettings({ ...settings, alert_on_buy: e.target.checked })}
                  disabled={!settings.alert_enabled}
                  className="w-5 h-5"
                />
                <TrendingUp className={settings.alert_on_buy ? 'text-green-400' : 'text-gray-400'} size={20} />
                <div className="flex-1">
                  <span className="font-semibold">Buys a token</span>
                  <p className="text-xs text-gray-400">Alert when wallet purchases</p>
                </div>
              </label>

              <label className={`flex items-center gap-3 p-4 border rounded-xl cursor-pointer transition ${
                settings.alert_on_sell
                  ? 'bg-red-500/10 border-red-500/30'
                  : 'bg-white/5 border-white/10 hover:border-white/20'
              }`}>
                <input
                  type="checkbox"
                  checked={settings.alert_on_sell}
                  onChange={(e) => setSettings({ ...settings, alert_on_sell: e.target.checked })}
                  disabled={!settings.alert_enabled}
                  className="w-5 h-5"
                />
                <TrendingDown className={settings.alert_on_sell ? 'text-red-400' : 'text-gray-400'} size={20} />
                <div className="flex-1">
                  <span className="font-semibold">Sells a token</span>
                  <p className="text-xs text-gray-400">Alert when wallet sells</p>
                </div>
              </label>
            </div>
          </div>

          {/* Minimum Trade Value */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <DollarSign className="text-purple-400" size={18} />
              <h3 className="font-semibold text-sm text-gray-300">
                Minimum Trade Value
              </h3>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {presetValues.map((preset) => (
                <button
                  key={preset.value}
                  onClick={() => setSettings({ ...settings, min_trade_usd: preset.value })}
                  disabled={!settings.alert_enabled}
                  className={`px-3 py-2 rounded-lg text-sm font-semibold transition ${
                    settings.min_trade_usd === preset.value
                      ? 'bg-purple-600 text-white'
                      : 'bg-white/5 text-gray-400 hover:bg-white/10 disabled:opacity-50'
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-400">Custom:</span>
              <div className="relative flex-1">
                <span className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400">
                  $
                </span>
                <input
                  type="number"
                  value={settings.min_trade_usd}
                  onChange={(e) => setSettings({ ...settings, min_trade_usd: Math.max(0, parseInt(e.target.value) || 0) })}
                  disabled={!settings.alert_enabled}
                  className="w-full bg-black/50 border border-white/10 rounded-lg pl-7 pr-3 py-2 text-sm focus:outline-none focus:border-purple-500 disabled:opacity-50"
                  placeholder="Enter amount"
                />
              </div>
            </div>
          </div>

          {/* Preview */}
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-4">
            <p className="text-xs text-gray-400 mb-1">Alert Preview:</p>
            <p className="text-sm">
              {!settings.alert_enabled ? (
                <span className="text-gray-400">Alerts disabled for this wallet</span>
              ) : !settings.alert_on_buy && !settings.alert_on_sell ? (
                <span className="text-gray-400">
                  Please select at least one trade type (buy or sell)
                </span>
              ) : (
                <>
                  You'll be notified when{' '}
                  <span className="font-mono text-purple-300">
                    {walletAddress?.slice(0, 8)}...
                  </span>
                  {' '}
                  {settings.alert_on_buy && settings.alert_on_sell ? (
                    <>
                      <span className="text-white font-semibold">buys or sells</span>
                      {' tokens'}
                    </>
                  ) : settings.alert_on_buy ? (
                    <>
                      <span className="text-green-400 font-semibold">buys</span>
                      {' a token'}
                    </>
                  ) : (
                    <>
                      <span className="text-red-400 font-semibold">sells</span>
                      {' a token'}
                    </>
                  )}
                  {settings.min_trade_usd > 0 ? (
                    <>
                      {' worth '}
                      <span className="text-yellow-400 font-bold">
                        ${settings.min_trade_usd.toLocaleString()}+
                      </span>
                    </>
                  ) : (
                    <span className="text-gray-300"> of any amount</span>
                  )}
                </>
              )}
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="bg-white/5 border-t border-white/10 p-4 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg font-semibold transition"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving || saveSuccess}
            className="flex-1 px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/50 rounded-lg font-semibold transition flex items-center justify-center gap-2"
          >
            {isSaving ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Saving...
              </>
            ) : saveSuccess ? (
              <>
                <Save size={18} />
                Saved!
              </>
            ) : (
              <>
                <Save size={18} />
                Save Settings
              </>
            )}
          </button>
        </div>
      </div>

      <style jsx>{`
        @keyframes fade-in {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        @keyframes scale-in {
          from {
            opacity: 0;
            transform: scale(0.95);
          }
          to {
            opacity: 1;
            transform: scale(1);
          }
        }

        .animate-fade-in {
          animation: fade-in 0.2s ease-out;
        }

        .animate-scale-in {
          animation: scale-in 0.3s ease-out;
        }
      `}</style>
    </div>
  );
}