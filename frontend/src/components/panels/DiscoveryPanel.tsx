import React, { useState, useRef, useEffect } from 'react';
import { toast } from 'sonner';
import { Zap, Search, Sparkles, CheckCircle, AlertCircle, Shield, XCircle, AlertTriangle, RotateCcw, Minimize2, Activity } from 'lucide-react';

const POLL_INTERVAL_MS  = 3_000;
const MAX_POLL_ATTEMPTS = 400;   // 400 × 3s = 20 minutes

interface DiscoveryProgress {
  current: number;
  total: number;
  phase: string;
}

interface DiscoveryPanelProps {
  userId: string;
  apiUrl: string;
  onClose: () => void;
  onAddToWatchlist: (...args: any[]) => any;
  formatNumber: (v: any) => string;
  onResultsReady: ((data: any, type: string) => void) | null;
  onAnalysisStart: (info: any) => void;
  onAnalysisProgress: (progress: DiscoveryProgress) => void;
  onAnalysisComplete: (data: any) => void;
  activeAnalysis: any;
  onMinimize: (() => void) | null;
}

export default function DiscoveryPanel({
  userId,
  apiUrl,
  onClose,
  onAddToWatchlist,
  formatNumber,
  onResultsReady,
  onAnalysisStart,
  onAnalysisProgress,
  onAnalysisComplete,
  activeAnalysis,
  onMinimize,
}: DiscoveryPanelProps) {
  const [isDiscovering, setIsDiscovering]       = useState<boolean>(false);
  const [discoveryResults, setDiscoveryResults] = useState<any[] | null>(null);
  const [currentJobId, setCurrentJobId]         = useState<string | null>(null);
  const [analysisProgress, setAnalysisProgress] = useState<DiscoveryProgress>({ current: 0, total: 0, phase: '' });
  const [timedOut, setTimedOut]                 = useState<boolean>(false);
  const [timeoutMessage, setTimeoutMessage]     = useState<string>('');

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef    = useRef<number>(0);

  useEffect(() => {
    return () => { if (pollIntervalRef.current) clearInterval(pollIntervalRef.current); };
  }, []);

  const cancelDiscovery = async () => {
    if (currentJobId) {
      try { await fetch(`${apiUrl}/api/wallets/jobs/${currentJobId}/cancel`, { method: 'POST' }); }
      catch (e) { console.error('Error cancelling job:', e); }
    }
    if (pollIntervalRef.current) { clearInterval(pollIntervalRef.current); pollIntervalRef.current = null; }
    pollCountRef.current = 0;
    setIsDiscovering(false);
    setCurrentJobId(null);
    setAnalysisProgress({ current: 0, total: 0, phase: '' });
    setTimedOut(false);
    setTimeoutMessage('');
  };

  const attemptRecovery = async (jobId: string) => {
    setTimeoutMessage('Attempting to recover result from server…');
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/jobs/${jobId}/recover`, { method: 'POST' });
      const data = await res.json();
      if (data.results) {
        const wallets = data.results.top_wallets || data.results.smart_money_wallets || data.results.wallets || [];
        setDiscoveryResults(wallets);
        onAnalysisComplete(data.results);
        if (onResultsReady) onResultsReady(data.results, 'discovery');
        setIsDiscovering(false);
        setCurrentJobId(null);
        setTimedOut(false);
        setTimeoutMessage('');
        return true;
      }
    } catch (err) { console.warn('[DISCOVERY] Recovery failed:', err); }
    setTimeoutMessage('No recoverable result found. Please try again.');
    return false;
  };

  // Local poll — feeds progress into parent's global tracking
  const pollJobProgress = (jobId: string) => {
    pollCountRef.current = 0;

    pollIntervalRef.current = setInterval(async () => {
      pollCountRef.current++;

      if (pollCountRef.current > MAX_POLL_ATTEMPTS) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
        setTimedOut(true);
        setTimeoutMessage('⏱️ Discovery timed out after 20 minutes.');
        setAnalysisProgress(p => ({ ...p, phase: 'Timed out' }));
        await attemptRecovery(jobId);
        return;
      }

      try {
        const response = await fetch(`${apiUrl}/api/wallets/jobs/${jobId}/progress`);
        const data     = await response.json();

        if (data.success) {
          const progress = { current: data.tokens_completed || 0, total: data.tokens_total || 10, phase: data.phase || '' };
          setAnalysisProgress(progress);
          onAnalysisProgress(progress);

          if (data.status === 'completed') {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;

            const resultRes  = await fetch(`${apiUrl}/api/wallets/jobs/${jobId}`);
            const resultData = await resultRes.json();
            const wallets    = resultData.top_wallets || resultData.smart_money_wallets || resultData.wallets || [];

            setDiscoveryResults(wallets);
            onAnalysisComplete(resultData);
            if (onResultsReady) onResultsReady(resultData, 'discovery');
            setIsDiscovering(false);
            setCurrentJobId(null);

          } else if (data.status === 'failed') {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
            toast.error('Discovery failed');
            setIsDiscovering(false);
            setCurrentJobId(null);
          }
        }
      } catch (error) { console.error('Polling error:', error); }
    }, POLL_INTERVAL_MS);
  };

  const handleAutoDiscovery = async () => {
    if (isDiscovering) await cancelDiscovery();

    setIsDiscovering(true);
    setDiscoveryResults(null);
    setTimedOut(false);
    setTimeoutMessage('');
    setAnalysisProgress({ current: 0, total: 10, phase: 'Starting discovery…' });

    try {
      const response = await fetch(`${apiUrl}/api/wallets/discover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });
      const data = await response.json();

      if (data.success && data.job_id) {
        setCurrentJobId(data.job_id);
        onAnalysisStart({ jobId: data.job_id, total: 10, analysisType: 'discovery' });
        pollJobProgress(data.job_id);
        // Auto-minimize so user can keep working — panel stays open but hint is shown
      } else {
        toast.error(`Discovery failed: ${data.error || 'Unknown error'}`);
        setIsDiscovering(false);
      }
    } catch (error) {
      console.error('Auto discovery error:', error);
      toast.error('Discovery failed due to network error');
      setIsDiscovering(false);
    }
  };

  const handleAddWallet = async (wallet: any) => {
    try {
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          wallet: {
            wallet:               wallet.wallet,
            tier:                 wallet.tier || 'C',
            pump_count:           wallet.runner_hits_30d || wallet.runner_count || 0,
            avg_distance_to_peak: wallet.avg_distance_to_ath_pct || 0,
            avg_roi_to_peak:      wallet.avg_roi || 0,
            professional_score:   wallet.avg_professional_score || wallet.professional_score || 0,
            consistency_score:    wallet.consistency_score || 0,
            tokens_hit:           wallet.runners_hit || [],
          }
        })
      });
      const data = await response.json();
      if (data.success) toast.success(`Added ${wallet.wallet.slice(0, 8)}… to watchlist`);
      else toast.error(`Failed: ${data.error}`);
    } catch (error) { console.error('Add to watchlist error:', error); toast.error('Failed to add wallet to watchlist'); }
  };

  const handleAddAll = async () => {
    if (!discoveryResults?.length) return;
    toast.info(`Adding ${discoveryResults.length} wallets to watchlist...`);
    let successCount = 0;
    for (const wallet of discoveryResults) {
      try { await handleAddWallet(wallet); successCount++; } catch { /* ignore */ }
    }
    toast.success(`Added ${successCount}/${discoveryResults.length} wallets to your watchlist!`);
  };

  // Progress to show — prefer local (more granular) over parent summary
  const displayProgress = isDiscovering ? analysisProgress : activeAnalysis?.progress;
  const displayPct = displayProgress
    ? Math.round(((displayProgress.current || 0) / (displayProgress.total || 1)) * 100)
    : 0;

  return (
    <div className="space-y-4">

      {/* ── Discovery launch card ── */}
      <div className="bg-gradient-to-br from-yellow-900/20 to-yellow-800/10 border border-yellow-500/30 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Zap className="text-yellow-400" size={20} />
          <h3 className="text-base font-semibold">Auto Discovery</h3>
        </div>

        <p className="text-xs text-gray-400 mb-4">
          Automatically scan the last 30 days of trending tokens to find wallets that consistently hit multiple runners
        </p>

        <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-3 mb-4">
          <div className="flex items-center gap-2 text-xs">
            <Shield className="text-green-400" size={14} />
            <span className="text-green-400 font-semibold">Security Filter Active</span>
          </div>
          <p className="text-xs text-gray-400 mt-1">
            All tokens verified: Liquidity locked · Mint authority revoked · Social presence
          </p>
        </div>

        {/* Action buttons */}
        <div className="flex gap-2">
          {isDiscovering ? (
            <button
              onClick={cancelDiscovery}
              className="flex-1 px-4 py-3 bg-gradient-to-r from-red-600 to-red-500 hover:from-red-700 hover:to-red-600 rounded-lg font-semibold transition flex items-center justify-center gap-2 shadow-lg shadow-red-500/30"
            >
              <XCircle size={18} /> Cancel
            </button>
          ) : (
            <button
              onClick={handleAutoDiscovery}
              className="flex-1 px-4 py-3 bg-gradient-to-r from-yellow-600 to-yellow-500 hover:from-yellow-700 hover:to-yellow-600 rounded-lg font-semibold transition flex items-center justify-center gap-2 shadow-lg shadow-yellow-500/30"
            >
              <Search size={18} /> Start Auto Discovery
            </button>
          )}

          {/* Minimize — only while running */}
          {isDiscovering && onMinimize && (
            <button
              onClick={onMinimize}
              title="Minimize to background"
              className="px-3 py-3 rounded-lg transition flex items-center gap-1.5"
              style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}
            >
              <Minimize2 size={16} />
            </button>
          )}
        </div>

        {/* Progress bar */}
        {(isDiscovering || (activeAnalysis && !discoveryResults)) && (
          <div className="mt-4 space-y-2">
            <div className="rounded-full h-2 overflow-hidden" style={{ backgroundColor: 'var(--bg-secondary)' }}>
              <div
                className="bg-gradient-to-r from-yellow-500 to-amber-400 h-2 transition-all duration-500"
                style={{ width: `${displayPct}%` }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-400">
              <span>{displayProgress?.phase || 'Processing…'}</span>
              <span>{displayProgress?.current}/{displayProgress?.total} · {displayPct}%</span>
            </div>
            {isDiscovering && (
              <p className="text-xs text-gray-600 text-center">
                You can minimize this panel — discovery runs in the background
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── Active analysis card from parent (cross-session restore) ── */}
      {activeAnalysis && !isDiscovering && !discoveryResults && (
        <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Activity size={14} className="text-green-400 animate-pulse" />
              Discovery In Progress
            </h3>
            {onMinimize && (
              <button
                onClick={onMinimize}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs transition"
                style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}
              >
                <Minimize2 size={12} /> Minimize
              </button>
            )}
          </div>
          <div className="rounded-full h-2 overflow-hidden mb-2" style={{ backgroundColor: 'var(--bg-secondary)' }}>
            <div
              className="bg-green-500 h-2 transition-all duration-500"
              style={{ width: `${Math.round(((activeAnalysis.progress?.current || 0) / (activeAnalysis.progress?.total || 1)) * 100)}%` }}
            />
          </div>
          <p className="text-xs text-gray-400 text-center">
            {activeAnalysis.progress?.phase} ({activeAnalysis.progress?.current}/{activeAnalysis.progress?.total})
          </p>
        </div>
      )}

      {/* ── Timeout / recovery banner ── */}
      {timedOut && (
        <div className="bg-orange-500/10 border border-orange-500/30 rounded-xl p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} className="text-orange-400 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-orange-400">Discovery Timed Out</div>
              <p className="text-xs text-gray-400 mt-1">{timeoutMessage}</p>
            </div>
            <button
              onClick={() => currentJobId && attemptRecovery(currentJobId)}
              className="shrink-0 flex items-center gap-1 px-3 py-1.5 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/30 rounded-lg text-xs font-semibold text-orange-400 transition"
            >
              <RotateCcw size={12} /> Retry Recovery
            </button>
          </div>
        </div>
      )}

      {/* ── Results ── */}
      {discoveryResults && (
        <div className="rounded-xl p-4" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold flex items-center gap-2">
                <Sparkles className="text-yellow-400" size={18} />
                Discovery Results
              </h3>
              <p className="text-xs text-gray-400 mt-1">Found {discoveryResults.length} qualifying wallets</p>
            </div>
            {discoveryResults.length > 0 && (
              <button
                onClick={handleAddAll}
                className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold transition"
              >
                Add All to Watchlist
              </button>
            )}
          </div>

          {discoveryResults.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <AlertCircle size={48} className="mx-auto mb-3 opacity-20" />
              <p className="text-sm">No wallets found matching your criteria</p>
              <p className="text-xs mt-1">Try again later</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
              {discoveryResults.map((wallet, idx) => (
                <div
                  key={wallet.wallet || idx}
                  className="rounded-lg p-3 transition"
                  style={{ backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-yellow-400 font-bold">#{idx + 1}</span>
                        <code className="text-sm font-mono text-gray-300">{wallet.wallet?.slice(0, 16)}…</code>
                        {wallet.tier && (
                          <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                            wallet.tier === 'S' ? 'bg-yellow-500/20 text-yellow-400' :
                            wallet.tier === 'A' ? 'bg-green-500/20 text-green-400'  :
                            wallet.tier === 'B' ? 'bg-blue-500/20 text-blue-400'    :
                            'bg-gray-500/20 text-gray-400'
                          }`}>{wallet.tier}-Tier</span>
                        )}
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 sm:gap-3 text-xs">
                        <div><span className="text-gray-500">Runners:</span><span className="ml-1 text-yellow-400 font-bold">{wallet.runner_count || wallet.runner_hits_30d || 0}</span></div>
                        <div><span className="text-gray-500">Score:</span><span className="ml-1 font-bold" style={{ color: 'var(--text-primary)' }}>{wallet.avg_professional_score || wallet.professional_score || 0}</span></div>
                        <div><span className="text-gray-500">Avg ROI:</span><span className="ml-1 text-green-400 font-bold">+{(wallet.avg_roi || 0).toFixed(1)}%</span></div>
                      </div>
                      {wallet.runners_hit?.length > 0 && (
                        <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--border-color)' }}>
                          <div className="text-xs text-gray-500 mb-1">Recent Hits:</div>
                          <div className="flex flex-wrap gap-1">
                            {wallet.runners_hit.slice(0, 5).map((token, tidx) => (
                              <span key={tidx} className="text-xs px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded">{token}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() => handleAddWallet(wallet)}
                      className="ml-3 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold transition flex items-center gap-1"
                    >
                      <CheckCircle size={14} /> Add
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── How it works ── */}
      <div className="rounded-lg p-4" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <h4 className="text-sm font-semibold mb-2">How Auto Discovery Works</h4>
        <ol className="space-y-2 text-xs text-gray-400">
          <li className="flex gap-2"><span className="text-purple-400">1.</span><span>Scans all trending tokens from the past 30 days</span></li>
          <li className="flex gap-2"><span className="text-purple-400">2.</span><span>Identifies wallets that hit multiple runners</span></li>
          <li className="flex gap-2"><span className="text-purple-400">3.</span><span>Filters by minimum ROI multiplier (3x default)</span></li>
          <li className="flex gap-2"><span className="text-purple-400">4.</span><span>Returns top 50 most consistent performers</span></li>
        </ol>
      </div>
    </div>
  );
}