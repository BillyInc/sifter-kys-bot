import React, { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { Send, Check, X, RefreshCw, Bell, BellOff, ExternalLink, Play, Square, Activity, AlertTriangle } from 'lucide-react';
import { supabase } from './lib/supabase';

export default function TelegramSettings({ userId, apiUrl }) {
  const [status, setStatus] = useState({ connected: false, chat_id: null });
  const [isConnecting, setIsConnecting] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [alertsEnabled, setAlertsEnabled] = useState(true);
  const [error, setError] = useState(null);
  const [operatorStatus, setOperatorStatus] = useState(null);
  const [operatorLoading, setOperatorLoading] = useState(false);

  // Helper for Auth
  async function getHeaders() {
    const { data: { session } } = await supabase.auth.getSession();
    return {
      'Content-Type': 'application/json',
      ...(session?.access_token ? { 'Authorization': `Bearer ${session.access_token}` } : {})
    };
  }

  useEffect(() => {
    if (userId) {
      checkTelegramStatus();
      loadOperatorStatus();
    }
  }, [userId]);

  const checkTelegramStatus = async () => {
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/telegram/status?user_id=${userId}`, { headers });
      const data = await response.json();
      if (data.success) {
        setStatus({ connected: data.connected, chat_id: data.chat_id });
        if (data.connected) setAlertsEnabled(data.alerts_enabled ?? true);
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
          toast.success('Telegram connected successfully!');
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
    // Proceed with disconnect — toast will show result
    
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
      toast.error('Failed to disconnect');
    } finally {
      setIsLoading(false);
    }
  };

  const toggleAlerts = async () => {
    const next = !alertsEnabled;
    setAlertsEnabled(next); // optimistic
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/telegram/alerts/toggle`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, enabled: next })
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Failed');
      toast.success(next ? 'Alerts enabled' : 'Alerts muted');
    } catch (err) {
      setAlertsEnabled(!next); // revert on failure
      toast.error('Failed to update alert setting');
    }
  };

  const sendTestAlert = async () => {
    setIsLoading(true);
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/telegram/test`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId })
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Failed to send');
      toast.success('Test alert sent — check your Telegram');
    } catch (err) {
      toast.error(err.message || 'Failed to send test alert');
    } finally {
      setIsLoading(false);
    }
  };

  const loadOperatorStatus = async () => {
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/telegram/operator/status`, { headers });
      if (response.status === 403 || response.status === 401) {
        setOperatorStatus(null);
        return;
      }
      const data = await response.json();
      if (data.success) {
        setOperatorStatus(data);
      }
    } catch (error) {
      console.error('Operator status error:', error);
    }
  };

  const runOperatorAction = async (path, method = 'POST', body = {}) => {
    setOperatorLoading(true);
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}${path}`, {
        method,
        headers,
        body: method === 'GET' ? undefined : JSON.stringify(body)
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      toast.success('Operator action completed');
      await loadOperatorStatus();
    } catch (error) {
      toast.error(error.message || 'Operator action failed');
    } finally {
      setOperatorLoading(false);
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
                onClick={toggleAlerts}
                className={`p-2 rounded-lg transition ${
                  alertsEnabled
                    ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                    : 'bg-gray-500/20 text-gray-400 hover:bg-gray-500/30'
                }`}
                title={alertsEnabled ? 'Alerts enabled — tap to mute' : 'Alerts muted — tap to enable'}
              >
                {alertsEnabled ? <Bell size={20} /> : <BellOff size={20} />}
              </button>
            </div>

            <div className="bg-white/5 rounded-lg p-4">
              <div className="flex items-center justify-between mb-3">
                <h5 className="text-sm font-semibold">Alert Settings</h5>
                <span className={`text-xs font-semibold ${alertsEnabled ? 'text-green-400' : 'text-gray-400'}`}>
                  {alertsEnabled ? 'Alerts on' : 'Muted'}
                </span>
              </div>
              <div className="space-y-2 text-xs text-gray-400">
                {['Wallet buys', 'Wallet sells', 'Multi-wallet signals'].map((label) => (
                  <div key={label} className="flex items-center justify-between">
                    <span>{label}</span>
                    <span className={alertsEnabled ? 'text-green-400 font-semibold' : 'text-gray-500 font-semibold'}>
                      {alertsEnabled ? 'Enabled' : 'Muted'}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-gray-500 mt-3">
                Use the bell above to mute or enable all alerts.
              </p>
            </div>

            <button
              onClick={sendTestAlert}
              disabled={isLoading}
              className="w-full py-2.5 text-sm font-semibold bg-blue-500/15 text-blue-300 hover:bg-blue-500/25 border border-blue-500/30 rounded-lg transition flex items-center justify-center gap-2 disabled:opacity-50"
            >
              <Send size={16} /> Send test alert
            </button>

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

      {operatorStatus && (
        <div className="bg-white/5 border border-white/10 rounded-xl p-6 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h4 className="font-semibold flex items-center gap-2">
                <Activity size={18} className="text-purple-400" />
                Paper Trader Ops
              </h4>
              <p className="text-xs text-gray-400 mt-1">Runtime controls and critical execution health</p>
            </div>
            <button
              onClick={loadOperatorStatus}
              className="p-2 rounded-lg bg-white/5 hover:bg-white/10 transition"
              title="Refresh"
            >
              <RefreshCw size={16} />
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div className="bg-black/20 rounded-lg p-3">
              <div className="text-xs text-gray-400">Runtime</div>
              <div className={operatorStatus.status?.settings?.paper_trader_enabled ? 'text-green-400 font-bold' : 'text-gray-300 font-bold'}>
                {operatorStatus.status?.settings?.paper_trader_enabled ? 'ON' : 'OFF'}
              </div>
            </div>
            <div className="bg-black/20 rounded-lg p-3">
              <div className="text-xs text-gray-400">Entries</div>
              <div className="font-bold">{operatorStatus.summary?.signals?.entered || 0}</div>
            </div>
            <div className="bg-black/20 rounded-lg p-3">
              <div className="text-xs text-gray-400">Skipped</div>
              <div className="font-bold">{operatorStatus.summary?.signals?.skipped || 0}</div>
            </div>
            <div className="bg-black/20 rounded-lg p-3">
              <div className="text-xs text-gray-400">Critical Logs</div>
              <div className={operatorStatus.status?.critical_count ? 'text-red-400 font-bold' : 'font-bold'}>
                {operatorStatus.status?.critical_count || 0}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => runOperatorAction('/api/telegram/operator/paper-trader/start')}
              disabled={operatorLoading}
              className="px-3 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 rounded-lg text-sm font-semibold flex items-center gap-2"
            >
              <Play size={16} /> Start
            </button>
            <button
              onClick={() => runOperatorAction('/api/telegram/operator/paper-trader/stop')}
              disabled={operatorLoading}
              className="px-3 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 rounded-lg text-sm font-semibold flex items-center gap-2"
            >
              <Square size={16} /> Stop
            </button>
            <button
              onClick={() => runOperatorAction('/api/telegram/operator/paper-trader/test-signal')}
              disabled={operatorLoading}
              className="px-3 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 rounded-lg text-sm font-semibold flex items-center gap-2"
            >
              <Activity size={16} /> Test Signal
            </button>
          </div>

          {operatorStatus.failure_report?.issues?.length > 0 && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
              <div className="flex items-center gap-2 text-red-300 text-sm font-semibold mb-2">
                <AlertTriangle size={16} />
                Failure Report
              </div>
              <div className="text-xs text-gray-300">
                {operatorStatus.failure_report.issues.join(', ')}
              </div>
            </div>
          )}

          <div className="space-y-2">
            <h5 className="text-sm font-semibold">Recent Logs</h5>
            {(operatorStatus.status?.recent_logs || []).slice(0, 5).map((row) => (
              <div key={row.id || `${row.created_at}-${row.message}`} className="flex items-start justify-between gap-3 rounded-lg bg-black/20 p-3 text-xs">
                <span className="text-gray-400 uppercase">{row.severity || 'info'}</span>
                <span className="flex-1 text-gray-200">{row.message || row.event_type}</span>
              </div>
            ))}
            {(operatorStatus.status?.recent_logs || []).length === 0 && (
              <div className="text-xs text-gray-500">No paper trader logs yet.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
