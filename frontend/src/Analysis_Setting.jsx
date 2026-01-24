import React, { useState, useEffect } from 'react';
import { Settings, ChevronDown, ChevronUp, Clock, TrendingUp, Search } from 'lucide-react';

export default function AnalysisSettings({ selectedTokens, onSettingsChange }) {
  const [settingsMode, setSettingsMode] = useState('global'); // 'global' or 'per-token'
  const [globalSettings, setGlobalSettings] = useState({
    analysisTimeframe: 'first_7d',
    pumpTimeframe: '5m',
    tweetWindow: { minus: 35, plus: 10 }
  });
  const [perTokenSettings, setPerTokenSettings] = useState({});
  const [expandedTokens, setExpandedTokens] = useState({});

  // Timeframe options
  const analysisTimeframes = [
    { value: 'first_5m', label: 'First 5 Minutes After Launch', type: 'launch' },
    { value: 'first_24h', label: 'First 24 Hours After Launch', type: 'launch' },
    { value: 'first_7d', label: 'First 7 Days After Launch', type: 'launch' },
    { value: 'first_30d', label: 'First 30 Days After Launch', type: 'launch' },
    { value: 'last_1h', label: 'Last 1 Hour', type: 'relative' },
    { value: 'last_5h', label: 'Last 5 Hours', type: 'relative' },
    { value: 'last_24h', label: 'Last 24 Hours', type: 'relative' },
    { value: 'last_3d', label: 'Last 3 Days', type: 'relative' },
    { value: 'last_7d', label: 'Last 7 Days', type: 'relative' },
    { value: 'last_30d', label: 'Last 30 Days', type: 'relative' },
    { value: 'all', label: 'All Time', type: 'relative' }
  ];

  const pumpTimeframes = [
    { value: '1m', label: 'M1 (1 Minute Candles)' },
    { value: '5m', label: 'M5 (5 Minute Candles)' },
    { value: '15m', label: 'M15 (15 Minute Candles)' },
    { value: '1h', label: '1H (1 Hour Candles)' },
    { value: '4h', label: '4H (4 Hour Candles)' },
    { value: '1d', label: '1D (Daily Candles)' }
  ];

  // Initialize per-token settings when tokens change
  useEffect(() => {
    const newPerTokenSettings = {};
    selectedTokens.forEach(token => {
      if (!perTokenSettings[token.address]) {
        newPerTokenSettings[token.address] = {
          analysisTimeframe: globalSettings.analysisTimeframe,
          pumpTimeframe: globalSettings.pumpTimeframe,
          tweetWindow: { ...globalSettings.tweetWindow }
        };
      } else {
        newPerTokenSettings[token.address] = perTokenSettings[token.address];
      }
    });
    setPerTokenSettings(newPerTokenSettings);
  }, [selectedTokens]);

  // Notify parent of settings changes
  useEffect(() => {
    if (onSettingsChange) {
      onSettingsChange({
        mode: settingsMode,
        globalSettings: globalSettings,
        perTokenSettings: perTokenSettings
      });
    }
  }, [settingsMode, globalSettings, perTokenSettings]);

  const updateGlobalSettings = (field, value) => {
    setGlobalSettings(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const updateGlobalTweetWindow = (field, value) => {
    setGlobalSettings(prev => ({
      ...prev,
      tweetWindow: {
        ...prev.tweetWindow,
        [field]: parseInt(value) || 0
      }
    }));
  };

  const updatePerTokenSettings = (tokenAddress, field, value) => {
    setPerTokenSettings(prev => ({
      ...prev,
      [tokenAddress]: {
        ...prev[tokenAddress],
        [field]: value
      }
    }));
  };

  const updatePerTokenTweetWindow = (tokenAddress, field, value) => {
    setPerTokenSettings(prev => ({
      ...prev,
      [tokenAddress]: {
        ...prev[tokenAddress],
        tweetWindow: {
          ...prev[tokenAddress].tweetWindow,
          [field]: parseInt(value) || 0
        }
      }
    }));
  };

  const toggleTokenExpanded = (address) => {
    setExpandedTokens(prev => ({
      ...prev,
      [address]: !prev[address]
    }));
  };

  const applyGlobalToAll = () => {
    const updated = {};
    selectedTokens.forEach(token => {
      updated[token.address] = {
        analysisTimeframe: globalSettings.analysisTimeframe,
        pumpTimeframe: globalSettings.pumpTimeframe,
        tweetWindow: { ...globalSettings.tweetWindow }
      };
    });
    setPerTokenSettings(updated);
  };

  if (selectedTokens.length === 0) {
    return (
      <div className="bg-white/5 border border-white/10 rounded-lg p-6 text-center">
        <Settings className="mx-auto mb-3 text-gray-400" size={48} />
        <p className="text-gray-400">Select tokens to configure analysis settings</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Mode Toggle */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-4">
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-400">Settings Mode:</span>
          
          <button
            onClick={() => setSettingsMode('global')}
            className={`px-4 py-2 rounded-lg font-semibold transition ${
              settingsMode === 'global'
                ? 'bg-purple-600 text-white'
                : 'bg-white/5 text-gray-400 hover:bg-white/10'
            }`}
          >
            Global (Quick Mode)
          </button>
          
          <button
            onClick={() => setSettingsMode('per-token')}
            className={`px-4 py-2 rounded-lg font-semibold transition ${
              settingsMode === 'per-token'
                ? 'bg-purple-600 text-white'
                : 'bg-white/5 text-gray-400 hover:bg-white/10'
            }`}
          >
            Per-Token Customization
          </button>
        </div>
      </div>

      {/* Global Settings */}
      {settingsMode === 'global' && (
        <div className="bg-white/5 border border-white/10 rounded-lg p-6">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Settings className="text-purple-400" size={20} />
            Global Settings (Apply to all {selectedTokens.length} tokens)
          </h3>

          <div className="space-y-6">
            {/* Analysis Timeframe */}
            <div>
              <label className="flex items-center gap-2 text-sm font-medium mb-2 text-gray-300">
                <Clock size={16} />
                1️⃣ Analysis Timeframe (Historical Scope)
              </label>
              <select
                value={globalSettings.analysisTimeframe}
                onChange={(e) => updateGlobalSettings('analysisTimeframe', e.target.value)}
                className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500"
              >
                <optgroup label="Launch-Anchored Windows">
                  {analysisTimeframes.filter(t => t.type === 'launch').map(option => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="Relative Windows (from now)">
                  {analysisTimeframes.filter(t => t.type === 'relative').map(option => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </optgroup>
              </select>
              <p className="text-xs text-gray-500 mt-1">
                📊 This determines the time period to analyze for price movements
              </p>
            </div>

            {/* Pump Detection Timeframe */}
            <div>
              <label className="flex items-center gap-2 text-sm font-medium mb-2 text-gray-300">
                <TrendingUp size={16} />
                2️⃣ Pump Detection Timeframe (Candle Size)
              </label>
              <select
                value={globalSettings.pumpTimeframe}
                onChange={(e) => updateGlobalSettings('pumpTimeframe', e.target.value)}
                className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500"
              >
                {pumpTimeframes.map(option => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">
                📈 Smaller candles = more precise pump detection, larger = broader trends
              </p>
            </div>

            {/* Tweet Search Window */}
            <div>
              <label className="flex items-center gap-2 text-sm font-medium mb-2 text-gray-300">
                <Search size={16} />
                3️⃣ Tweet Search Window
              </label>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">T-minus (minutes before)</label>
                  <input
                    type="number"
                    value={globalSettings.tweetWindow.minus}
                    onChange={(e) => updateGlobalTweetWindow('minus', e.target.value)}
                    min="0"
                    max="120"
                    className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-2 focus:outline-none focus:border-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">T-plus (minutes after)</label>
                  <input
                    type="number"
                    value={globalSettings.tweetWindow.plus}
                    onChange={(e) => updateGlobalTweetWindow('plus', e.target.value)}
                    min="0"
                    max="60"
                    className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-2 focus:outline-none focus:border-purple-500"
                  />
                </div>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                🐦 Search for tweets T-{globalSettings.tweetWindow.minus} to T+{globalSettings.tweetWindow.plus} around each pump
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Per-Token Settings */}
      {settingsMode === 'per-token' && (
        <div className="space-y-3">
          <div className="flex justify-between items-center mb-2">
            <h3 className="text-lg font-semibold">Customize Each Token</h3>
            <button
              onClick={applyGlobalToAll}
              className="text-sm px-3 py-1 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 rounded text-purple-400"
            >
              Apply Global Settings to All
            </button>
          </div>

          {selectedTokens.map((token, index) => {
            const settings = perTokenSettings[token.address] || globalSettings;
            const isExpanded = expandedTokens[token.address];

            return (
              <div
                key={token.address}
                className="bg-white/5 border border-white/10 rounded-lg overflow-hidden"
              >
                {/* Token Header */}
                <button
                  onClick={() => toggleTokenExpanded(token.address)}
                  className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/5 transition"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-lg font-bold text-purple-400">#{index + 1}</span>
                    <div className="text-left">
                      <div className="font-semibold">{token.ticker}</div>
                      <div className="text-xs text-gray-400">{token.name}</div>
                    </div>
                    <span className="text-xs px-2 py-1 bg-white/10 rounded">
                      {token.chain.toUpperCase()}
                    </span>
                  </div>
                  {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                </button>

                {/* Token Settings (Expanded) */}
                {isExpanded && (
                  <div className="px-6 pb-6 space-y-4 border-t border-white/10 pt-4">
                    {/* Analysis Timeframe */}
                    <div>
                      <label className="block text-sm font-medium mb-2 text-gray-300">
                        Analysis Timeframe
                      </label>
                      <select
                        value={settings.analysisTimeframe}
                        onChange={(e) => updatePerTokenSettings(token.address, 'analysisTimeframe', e.target.value)}
                        className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-2 focus:outline-none focus:border-purple-500 text-sm"
                      >
                        <optgroup label="Launch-Anchored">
                          {analysisTimeframes.filter(t => t.type === 'launch').map(option => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </optgroup>
                        <optgroup label="Relative">
                          {analysisTimeframes.filter(t => t.type === 'relative').map(option => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </optgroup>
                      </select>
                    </div>

                    {/* Pump Detection */}
                    <div>
                      <label className="block text-sm font-medium mb-2 text-gray-300">
                        Candle Size
                      </label>
                      <select
                        value={settings.pumpTimeframe}
                        onChange={(e) => updatePerTokenSettings(token.address, 'pumpTimeframe', e.target.value)}
                        className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-2 focus:outline-none focus:border-purple-500 text-sm"
                      >
                        {pumpTimeframes.map(option => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Tweet Window */}
                    <div>
                      <label className="block text-sm font-medium mb-2 text-gray-300">
                        Tweet Search Window
                      </label>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="block text-xs text-gray-400 mb-1">T-minus</label>
                          <input
                            type="number"
                            value={settings.tweetWindow.minus}
                            onChange={(e) => updatePerTokenTweetWindow(token.address, 'minus', e.target.value)}
                            min="0"
                            max="120"
                            className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-gray-400 mb-1">T-plus</label>
                          <input
                            type="number"
                            value={settings.tweetWindow.plus}
                            onChange={(e) => updatePerTokenTweetWindow(token.address, 'plus', e.target.value)}
                            min="0"
                            max="60"
                            className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Settings Summary */}
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
        <div className="flex items-start gap-3">
          <div className="text-blue-400 mt-1">ℹ️</div>
          <div className="flex-1 text-sm text-gray-300">
            <p className="font-semibold mb-1">What do these settings mean?</p>
            <ul className="space-y-1 text-xs text-gray-400">
              <li><strong>Analysis Timeframe:</strong> How far back in time to look for pumps</li>
              <li><strong>Candle Size:</strong> The granularity of price data (smaller = more precise)</li>
              <li><strong>Tweet Window:</strong> How many minutes before/after each pump to search for tweets</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}