import React, { useState } from 'react';
import { User, Settings, Bell, Key, CreditCard, HelpCircle, LogOut, BarChart3 } from 'lucide-react';
import SettingsSubPanel from './SettingsSubPanel';
import TelegramSettings from '../../TelegramSettings';
import MyDashboardPanel from './MyDashboardPanel';

export default function ProfilePanel({ 
  user, 
  userId,
  apiUrl,
  onNavigate,
  onSignOut 
}) {
  const [subPanel, setSubPanel] = useState(null); // 'settings', 'telegram', 'dashboard'

  // If viewing a sub-panel, render it
  if (subPanel === 'settings') {
    return <SettingsSubPanel userId={userId} apiUrl={apiUrl} onBack={() => setSubPanel(null)} />;
  }

  if (subPanel === 'telegram') {
    return (
      <div className="space-y-4">
        <button
          onClick={() => setSubPanel(null)}
          className="flex items-center gap-2 text-sm text-purple-400 hover:text-purple-300 transition"
        >
          ← Back to Profile
        </button>
        <TelegramSettings userId={userId} apiUrl={apiUrl} />
      </div>
    );
  }

  if (subPanel === 'dashboard') {
    return (
      <div className="space-y-4">
        <button
          onClick={() => setSubPanel(null)}
          className="flex items-center gap-2 text-sm text-purple-400 hover:text-purple-300 transition"
        >
          ← Back to Profile
        </button>
        <MyDashboardPanel userId={userId} apiUrl={apiUrl} />
      </div>
    );
  }

  // Main profile menu
  const menuItems = [
    { id: 'dashboard', icon: BarChart3, label: 'My Dashboard', color: 'text-purple-400', action: () => setSubPanel('dashboard') },
    { id: 'settings', icon: Settings, label: 'Settings', color: 'text-gray-400', action: () => setSubPanel('settings') },
    { id: 'telegram', icon: Bell, label: 'Telegram Setup', color: 'text-blue-400', action: () => setSubPanel('telegram') },
    { id: 'api', icon: Key, label: 'API Keys', color: 'text-yellow-400', action: () => alert('API Keys coming soon') },
    { id: 'billing', icon: CreditCard, label: 'Billing', color: 'text-green-400', action: () => window.open('https://whop.com/sifter', '_blank') },
  ];

  return (
    <div className="space-y-4">
      {/* User Info */}
      <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-4">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-12 h-12 bg-purple-500/20 rounded-full flex items-center justify-center">
            <User className="text-purple-400" size={24} />
          </div>
          <div>
            <div className="font-bold">{user?.email?.split('@')[0] || 'User'}</div>
            <div className="text-xs text-gray-400">{user?.email}</div>
          </div>
        </div>
        <div className="flex items-center justify-between pt-2 border-t border-white/10">
          <span className="text-xs text-gray-400">Plan:</span>
          <span className="text-sm font-bold text-purple-400">Pro</span>
        </div>
      </div>

      {/* Menu Items */}
      <div className="space-y-2">
        {menuItems.map((item) => (
          <button
            key={item.id}
            onClick={item.action}
            className="w-full p-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-left transition flex items-center gap-3"
          >
            <item.icon className={item.color} size={18} />
            <span className="font-medium">{item.label}</span>
          </button>
        ))}
      </div>

      {/* Help & Sign Out */}
      <div className="space-y-2 pt-4 border-t border-white/10">
        <button
          onClick={() => onNavigate('help')}
          className="w-full p-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-left transition flex items-center gap-3"
        >
          <HelpCircle className="text-blue-400" size={18} />
          <span className="font-medium">Help & Support</span>
        </button>

        <button
          onClick={onSignOut}
          className="w-full p-3 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 rounded-lg text-left transition flex items-center gap-3"
        >
          <LogOut className="text-red-400" size={18} />
          <span className="font-medium text-red-400">Sign Out</span>
        </button>
      </div>
    </div>
  );
}