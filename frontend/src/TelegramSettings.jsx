import React, { useState, useEffect } from 'react';
import { Send, Check, X, RefreshCw, Bell, BellOff } from 'lucide-react';

export default function TelegramSettings({ userId, apiUrl }) {
  const [status, setStatus] = useState({
    connected: false,
    chat_id: null
  });
  const [connectionCode, setConnectionCode] = useState(null);
  const [codeExpiry, setCodeExpiry] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [alertsEnabled, setAlertsEnabled] = useState(true);

  useEffect(() => {
    checkTelegramStatus();
  }, [userId]);

  useEffect(() => {
    if (codeExpiry) {
      const timer = setInterval(() => {
        const remaining = codeExpiry - Date.now();
        if (remaining <= 0) {
          setConnectionCode(null);
          setCodeExpiry(null);
        }
      }, 1000);

      return () => clearInterval(timer);
    }
  }, [codeExpiry]);

  const checkTelegramStatus = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/telegram/status?user_id=${userId}`);
      const data = await response.json();
      
      if (data.success) {
        setStatus({
          connected: data.connected,
          chat_id: data.chat_id
        });
      }
    } catch (error) {
      console.error('Error checking Telegram status:', error);
    }
  };

  const generateCode = async () => {
    setIsLoading(true);
    setTestResult(null);

    try {
      const response = await fetch(`${apiUrl}/api/telegram/connect/code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });

      const data = await response.json();

      if (data.success) {
        setConnectionCode(data.code);
        setCodeExpiry(Date.now() + data.expires_in * 1000);
      } else {
        alert('Failed to generate code');
      }
    } catch (error) {
      console.error('Error generating code:', error);
      alert('Error generating code');
    }

    setIsLoading(false);
  };

  const disconnect = async () => {
    if (!confirm('Disconnect Telegram? You will stop receiving alerts.')) return;

    setIsLoading(true);

    try {
      const response = await fetch(`${apiUrl}/api/telegram/disconnect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });

      const data = await response.json();

      if (data.success) {
        setStatus({ connected: false, chat_id: null });
        alert('Telegram disconnected');
      } else {
        alert('Failed to disconnect');
      }
    } catch (error) {
      console.error('Error disconnecting:', error);
      alert('Error disconnecting');
    }

    setIsLoading(false);
  };

  const toggleAlerts = async () => {
    const newState = !alertsEnabled;

    try {
      const response = await fetch(`${apiUrl}/api/telegram/alerts/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          enabled: newState
        })
      });

      const data = await response.json();

      if (data.success) {
        setAlertsEnabled(newState);
      } else {
        alert('Failed to update settings');
      }
    } catch (error) {
      console.error('Error toggling alerts:', error);
      alert('Error updating settings');
    }
  };

  const sendTestAlert = async () => {
    setIsLoading(true);
    setTestResult(null);

    try {
      const response = await fetch(`${apiUrl}/api/telegram/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });

      const data = await response.json();

      setTestResult({
        success: data.success,
        message: data.message || data.error
      });
    } catch (error) {
      console.error('Error sending test:', error);
      setTestResult({
        success: false,
        message: 'Error sending test alert'
      });
    }

    setIsLoading(false);
  };

  const getRemainingTime = () => {
    if (!codeExpiry) return null;
    const remaining = Math.max(0, Math.floor((codeExpiry - Date.now()) / 1000));
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xl font-bold">Telegram Alerts</h3>
          <p className="text-sm text-gray-400 mt-1">
            Get instant wallet activity alerts on Telegram
          </p>
        </div>

        {status.connected && (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-green-500/20 text-green-400 rounded-lg text-sm">
            <Check size={16} />
            Connected
          </div>
        )}
      </div>

      {/* Connection Section */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-6">
        {!status.connected ? (
          // Not Connected
          <div className="space-y-4">
            <div className="flex items-center gap-3 mb-4">
              <Send className="text-blue-400" size={24} />
              <div>
                <h4 className="font-semibold">Connect Your Telegram</h4>
                <p className="text-sm text-gray-400">
                  Link your Telegram account to receive alerts
                </p>
              </div>
            </div>

            {!connectionCode ? (
              <button
                onClick={generateCode}
                disabled={isLoading}
                className="w-full px-4 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 rounded-lg font-semibold transition flex items-center justify-center gap-2"
              >
                {isLoading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Send size={18} />
                    Generate Connection Code
                  </>
                )}
              </button>
            ) : (
              <div className="space-y-4">
                <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-sm text-gray-400">Your Connection Code:</span>
                    <span className="text-xs text-orange-400">
                      Expires in {getRemainingTime()}
                    </span>
                  </div>
                  <div className="text-center">
                    <div className="text-4xl font-bold tracking-widest text-white mb-4">
                      {connectionCode}
                    </div>
                    <button
                      onClick={() => navigator.clipboard.writeText(connectionCode)}
                      className="text-sm text-blue-400 hover:text-blue-300 transition"
                    >
                      📋 Copy Code
                    </button>
                  </div>
                </div>

                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <h5 className="font-semibold mb-3">📱 Setup Instructions:</h5>
                  <ol className="text-sm text-gray-300 space-y-2">
                    <li>1. Open Telegram app</li>
                    <li>2. Search for your bot (check bot info below)</li>
                    <li>3. Send <code className="bg-white/10 px-2 py-0.5 rounded">/start</code></li>
                    <li>4. Send the code: <code className="bg-white/10 px-2 py-0.5 rounded">{connectionCode}</code></li>
                  </ol>
                </div>

                <button
                  onClick={checkTelegramStatus}
                  className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg font-semibold transition flex items-center justify-center gap-2"
                >
                  <RefreshCw size={18} />
                  Check Connection Status
                </button>
              </div>
            )}
          </div>
        ) : (
          // Connected
          <div className="space-y-4">
            <div className="flex items-center justify-between p-4 bg-green-500/10 border border-green-500/30 rounded-lg">
              <div className="flex items-center gap-3">
                <Check className="text-green-400" size={24} />
                <div>
                  <h4 className="font-semibold">Telegram Connected</h4>
                  <p className="text-sm text-gray-400">
                    Chat ID: {status.chat_id}
                  </p>
                </div>
              </div>

              <button
                onClick={toggleAlerts}
                className={`p-2 rounded-lg transition ${
                  alertsEnabled
                    ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                    : 'bg-gray-500/20 text-gray-400 hover:bg-gray-500/30'
                }`}
                title={alertsEnabled ? 'Disable alerts' : 'Enable alerts'}
              >
                {alertsEnabled ? <Bell size={20} /> : <BellOff size={20} />}
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={sendTestAlert}
                disabled={isLoading}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 rounded-lg font-semibold transition"
              >
                Send Test Alert
              </button>

              <button
                onClick={disconnect}
                disabled={isLoading}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-red-600/50 rounded-lg font-semibold transition"
              >
                Disconnect
              </button>
            </div>

            {testResult && (
              <div className={`p-3 rounded-lg ${
                testResult.success
                  ? 'bg-green-500/20 text-green-400'
                  : 'bg-red-500/20 text-red-400'
              }`}>
                {testResult.message}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Info Section */}
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-4">
        <h4 className="font-semibold mb-2">ℹ️ How It Works</h4>
        <ul className="text-sm text-gray-300 space-y-1">
          <li>• Get instant alerts when watched wallets trade</li>
          <li>• One-click copy commands for Your Trading Bot</li>
          <li>• View charts and transactions directly</li>
          <li>• Manage alert preferences in dashboard</li>
        </ul>
      </div>
    </div>
  );
}