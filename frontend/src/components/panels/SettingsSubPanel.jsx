import React, { useState } from 'react';
import { User, Bell, BarChart3, Palette, Save } from 'lucide-react';

export default function SettingsSubPanel({ userId, apiUrl, onBack }) {
  const [activeSettingsTab, setActiveSettingsTab] = useState('account');
  const [settings, setSettings] = useState({
    // Account
    email: '',
    timezone: 'UTC-5',
    language: 'English',
    
    // Alerts
    emailAlerts: true,
    browserNotifications: true,
    alertThreshold: 100,
    
    // Analysis
    defaultTimeframe: '7d',
    defaultCandle: '5m',
    minRoiMultiplier: 3.0,
    
    // Display
    theme: 'dark',
    compactMode: false,
    dataRefreshRate: 30
  });
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const response = await fetch(`${apiUrl}/api/user/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, settings })
      });
      
      const data = await response.json();
      if (data.success) {
        alert('✅ Settings saved!');
      }
    } catch (error) {
      console.error('Save error:', error);
    }
    setIsSaving(false);
  };

  return (
    <div className="space-y-4">
      {/* Back Button */}
      <button
        onClick={onBack}
        className="flex items-center gap-2 text-sm text-purple-400 hover:text-purple-300 transition"
      >
        ← Back to Profile
      </button>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-white/10">
        {[
          { id: 'account', icon: User, label: 'Account' },
          { id: 'alerts', icon: Bell, label: 'Alerts' },
          { id: 'analysis', icon: BarChart3, label: 'Analysis' },
          { id: 'display', icon: Palette, label: 'Display' }
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveSettingsTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 border-b-2 transition text-sm ${
              activeSettingsTab === tab.id
                ? 'border-purple-500 text-white'
                : 'border-transparent text-gray-400 hover:text-white'
            }`}
          >
            <tab.icon size={14} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Account Tab */}
      {activeSettingsTab === 'account' && (
        <div className="space-y-4">
          <div className="bg-white/5 border border-white/10 rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Account Settings</h3>
            
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Email</label>
                <input
                  type="email"
                  value={settings.email}
                  onChange={(e) => setSettings({...settings, email: e.target.value})}
                  className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                  placeholder="your@email.com"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Timezone</label>
                <select
                  value={settings.timezone}
                  onChange={(e) => setSettings({...settings, timezone: e.target.value})}
                  className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                >
                  <option value="UTC-5">UTC-5 (EST)</option>
                  <option value="UTC-8">UTC-8 (PST)</option>
                  <option value="UTC+0">UTC+0 (GMT)</option>
                  <option value="UTC+1">UTC+1 (CET)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Language</label>
                <select
                  value={settings.language}
                  onChange={(e) => setSettings({...settings, language: e.target.value})}
                  className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                >
                  <option value="English">English</option>
                  <option value="Spanish">Español</option>
                  <option value="French">Français</option>
                </select>
              </div>
            </div>
          </div>

          <div className="bg-white/5 border border-white/10 rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Change Password</h3>
            <div className="space-y-2">
              <input
                type="password"
                placeholder="Current password"
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
              />
              <input
                type="password"
                placeholder="New password"
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
              />
              <input
                type="password"
                placeholder="Confirm new password"
                className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
              />
              <button className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded text-sm font-semibold transition">
                Update Password
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Alerts Tab */}
      {activeSettingsTab === 'alerts' && (
        <div className="space-y-4">
          <div className="bg-white/5 border border-white/10 rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Notification Preferences</h3>
            
            <div className="space-y-3">
              <label className="flex items-center justify-between cursor-pointer">
                <span className="text-sm">Email Alerts</span>
                <div className={`relative w-12 h-6 rounded-full transition ${
                  settings.emailAlerts ? 'bg-purple-600' : 'bg-gray-600'
                }`}>
                  <div className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition transform ${
                    settings.emailAlerts ? 'translate-x-6' : ''
                  }`} />
                </div>
              </label>

              <label className="flex items-center justify-between cursor-pointer">
                <span className="text-sm">Browser Notifications</span>
                <input
                  type="checkbox"
                  checked={settings.browserNotifications}
                  onChange={(e) => setSettings({...settings, browserNotifications: e.target.checked})}
                  className="w-5 h-5"
                />
              </label>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Alert Threshold ($)</label>
                <input
                  type="number"
                  value={settings.alertThreshold}
                  onChange={(e) => setSettings({...settings, alertThreshold: parseInt(e.target.value) || 0})}
                  className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                />
              </div>
            </div>
          </div>

          <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3">
            <p className="text-xs text-blue-300">
              💡 Configure Telegram alerts in the Telegram Setup section
            </p>
          </div>
        </div>
      )}

      {/* Analysis Tab */}
      {activeSettingsTab === 'analysis' && (
        <div className="space-y-4">
          <div className="bg-white/5 border border-white/10 rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Default Analysis Settings</h3>
            
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Default Timeframe</label>
                <select
                  value={settings.defaultTimeframe}
                  onChange={(e) => setSettings({...settings, defaultTimeframe: e.target.value})}
                  className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                >
                  <option value="7d">7 Days</option>
                  <option value="14d">14 Days</option>
                  <option value="30d">30 Days</option>
                </select>
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Default Candle Size</label>
                <select
                  value={settings.defaultCandle}
                  onChange={(e) => setSettings({...settings, defaultCandle: e.target.value})}
                  className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                >
                  <option value="1m">1 Minute</option>
                  <option value="5m">5 Minutes</option>
                  <option value="15m">15 Minutes</option>
                  <option value="1h">1 Hour</option>
                </select>
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Min ROI Multiplier</label>
                <input
                  type="number"
                  step="0.5"
                  value={settings.minRoiMultiplier}
                  onChange={(e) => setSettings({...settings, minRoiMultiplier: parseFloat(e.target.value) || 1})}
                  className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Display Tab */}
      {activeSettingsTab === 'display' && (
        <div className="space-y-4">
          <div className="bg-white/5 border border-white/10 rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Display Preferences</h3>
            
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Theme</label>
                <select
                  value={settings.theme}
                  onChange={(e) => setSettings({...settings, theme: e.target.value})}
                  className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                >
                  <option value="dark">Dark</option>
                  <option value="light">Light</option>
                  <option value="auto">Auto</option>
                </select>
              </div>

              <label className="flex items-center justify-between cursor-pointer">
                <span className="text-sm">Compact Mode</span>
                <input
                  type="checkbox"
                  checked={settings.compactMode}
                  onChange={(e) => setSettings({...settings, compactMode: e.target.checked})}
                  className="w-5 h-5"
                />
              </label>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Data Refresh Rate (seconds)</label>
                <input
                  type="number"
                  value={settings.dataRefreshRate}
                  onChange={(e) => setSettings({...settings, dataRefreshRate: parseInt(e.target.value) || 30})}
                  className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Save Button */}
      <button
        onClick={handleSave}
        disabled={isSaving}
        className="w-full px-4 py-3 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 disabled:from-purple-600/30 disabled:to-purple-500/30 rounded-lg font-semibold transition flex items-center justify-center gap-2"
      >
        {isSaving ? (
          <>
            <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Saving...
          </>
        ) : (
          <>
            <Save size={18} />
            Save Settings
          </>
        )}
      </button>
    </div>
  );
}