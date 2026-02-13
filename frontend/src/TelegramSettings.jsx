import React, { useState, useEffect } from 'react';
import { Send, Check, X, RefreshCw, Bell, BellOff } from 'lucide-react';
import { supabase } from './lib/supabase';

export default function TelegramSettings({ userId, apiUrl }) {
  const [status, setStatus] = useState({ connected: false, chat_id: null });
  const [connectionCode, setConnectionCode] = useState(null);
  const [codeExpiry, setCodeExpiry] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [alertsEnabled, setAlertsEnabled] = useState(true);

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
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/telegram/status?user_id=${userId}`, { headers });
      const data = await response.json();
      if (data.success) {
        setStatus({ connected: data.connected, chat_id: data.chat_id });
      }
    } catch (error) {
      console.error('Error checking Telegram status:', error);
    }
  };

  const generateCode = async () => {
    setIsLoading(true);
    setTestResult(null);
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/telegram/connect/code`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId })
      });
      const data = await response.json();
      if (data.success) {
        setConnectionCode(data.code);
        setCodeExpiry(Date.now() + data.expires_in * 1000);
      } else {
        alert(data.error || 'Failed to generate code');
      }
    } catch (error) {
      alert('Error connecting to backend server');
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

      <div className="bg-white/5 border border-white/10 rounded-xl p-6">
        {!status.connected ? (
          <div className="space-y-4">
            <div className="flex items-center gap-3 mb-4">
              <Send className="text-blue-400" size={24} />
              <div>
                <h4 className="font-semibold">Connect Your Telegram</h4>
                <p className="text-sm text-gray-400">Link your account to receive real-time notifications</p>
              </div>
            </div>

            {!connectionCode ? (
              <button
                onClick={generateCode}
                disabled={isLoading}
                className="w-full px-4 py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg font-semibold transition flex items-center justify-center gap-2"
              >
                {isLoading ? <RefreshCw className="animate-spin" size={18} /> : <Send size={18} />}
                Generate Connection Code
              </button>
            ) : (
              <div className="space-y-4">
                <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 text-center">
                  <span className="text-sm text-gray-400">Your Code (Expires in {getRemainingTime()}):</span>
                  <div className="text-4xl font-bold tracking-widest text-white my-2">{connectionCode}</div>
                </div>

                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <h5 className="font-semibold mb-3 text-sm">📱 Setup Instructions:</h5>
                  <ol className="text-sm text-gray-300 space-y-2">
                    <li>1. Open Telegram and search for <strong>@SifterDueDiligenceBot</strong></li>
                    <li>2. Send <code className="bg-white/10 px-2 py-0.5 rounded">/start</code></li>
                    <li>3. Send the code shown above</li>
                  </ol>
                </div>
                
                <button onClick={checkTelegramStatus} className="w-full py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-semibold flex items-center justify-center gap-2">
                  <RefreshCw size={16} /> I've sent the code, check status
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between p-4 bg-green-500/10 border border-green-500/30 rounded-lg">
              <div className="flex items-center gap-3">
                <Check className="text-green-400" size={24} />
                <div>
                  <h4 className="font-semibold text-white">Bot Connected</h4>
                  <p className="text-xs text-gray-400 font-mono">ID: {status.chat_id}</p>
                </div>
              </div>
              <button onClick={() => setAlertsEnabled(!alertsEnabled)} className={`p-2 rounded-lg ${alertsEnabled ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'}`}>
                {alertsEnabled ? <Bell size={20} /> : <BellOff size={20} />}
              </button>
            </div>
            <button onClick={() => setStatus({connected: false})} className="w-full py-2 text-sm text-red-400 hover:bg-red-400/10 rounded-lg transition">
              Disconnect Telegram
            </button>
          </div>
        )}
      </div>
    </div>
  );
}