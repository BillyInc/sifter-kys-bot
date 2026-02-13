import React, { useState, useEffect } from 'react';
import { Send, Check, X, RefreshCw, Bell, BellOff, ExternalLink } from 'lucide-react';
import { supabase } from './lib/supabase';

export default function TelegramSettings({ userId, apiUrl }) {
  const [status, setStatus] = useState({ connected: false, chat_id: null });
  const [isConnecting, setIsConnecting] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [alertsEnabled, setAlertsEnabled] = useState(true);
  const [error, setError] = useState(null);

  // Helper for Auth
  async function getHeaders() {
    const { data: { session } } = await supabase.auth.getSession();
    return {
      'Content-Type': 'application/json',
      ...(session?.access_token ? { 'Authorization': `Bearer ${session.access_token}` } : {})
    };
  }

  useEffect(() => {
    if (userId) checkTelegramStatus();
  }, [userId]);

  const checkTelegramStatus = async () => {
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/telegram/status?user_id=${userId}`, { headers });
      const data = await response.json();
      if (data.success) {
        setStatus({ connected: data.connected, chat_id: data.chat_id });
        setAlertsEnabled(data.connected);
      }
    } catch (error) {
      console.error('Error checking Telegram status:', error);
    }
  };

  const connectTelegram = async () => {
    setIsConnecting(true);
    setError(null);
    
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/telegram/connect/link`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId })
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: Failed to generate link`);
      }
      
      const data = await response.json();
      
      if (data.success && data.telegram_link) {
        // Open Telegram with deep link
        window.open(data.telegram_link, '_blank');
        
        // Start polling to check if connection succeeded
        pollConnectionStatus();
      } else {
        throw new Error(data.error || 'Failed to generate connection link');
      }
    } catch (error) {
      console.error('Connection error:', error);
      setError(error.message || 'Failed to connect to Telegram');
    } finally {
      setIsConnecting(false);
    }
  };

  const pollConnectionStatus = () => {
    let attempts = 0;
    const maxAttempts = 40; // 2 minutes (40 * 3 seconds)
    
    const interval = setInterval(async () => {
      attempts++;
      
      try {
        const headers = await getHeaders();
        const response = await fetch(`${apiUrl}/api/telegram/status?user_id=${userId}`, { headers });
        const data = await response.json();
        
        if (data.connected) {
          clearInterval(interval);
          setStatus({ connected: true, chat_id: data.chat_id });
          setAlertsEnabled(true);
          setError(null);
          // Show success message
          alert('✅ Telegram connected successfully!');
        }
      } catch (err) {
        console.error('Error checking status:', err);
      }
      
      // Stop polling after max attempts
      if (attempts >= maxAttempts) {
        clearInterval(interval);
      }
    }, 3000); // Poll every 3 seconds
  };

  const disconnectTelegram = async () => {
    if (!confirm('Disconnect Telegram alerts?')) return;
    
    setIsLoading(true);
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/telegram/disconnect`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId })
      });
      const data = await response.json();
      
      if (data.success) {
        setStatus({ connected: false, chat_id: null });
        setAlertsEnabled(false);
      }
    } catch (error) {
      console.error('Disconnect error:', error);
      alert('Failed to disconnect');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xl font-bold">Telegram Alerts</h3>
          <p className="text-sm text-gray-400 mt-1">Get instant wallet activity alerts on Telegram</p>
        </div>
        {status.connected && (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-green-500/20 text-green-400 rounded-lg text-sm">
            <Check size={16} /> Connected
          </div>
        )}
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4">
          <div className="flex items-center gap-2 text-red-400">
            <X size={16} />
            <span className="text-sm font-semibold">{error}</span>
          </div>
        </div>
      )}

      <div className="bg-white/5 border border-white/10 rounded-xl p-6">
        {!status.connected ? (
          <div className="space-y-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 bg-blue-500/20 rounded-xl flex items-center justify-center">
                <Send className="text-blue-400" size={24} />
              </div>
              <div>
                <h4 className="font-semibold">Connect Your Telegram</h4>
                <p className="text-sm text-gray-400">One-click connection to receive alerts</p>
              </div>
            </div>

            <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 mb-4">
              <h5 className="text-sm font-semibold text-blue-400 mb-2">How it works:</h5>
              <ol className="text-xs text-gray-400 space-y-1 list-decimal list-inside">
                <li>Click "Connect Telegram" below</li>
                <li>You'll be redirected to Telegram</li>
                <li>Click "Start" in the bot chat</li>
                <li>Your account will be linked automatically</li>
              </ol>
            </div>

            <button
              onClick={connectTelegram}
              disabled={isConnecting}
              className="w-full px-4 py-3 bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl font-semibold transition-all duration-300 flex items-center justify-center gap-2 shadow-lg shadow-blue-500/30"
            >
              {isConnecting ? (
                <>
                  <RefreshCw className="animate-spin" size={18} />
                  Opening Telegram...
                </>
              ) : (
                <>
                  <ExternalLink size={18} />
                  Connect Telegram
                </>
              )}
            </button>

            {isConnecting && (
              <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-2 h-2 bg-purple-400 rounded-full animate-pulse" />
                  <span className="text-sm font-semibold text-purple-400">Waiting for connection...</span>
                </div>
                <p className="text-xs text-gray-400 mb-3">
                  Click "Start" in the Telegram bot to complete the connection.
                </p>
                <button 
                  onClick={checkTelegramStatus}
                  className="w-full py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition"
                >
                  <RefreshCw size={16} /> Check Status
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between p-4 bg-green-500/10 border border-green-500/30 rounded-lg">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-green-500/20 rounded-xl flex items-center justify-center">
                  <Check className="text-green-400" size={24} />
                </div>
                <div>
                  <h4 className="font-semibold text-white">Bot Connected</h4>
                  <p className="text-xs text-gray-400 font-mono">ID: {status.chat_id}</p>
                </div>
              </div>
              <button 
                onClick={() => setAlertsEnabled(!alertsEnabled)} 
                className={`p-2 rounded-lg transition ${
                  alertsEnabled 
                    ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' 
                    : 'bg-gray-500/20 text-gray-400 hover:bg-gray-500/30'
                }`}
                title={alertsEnabled ? 'Alerts enabled' : 'Alerts disabled'}
              >
                {alertsEnabled ? <Bell size={20} /> : <BellOff size={20} />}
              </button>
            </div>

            <div className="bg-white/5 rounded-lg p-4">
              <h5 className="text-sm font-semibold mb-3">Alert Settings</h5>
              <div className="space-y-2 text-xs text-gray-400">
                <div className="flex items-center justify-between">
                  <span>Wallet buys</span>
                  <span className="text-green-400 font-semibold">Enabled</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Wallet sells</span>
                  <span className="text-green-400 font-semibold">Enabled</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Multi-wallet signals</span>
                  <span className="text-green-400 font-semibold">Enabled</span>
                </div>
              </div>
            </div>
            
            <button 
              onClick={disconnectTelegram}
              disabled={isLoading}
              className="w-full py-2.5 text-sm text-red-400 hover:bg-red-400/10 border border-red-500/30 rounded-lg transition font-semibold"
            >
              {isLoading ? 'Disconnecting...' : 'Disconnect Telegram'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}