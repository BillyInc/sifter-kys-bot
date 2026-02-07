import React, { useState, useEffect } from 'react';
import { Settings, Target, Zap, Award, TrendingUp, Info, ChevronDown, ChevronUp } from 'lucide-react';

export default function AnalysisSettings({ 
  selectedTokens, 
  onSettingsChange,
  analysisType // 'general' or 'pump_window'
}) {
  // ========== STATE ==========
  const [settingsMode, setSettingsMode] = useState('global');
  
  // GENERAL MODE: Only ROI multiplier matters
  const [globalSettings, setGlobalSettings] = useState({
    minRoiMultiplier: 3.0,
    // Pump window settings (only used if analysisType === 'pump_window')
    daysBack: 7,
    candleSize: '5m',
    tweetWindow: { minus: 35, plus: 10 }
  });
  
  const [perTokenSettings, setPerTokenSettings] = useState({});
  const [expandedTokens, setExpandedTokens] = useState({});
  const [showInfoPanel, setShowInfoPanel] = useState(true);

  // ========== PRESETS ==========
  const roiPresets = [
    { value: 3, label: '3x', color: 'from-green-600 to-green-500', shadow: 'shadow-green-500/30' },
    { value: 5, label: '5x', color: 'from-blue-600 to-blue-500', shadow: 'shadow-blue-500/30' },
    { value: 10, label: '10x', color: 'from-purple-600 to-purple-500', shadow: 'shadow-purple-500/30' },
    { value: 20, label: '20x', color: 'from-pink-600 to-pink-500', shadow: 'shadow-pink-500/30' }
  ];

  const candleSizes = [
    { value: '1m', label: '1 Minute' },
    { value: '5m', label: '5 Minutes' },
    { value: '15m', label: '15 Minutes' },
    { value: '1h', label: '1 Hour' },
    { value: '4h', label: '4 Hours' },
    { value: '1d', label: '1 Day' }
  ];

  // ========== EFFECTS ==========
  useEffect(() => {
    const newPerTokenSettings = {};
    selectedTokens.forEach(token => {
      if (!perTokenSettings[token.address]) {
        newPerTokenSettings[token.address] = { ...globalSettings };
      } else {
        newPerTokenSettings[token.address] = perTokenSettings[token.address];
      }
    });
    setPerTokenSettings(newPerTokenSettings);
  }, [selectedTokens]);

  useEffect(() => {
    if (onSettingsChange) {
      onSettingsChange({
        mode: settingsMode,
        globalSettings: globalSettings,
        perTokenSettings: perTokenSettings
      });
    }
  }, [settingsMode, globalSettings, perTokenSettings]);

  // ========== HANDLERS ==========
  const updateGlobalSettings = (field, value) => {
    setGlobalSettings(prev => ({ ...prev, [field]: value }));
  };

  const updateGlobalTweetWindow = (field, value) => {
    setGlobalSettings(prev => ({
      ...prev,
      tweetWindow: { ...prev.tweetWindow, [field]: parseInt(value) || 0 }
    }));
  };

  const updatePerTokenSettings = (tokenAddress, field, value) => {
    setPerTokenSettings(prev => ({
      ...prev,
      [tokenAddress]: { ...prev[tokenAddress], [field]: value }
    }));
  };

  const updatePerTokenTweetWindow = (tokenAddress, field, value) => {
    setPerTokenSettings(prev => ({
      ...prev,
      [tokenAddress]: {
        ...prev[tokenAddress],
        tweetWindow: { ...prev[tokenAddress].tweetWindow, [field]: parseInt(value) || 0 }
      }
    }));
  };

  const toggleTokenExpanded = (address) => {
    setExpandedTokens(prev => ({ ...prev, [address]: !prev[address] }));
  };

  const applyGlobalToAll = () => {
    const updated = {};
    selectedTokens.forEach(token => {
      updated[token.address] = { ...globalSettings };
    });
    setPerTokenSettings(updated);
  };

  // ========== EMPTY STATE ==========
  if (selectedTokens.length === 0) {
    return (
      <div className="bg-white/5 border border-white/10 rounded-lg p-6 text-center">
        <Settings className="mx-auto mb-3 text-gray-400" size={48} />
        <p className="text-gray-400">Select tokens to configure analysis settings</p>
      </div>
    );
  }

  // ========== GENERAL MODE UI ==========
  if (analysisType === 'general') {
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

        {/* Global Settings - GENERAL MODE */}
        {settingsMode === 'global' && (
          <div className="space-y-4">
            {/* Main Settings Card */}
            <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-6">
              <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Target className="text-purple-400" size={20} />
                Minimum ROI Multiplier
              </h3>

              {/* Preset Buttons */}
              <div className="grid grid-cols-4 gap-3 mb-6">
                {roiPresets.map(preset => (
                  <button
                    key={preset.value}
                    onClick={() => updateGlobalSettings('minRoiMultiplier', preset.value)}
                    className={`relative px-6 py-4 rounded-xl font-bold text-lg transition-all duration-300 ${
                      globalSettings.minRoiMultiplier === preset.value
                        ? `bg-gradient-to-r ${preset.color} text-white shadow-lg ${preset.shadow} scale-105`
                        : 'bg-white/5 text-gray-400 hover:bg-white/10 hover:scale-102'
                    }`}
                  >
                    {preset.label}
                    {globalSettings.minRoiMultiplier === preset.value && (
                      <div className="absolute -top-2 -right-2 w-6 h-6 bg-white rounded-full flex items-center justify-center">
                        <Zap className="text-purple-600" size={14} />
                      </div>
                    )}
                  </button>
                ))}
              </div>

              {/* Custom Slider */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <label className="text-sm font-medium text-gray-300">
                    Custom ROI Threshold
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      value={globalSettings.minRoiMultiplier}
                      onChange={(e) => updateGlobalSettings('minRoiMultiplier', parseFloat(e.target.value) || 1)}
                      min="1"
                      max="50"
                      step="0.5"
                      className="w-20 bg-black/50 border border-white/10 rounded-lg px-3 py-1 text-sm text-center focus:outline-none focus:border-purple-500"
                    />
                    <span className="text-sm text-gray-400">x</span>
                  </div>
                </div>

                <input
                  type="range"
                  value={globalSettings.minRoiMultiplier}
                  onChange={(e) => updateGlobalSettings('minRoiMultiplier', parseFloat(e.target.value))}
                  min="1"
                  max="50"
                  step="0.5"
                  className="w-full h-2 bg-white/10 rounded-lg appearance-none cursor-pointer slider-thumb"
                  style={{
                    background: `linear-gradient(to right, rgb(168, 85, 247) 0%, rgb(168, 85, 247) ${((globalSettings.minRoiMultiplier - 1) / 49) * 100}%, rgba(255,255,255,0.1) ${((globalSettings.minRoiMultiplier - 1) / 49) * 100}%, rgba(255,255,255,0.1) 100%)`
                  }}
                />

                <div className="flex justify-between text-xs text-gray-500 mt-2">
                  <span>1x (Low bar)</span>
                  <span>25x (Sweet spot)</span>
                  <span>50x (Moon only)</span>
                </div>
              </div>

              <div className="mt-4 p-3 bg-purple-500/10 border border-purple-500/20 rounded-lg">
                <p className="text-sm text-gray-300">
                  <span className="font-semibold text-purple-400">
                    Current: {globalSettings.minRoiMultiplier}x minimum ROI
                  </span>
                  <br />
                  <span className="text-xs text-gray-400">
                    Only wallets with {globalSettings.minRoiMultiplier}x+ realized ROI will be included
                  </span>
                </p>
              </div>
            </div>

            {/* Fixed Criteria Info Panel */}
            <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
              <button
                onClick={() => setShowInfoPanel(!showInfoPanel)}
                className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/5 transition"
              >
                <div className="flex items-center gap-2">
                  <Info className="text-blue-400" size={18} />
                  <span className="font-semibold">Fixed Analysis Criteria</span>
                </div>
                {showInfoPanel ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
              </button>

              {showInfoPanel && (
                <div className="px-6 pb-6 border-t border-white/10 pt-4 space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-black/30 rounded-lg p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <Award className="text-yellow-400" size={16} />
                        <span className="text-sm font-semibold">Min Investment</span>
                      </div>
                      <div className="text-2xl font-bold text-green-400">$100</div>
                      <p className="text-xs text-gray-400 mt-1">Only wallets with $100+ invested</p>
                    </div>

                    <div className="bg-black/30 rounded-lg p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <Zap className="text-purple-400" size={16} />
                        <span className="text-sm font-semibold">Analysis Method</span>
                      </div>
                      <div className="text-2xl font-bold text-purple-400">6-Step</div>
                      <p className="text-xs text-gray-400 mt-1">Professional trader-based analysis</p>
                    </div>
                  </div>

                  <div className="bg-gradient-to-r from-blue-900/20 to-blue-800/10 border border-blue-500/20 rounded-lg p-4">
                    <div className="flex items-start gap-3">
                      <TrendingUp className="text-blue-400 mt-0.5" size={18} />
                      <div className="flex-1">
                        <p className="text-sm font-semibold text-blue-400 mb-2">What You'll Discover:</p>
                        <ul className="space-y-1 text-xs text-gray-300">
                          <li>✓ Professional Score (60% timing, 30% profit, 10% overall)</li>
                          <li>✓ Entry-to-ATH multipliers (how early they bought)</li>
                          <li>✓ 30-day runner history (other 5x+ tokens they traded)</li>
                          <li>✓ Consistency grades (A+ to F based on variance)</li>
                          <li>✓ Realized vs unrealized profits</li>
                        </ul>
                      </div>
                    </div>
                  </div>

                  <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3">
                    <div className="flex items-start gap-2">
                      <div className="text-yellow-400 mt-0.5">💡</div>
                      <div className="flex-1 text-xs text-gray-300">
                        <p className="font-semibold mb-1">Pro Tip:</p>
                        <p>Start with 3x to see more wallets, increase to 10x+ for only the top performers. 
                        The analysis automatically finds ALL historical traders regardless of timeframe.</p>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Per-Token Settings - GENERAL MODE */}
        {settingsMode === 'per-token' && (
          <div className="space-y-3">
            <div className="flex justify-between items-center mb-2">
              <h3 className="text-lg font-semibold">Customize ROI Threshold Per Token</h3>
              <button
                onClick={applyGlobalToAll}
                className="text-sm px-3 py-1 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 rounded text-purple-400"
              >
                Apply Global to All
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
                      <span className="text-xs px-2 py-1 bg-purple-500/20 text-purple-400 rounded font-semibold">
                        {settings.minRoiMultiplier}x ROI
                      </span>
                    </div>
                    {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                  </button>

                  {isExpanded && (
                    <div className="px-6 pb-6 border-t border-white/10 pt-4">
                      <label className="block text-sm font-medium mb-3 text-gray-300">
                        Minimum ROI Multiplier
                      </label>

                      <div className="grid grid-cols-4 gap-2 mb-4">
                        {roiPresets.map(preset => (
                          <button
                            key={preset.value}
                            onClick={() => updatePerTokenSettings(token.address, 'minRoiMultiplier', preset.value)}
                            className={`px-4 py-2 rounded-lg font-bold text-sm transition ${
                              settings.minRoiMultiplier === preset.value
                                ? `bg-gradient-to-r ${preset.color} text-white`
                                : 'bg-white/5 text-gray-400 hover:bg-white/10'
                            }`}
                          >
                            {preset.label}
                          </button>
                        ))}
                      </div>

                      <input
                        type="range"
                        value={settings.minRoiMultiplier}
                        onChange={(e) => updatePerTokenSettings(token.address, 'minRoiMultiplier', parseFloat(e.target.value))}
                        min="1"
                        max="50"
                        step="0.5"
                        className="w-full h-2 bg-white/10 rounded-lg appearance-none cursor-pointer mb-2"
                      />
                      
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-gray-400">Custom:</span>
                        <input
                          type="number"
                          value={settings.minRoiMultiplier}
                          onChange={(e) => updatePerTokenSettings(token.address, 'minRoiMultiplier', parseFloat(e.target.value) || 1)}
                          min="1"
                          max="50"
                          step="0.5"
                          className="w-20 bg-black/50 border border-white/10 rounded px-2 py-1 text-center focus:outline-none focus:border-purple-500"
                        />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  // ========== PUMP WINDOW MODE UI (Original Settings) ==========
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

      {/* Global Settings - PUMP WINDOW MODE */}
      {settingsMode === 'global' && (
        <div className="bg-white/5 border border-white/10 rounded-lg p-6">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Settings className="text-purple-400" size={20} />
            Global Settings (Apply to all {selectedTokens.length} tokens)
          </h3>

          <div className="space-y-6">
            {/* Days Back */}
            <div>
              <label className="flex items-center gap-2 text-sm font-medium mb-2 text-gray-300">
                Days Back (Historical Data)
              </label>
              <input
                type="number"
                value={globalSettings.daysBack}
                onChange={(e) => updateGlobalSettings('daysBack', Math.max(1, Math.min(90, parseInt(e.target.value) || 7)))}
                min="1"
                max="90"
                className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500"
              />
              <p className="text-xs text-gray-500 mt-1">
                Analyze the last {globalSettings.daysBack} days of price data (1-90 days)
              </p>
            </div>

            {/* Candle Size */}
            <div>
              <label className="text-sm font-medium mb-2 text-gray-300 block">
                Candle Size
              </label>
              <select
                value={globalSettings.candleSize}
                onChange={(e) => updateGlobalSettings('candleSize', e.target.value)}
                className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500"
              >
                {candleSizes.map(option => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Tweet Window */}
            <div>
              <label className="text-sm font-medium mb-2 text-gray-300 block">
                Tweet Search Window
              </label>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">T-minus (minutes)</label>
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
                  <label className="block text-xs text-gray-400 mb-1">T-plus (minutes)</label>
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
            </div>
          </div>
        </div>
      )}

      {/* Per-Token Settings - PUMP WINDOW MODE */}
      {settingsMode === 'per-token' && (
        <div className="space-y-3">
          <div className="flex justify-between items-center mb-2">
            <h3 className="text-lg font-semibold">Customize Each Token</h3>
            <button
              onClick={applyGlobalToAll}
              className="text-sm px-3 py-1 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 rounded text-purple-400"
            >
              Apply Global to All
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
                  </div>
                  {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                </button>

                {isExpanded && (
                  <div className="px-6 pb-6 space-y-4 border-t border-white/10 pt-4">
                    {/* Days Back, Candle Size, Tweet Window - same as original */}
                    <div>
                      <label className="block text-sm font-medium mb-2 text-gray-300">Days Back</label>
                      <input
                        type="number"
                        value={settings.daysBack}
                        onChange={(e) => updatePerTokenSettings(token.address, 'daysBack', Math.max(1, Math.min(90, parseInt(e.target.value) || 7)))}
                        min="1"
                        max="90"
                        className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-purple-500"
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium mb-2 text-gray-300">Candle Size</label>
                      <select
                        value={settings.candleSize}
                        onChange={(e) => updatePerTokenSettings(token.address, 'candleSize', e.target.value)}
                        className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-purple-500"
                      >
                        {candleSizes.map(option => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium mb-2 text-gray-300">Tweet Window</label>
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
    </div>
  );
}