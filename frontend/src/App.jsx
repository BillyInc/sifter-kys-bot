import React, { lazy, Suspense, useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from './contexts/AuthContext';
import { User, ChevronDown, Settings, HelpCircle, LogOut, BarChart3, Award, Clock, Activity } from 'lucide-react';

import DashboardHome      from './components/dashboard/DashboardHome';
import SlideOutPanel      from './components/panels/SlideOutPanel';

// Lazy-loaded panel components for code splitting
const AnalyzePanel        = lazy(() => import('./components/panels/AnalyzePanel'));
const TrendingPanel       = lazy(() => import('./components/panels/TrendingPanel'));
const DiscoveryPanel      = lazy(() => import('./components/panels/DiscoveryPanel'));
const WatchlistPanel      = lazy(() => import('./components/panels/WatchlistPanel'));
const Top100CommunityPanel  = lazy(() => import('./components/panels/Top100CommunityPanel'));
const PremiumElite100Panel  = lazy(() => import('./components/panels/PremiumElite100Panel'));
const QuickAddWalletPanel   = lazy(() => import('./components/panels/QuickAddWalletPanel'));
const ProfilePanel        = lazy(() => import('./components/panels/ProfilePanel'));
const HelpSupportPanel    = lazy(() => import('./components/panels/HelpSupportPanel'));
const ResultsPanel        = lazy(() => import('./components/panels/ResultsPanel'));
const SimulatorModal      = lazy(() => import('./components/panels/SimulatorModal'));
import RecentResultsList  from './components/RecentResultsList';
import { useRecents }     from './components/hooks/useRecentResults';

import WalletActivityMonitor  from './WalletActivityMonitor';
import WalletAlertSettings    from './WalletAlertSettings';
const WalletReplacementModal = lazy(() => import('./WalletReplacementModal'));
import Auth from './components/Auth';
import { Toaster, toast } from 'sonner';

// ─── Constants ────────────────────────────────────────────────────────────────
const POLL_INTERVAL_MS  = 3_000;
const MAX_POLL_ATTEMPTS = 400;   // 400 × 3s = 20 minutes

const TRENDING_CACHE_KEY = 'sifter_trending_runners';
const TRENDING_CACHE_TTL = 10 * 60 * 1000;

export default function SifterKYS() {
  const {
    user, loading: authLoading, isAuthenticated,
    signOut, getAccessToken, signIn, signUp, resetPassword, updatePassword
  } = useAuth();

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';
  const userId  = user?.id;

  const [openPanel, setOpenPanel]             = useState(null);
  const [showProfileDropdown, setShowProfileDropdown] = useState(false);
  const [resultsPanel, setResultsPanel]       = useState({ isOpen: false, type: null, data: null });
  const [simulatorWallet, setSimulatorWallet] = useState(null);

  // ── Cached trending runners ──────────────────────────────────────────────────
  const [cachedTrendingRunners, setCachedTrendingRunners] = useState(() => {
    try {
      const stored = localStorage.getItem(TRENDING_CACHE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed.timestamp && Date.now() - parsed.timestamp < TRENDING_CACHE_TTL) {
          return parsed.runners || [];
        }
      }
    } catch (e) { /* ignore */ }
    return [];
  });

  const saveTrendingToCache = useCallback((runners) => {
    try {
      localStorage.setItem(TRENDING_CACHE_KEY, JSON.stringify({ runners, timestamp: Date.now() }));
      setCachedTrendingRunners(runners);
    } catch (e) { /* ignore */ }
  }, []);

  // ── Recent results ───────────────────────────────────────────────────────────
  const {
    recents: recentResults, loading: recentsLoading, error: recentsError,
    saveResult: addToRecents, removeResult: removeRecent,
    clearAll: clearRecents, refreshRecents,
  } = useRecents({ apiUrl: API_URL, userId, getAccessToken });

  // ── Search state ─────────────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery]       = useState('');
  const [searchResults, setSearchResults]   = useState([]);
  const [selectedTokens, setSelectedTokens] = useState([]);
  const [isSearching, setIsSearching]       = useState(false);
  const [showDropdown, setShowDropdown]     = useState(false);
  const searchRef = useRef(null);

  // ── Analysis settings ────────────────────────────────────────────────────────
  const [analysisType, setAnalysisType]           = useState('general');
  const [useGlobalSettings, setUseGlobalSettings] = useState(true);
  const [tokenSettings, setTokenSettings]         = useState({});
  const [daysBack, setDaysBack]                   = useState(7);
  const [candleSize, setCandleSize]               = useState('5m');
  const [tMinusWindow, setTMinusWindow]           = useState(4);
  const [tPlusWindow, setTPlusWindow]             = useState(2);

  // ── Other state ──────────────────────────────────────────────────────────────
  const [alertSettingsWallet, setAlertSettingsWallet] = useState(null);
  const [replacementData, setReplacementData]   = useState(null);
  const [dashboardRefreshKey, setDashboardRefreshKey] = useState(0);
  const [userPoints, setUserPoints]             = useState(0);

  // ── Refs ─────────────────────────────────────────────────────────────────────
  const completedJobsRef  = useRef(new Set());
  const savedResultIdsRef = useRef(new Set());
  const pollIntervalsRef  = useRef({});
  const activeAnalysesRef = useRef({});
  const cancellingRef     = useRef(new Set());

  // ── Panel helpers ────────────────────────────────────────────────────────────
  const handleOpenPanel  = (panelId) => { setOpenPanel(panelId); setShowProfileDropdown(false); setShowActiveAnalyses(false); };
  const handleClosePanel = () => setOpenPanel(null);

  // ── Results dedup ────────────────────────────────────────────────────────────
  const handleResultsReady = useCallback((data, type) => {
    const resultId = data?.job_id || data?.id || JSON.stringify(data).slice(0, 60);
    if (savedResultIdsRef.current.has(resultId)) {
      setResultsPanel({ isOpen: true, type, data });
      return;
    }
    savedResultIdsRef.current.add(resultId);
    setResultsPanel({ isOpen: true, type, data });

    const token = data?.token;
    let label, sublabel;
    if (type === 'discovery') {
      label = '⚡ Auto Discovery'; sublabel = 'Full 30-day scan';
    } else if (type?.includes('trending')) {
      label    = token ? `🔥 ${token.ticker || token.symbol || 'Trending'}` : '🔥 Trending Batch';
      sublabel = type.includes('batch') ? 'Batch' : 'Single token';
    } else {
      label    = token ? `📊 ${token.ticker || token.symbol || 'Token'}` : '📊 Batch Analysis';
      sublabel = type === 'batch-token' ? 'Batch' : 'Single token';
    }
    addToRecents({ label, sublabel, data, resultType: type });
  }, [addToRecents]);

  const getPanelConfig = (panelId) => ({
    analyze:    { direction: 'left',  width: 'w-96',             title: '🔍 Analyze Tokens'    },
    trending:   { direction: 'right', width: 'w-[800px]',        title: '🔥 Trending Runners'  },
    discovery:  { direction: 'right', width: 'w-96',             title: '⚡ Auto Discovery'     },
    watchlist:  { direction: 'right', width: 'w-full max-w-4xl', title: '👁️ Watchlist'          },
    top100:     { direction: 'right', width: 'w-full max-w-4xl', title: '🏆 Top 100 Community'  },
    premium100: { direction: 'right', width: 'w-full max-w-4xl', title: '👑 Premium Elite 100'  },
    quickadd:   { direction: 'right', width: 'w-96',             title: '➕ Quick Add Wallet'   },
    profile:    { direction: 'right', width: 'w-96',             title: 'Profile'               },
    help:       { direction: 'right', width: 'w-96',             title: '❓ Help & Support'     },
    recents:    { direction: 'right', width: 'w-[480px]',        title: '🕐 Recent Analyses'    },
  }[panelId] || { direction: 'left', width: 'w-96', title: '' });

  // ── Active analysis tracking ──────────────────────────────────────────────
  const [activeAnalyses, setActiveAnalyses] = useState({ trending: null, discovery: null, analyze: null });
  const [showActiveAnalyses, setShowActiveAnalyses] = useState(false);

  useEffect(() => { activeAnalysesRef.current = activeAnalyses; }, [activeAnalyses]);

  // ── Redis persistence ────────────────────────────────────────────────────────
  const saveActiveAnalysisToRedis = useCallback(async (type, analysis) => {
    if (!userId || !isAuthenticated) return;
    try {
      const authToken = getAccessToken();
      await fetch(`${API_URL}/api/user/active-analysis`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
        body: JSON.stringify({ user_id: userId, type, analysis: { ...analysis, timestamp: Date.now() } })
      });
    } catch (e) { console.error('Failed to save active analysis to Redis:', e); }
  }, [userId, isAuthenticated, getAccessToken, API_URL]);

  const deleteActiveAnalysisFromRedis = useCallback(async (type) => {
    if (!userId || !isAuthenticated) return;
    try {
      const authToken = getAccessToken();
      await fetch(`${API_URL}/api/user/active-analysis/${type}?user_id=${userId}`, {
        method: 'DELETE', headers: { Authorization: `Bearer ${authToken}` }
      });
    } catch (e) { console.error('Failed to delete active analysis from Redis:', e); }
  }, [userId, isAuthenticated, getAccessToken, API_URL]);

  const loadActiveAnalysesFromRedis = useCallback(async () => {
    if (!userId || !isAuthenticated) return;
    try {
      const authToken = getAccessToken();
      const res  = await fetch(`${API_URL}/api/user/active-analyses?user_id=${userId}`, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      const data = await res.json();
      if (data.success && data.analyses) setActiveAnalyses(prev => ({ ...prev, ...data.analyses }));
    } catch (e) { console.error('Failed to load active analyses from Redis:', e); }
  }, [userId, isAuthenticated, getAccessToken, API_URL]);

  // ── Analysis lifecycle ────────────────────────────────────────────────────
  const startAnalysis = useCallback(async (type, data) => {
    const newAnalysis = {
      jobId:     data.jobId,
      type:      data.analysisType || type,
      startTime: Date.now(),
      progress:  { current: 0, total: data.total || 1, phase: 'Starting…' },
      tokens:    data.tokens || [],
      ...data,
    };
    setActiveAnalyses(prev => ({ ...prev, [type]: newAnalysis }));
    saveActiveAnalysisToRedis(type, newAnalysis);
    // Auto-show the active analyses box so user can see it running
    setShowActiveAnalyses(true);
  }, [saveActiveAnalysisToRedis]);

  const updateAnalysisProgress = useCallback((type, progress) => {
    setActiveAnalyses(prev => {
      const updated = { ...prev, [type]: prev[type] ? { ...prev[type], progress } : null };
      if (updated[type]) saveActiveAnalysisToRedis(type, updated[type]);
      else deleteActiveAnalysisFromRedis(type);
      return updated;
    });
  }, [saveActiveAnalysisToRedis, deleteActiveAnalysisFromRedis]);

  const completeAnalysis = useCallback(async (type, results) => {
    setShowActiveAnalyses(false);
    if (pollIntervalsRef.current[type]) {
      clearInterval(pollIntervalsRef.current[type]);
      delete pollIntervalsRef.current[type];
    }
    setActiveAnalyses(prev => ({ ...prev, [type]: null }));
    deleteActiveAnalysisFromRedis(type);
    handleResultsReady(results, type);
  }, [handleResultsReady, deleteActiveAnalysisFromRedis]);

  const cancelAnalysis = useCallback(async (type) => {
    if (cancellingRef.current.has(type)) return;
    cancellingRef.current.add(type);

    const analysis = activeAnalysesRef.current[type];
    if (!analysis?.jobId) { cancellingRef.current.delete(type); return; }

    if (pollIntervalsRef.current[type]) {
      clearInterval(pollIntervalsRef.current[type]);
      delete pollIntervalsRef.current[type];
    }
    completedJobsRef.current.add(analysis.jobId);

    setActiveAnalyses(prev => { const u = { ...prev }; delete u[type]; return u; });
    setShowActiveAnalyses(false);
    activeAnalysesRef.current = { ...activeAnalysesRef.current, [type]: null };

    deleteActiveAnalysisFromRedis(type).catch(() => {});

    try {
      const authToken = getAccessToken();
      const ctrl = new AbortController();
      const tid  = setTimeout(() => ctrl.abort(), 5000);
      await fetch(`${API_URL}/api/wallets/jobs/${analysis.jobId}/cancel`, {
        method: 'POST', headers: { Authorization: `Bearer ${authToken}` }, signal: ctrl.signal
      });
      clearTimeout(tid);
    } catch (e) { /* ignore — local state already cleaned up */ }

    cancellingRef.current.delete(type);
  }, [getAccessToken, API_URL, deleteActiveAnalysisFromRedis]);

  // ── Load on mount ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (isAuthenticated && userId) loadActiveAnalysesFromRedis();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, userId]);

  // ── Global poll — ALL types including analyze ─────────────────────────────
  useEffect(() => {
    if (!isAuthenticated) return;

    const intervalId = setInterval(async () => {
      const authToken = getAccessToken();
      if (!authToken) return;

      const currentAnalyses = activeAnalysesRef.current;
      const hasActive = Object.values(currentAnalyses).some(Boolean);
      if (!hasActive) return;

      for (const [type, analysis] of Object.entries(currentAnalyses)) {
        if (!analysis?.jobId) continue;
        if (completedJobsRef.current.has(analysis.jobId)) continue;

        try {
          const res  = await fetch(`${API_URL}/api/wallets/jobs/${analysis.jobId}/progress`, {
            headers: { Authorization: `Bearer ${authToken}` }
          });
          const data = await res.json();
          if (!data.success) continue;

          // Queue position update
          if (data.queue_position) {
            setActiveAnalyses(prev => {
              if (!prev[type]) return prev;
              return { ...prev, [type]: { ...prev[type], in_queue: true, queue_position: data.queue_position, estimated_wait: data.estimated_wait } };
            });
          }

          if (data.status === 'completed') {
            completedJobsRef.current.add(analysis.jobId);
            const resultRes  = await fetch(`${API_URL}/api/wallets/jobs/${analysis.jobId}`, {
              headers: { Authorization: `Bearer ${authToken}` }
            });
            const resultData = await resultRes.json();
            const resultType =
              type === 'analyze'
                ? (analysis.tokens?.length > 1 ? 'batch-token' : 'single-token')
                : type === 'trending' ? 'trending-batch'
                : type;
            await completeAnalysis(type, { ...resultData, result_type: resultType });
            setDashboardRefreshKey(k => k + 1);

          } else if (data.status === 'failed') {
            setActiveAnalyses(prev => ({ ...prev, [type]: null }));
            deleteActiveAnalysisFromRedis(type);

          } else {
            setActiveAnalyses(prev => {
              if (!prev[type]) return prev;
              return {
                ...prev,
                [type]: {
                  ...prev[type],
                  progress: {
                    current: data.tokens_completed || 0,
                    total:   data.tokens_total || 1,
                    phase:   data.phase || '',
                  },
                  in_queue:       data.queue_position ? true : false,
                  queue_position: data.queue_position,
                  estimated_wait: data.estimated_wait,
                }
              };
            });
          }
        } catch (e) { console.error(`Poll error for ${type}:`, e); }
      }
    }, POLL_INTERVAL_MS);

    pollIntervalsRef.current['__global'] = intervalId;
    return () => clearInterval(intervalId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, API_URL, getAccessToken, completeAnalysis, deleteActiveAnalysisFromRedis]);

  const activeCount = Object.values(activeAnalyses).filter(Boolean).length;

  // ── Formatters ────────────────────────────────────────────────────────────
  const formatNumber = (num) => {
    if (!num) return '0';
    if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
    if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
    if (num >= 1e3) return `$${(num / 1e3).toFixed(2)}K`;
    return `$${num.toFixed(2)}`;
  };
  const formatPrice = (price) => {
    if (!price) return '$0';
    if (price < 0.000001) return `$${price.toExponential(2)}`;
    if (price < 0.01)     return `$${price.toFixed(6)}`;
    if (price < 1)        return `$${price.toFixed(4)}`;
    return `$${price.toFixed(2)}`;
  };

  // ── Points ────────────────────────────────────────────────────────────────
  const awardPoints = async (actionType, metadata = {}) => {
    try {
      const token = getAccessToken();
      await fetch(`${API_URL}/api/referral-points/points/award`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_type: actionType, metadata })
      });
      loadUserPoints();
    } catch (e) { console.error('Points award error:', e); }
  };

  const loadUserPoints = async () => {
    if (!userId) return;
    try {
      const token = getAccessToken();
      const res   = await fetch(`${API_URL}/api/referral-points/dashboard`, { headers: { 'Authorization': `Bearer ${token}` } });
      const data  = await res.json();
      if (data.success) setUserPoints(data.points?.total || 0);
    } catch (e) { console.error('Load points error:', e); }
  };

  useEffect(() => {
    if (isAuthenticated && userId) { loadUserPoints(); awardPoints('daily_login'); }
  }, [isAuthenticated, userId]);

  // ── Click-outside dropdown ────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) setShowDropdown(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // ── Search (debounced + manual trigger) ──────────────────────────────────
  const [searchTrigger, setSearchTrigger] = useState(0);
  const fireSearch = useCallback(() => setSearchTrigger(t => t + 1), []);

  useEffect(() => {
    const doSearch = async () => {
      if (searchQuery.length < 2) { setSearchResults([]); setShowDropdown(false); return; }
      setIsSearching(true);
      setShowDropdown(true);
      try {
        const res  = await fetch(`${API_URL}/api/tokens/search?query=${encodeURIComponent(searchQuery)}`);
        const data = await res.json();
        if (data.success) setSearchResults(data.tokens || []);
      } catch (e) { console.error('Search error:', e); setSearchResults([]); }
      setIsSearching(false);
    };
    let timer;
    if (searchTrigger > 0) { doSearch(); }
    else { timer = setTimeout(doSearch, 300); }
    return () => clearTimeout(timer);
  }, [searchQuery, searchTrigger, API_URL]);

  // ── Token selection ───────────────────────────────────────────────────────
  const toggleTokenSelection = (token) => {
    const key = (t) => `${t.address?.toLowerCase()}-${t.chain}`;
    const isSelected = selectedTokens.some(t => key(t) === key(token));
    if (isSelected) {
      setSelectedTokens(selectedTokens.filter(t => key(t) !== key(token)));
    } else {
      setSelectedTokens([...selectedTokens, token]);
      if (!tokenSettings[token.address]) {
        setTokenSettings(prev => ({ ...prev, [token.address]: { daysBack: 7, candleSize: '5m', tMinusWindow: 4, tPlusWindow: 2 } }));
      }
    }
    setShowDropdown(false);
    setSearchQuery('');
  };

  const removeToken = (address, chain) =>
    setSelectedTokens(selectedTokens.filter(t => !(t.address?.toLowerCase() === address.toLowerCase() && t.chain === chain)));

  const updateTokenSetting = (address, setting, value) =>
    setTokenSettings(prev => ({ ...prev, [address]: { ...prev[address], [setting]: value } }));

  // ── Analysis submit — fire-and-forget, routes to global poll ─────────────
  const handleAnalysisPolling = async () => {
    if (selectedTokens.length === 0) { toast.warning('Please select at least one token'); return null; }

    try {
      const authToken  = getAccessToken();
      const submitRes  = await fetch(`${API_URL}/api/wallets/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
        body: JSON.stringify({
          user_id:        userId,
          tokens:         selectedTokens.map(t => ({ address: t.address, chain: t.chain, ticker: t.ticker })),
          global_settings: useGlobalSettings
            ? { days_back: daysBack, candle_size: candleSize, t_minus_window: tMinusWindow, t_plus_window: tPlusWindow }
            : null,
          analysis_type: analysisType,
        }),
      });
      const submitData = await submitRes.json();
      if (!submitData.success) throw new Error(submitData.error || 'Failed to queue job');

      const jobId      = submitData.job_id;
      const resultType = selectedTokens.length > 1 ? 'batch-token' : 'single-token';

      // Register with global tracking — panel can close immediately
      await startAnalysis('analyze', {
        jobId,
        total:        selectedTokens.length,
        analysisType: resultType,
        tokens:       selectedTokens.map(t => t.ticker || t.symbol),
      });

      await awardPoints('run_analysis', { token_count: selectedTokens.length });
      return { jobId };

    } catch (error) {
      console.error('Analysis error:', error);
      toast.error(`Analysis failed: ${error.message}`);
      return null;
    }
  };

  // ── Watchlist helpers ─────────────────────────────────────────────────────
  const computeConsistency = (otherRunners = []) => {
    const vals = otherRunners.map(r => r.entry_to_ath_multiplier).filter(v => v != null && v > 0);
    if (vals.length < 2) return 50;
    const mean     = vals.reduce((a, b) => a + b, 0) / vals.length;
    const variance = vals.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / vals.length;
    return Math.max(0, Math.round(100 - (variance * 2)));
  };

  const addToWalletWatchlist = async (walletData) => {
    try {
      const authToken = getAccessToken();
      const res = await fetch(`${API_URL}/api/wallets/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
        body: JSON.stringify({
          user_id: userId,
          wallet: {
            wallet:              walletData.wallet_address,
            professional_score:  walletData.professional_score,
            tier:                walletData.tier,
            roi_percent:         walletData.roi_percent,
            runner_hits_30d:     walletData.runner_hits_30d,
            runner_success_rate: walletData.runner_success_rate,
            total_invested:      walletData.total_invested,
            tokens_hit:          walletData.runners_hit || [],
            roi_30d:             walletData.roi_percent,
            runners_30d:         walletData.runner_hits_30d,
            win_rate_7d:         walletData.runner_success_rate,
            consistency_score:   computeConsistency(walletData.other_runners),
            is_cross_token:      walletData.is_cross_token || false,
          }
        }),
      });
      const data = await res.json();
      if (data.success) { toast.success('Wallet added to watchlist!'); await awardPoints('add_watchlist'); }
      else toast.error(`Failed: ${data.error}`);
    } catch (e) { console.error('Add to watchlist error:', e); toast.error('Failed to add wallet to watchlist'); }
  };

  // ── Auth guard ────────────────────────────────────────────────────────────
  if (authLoading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="w-12 h-12 border-4 border-white/20 border-t-purple-500 rounded-full animate-spin" />
      </div>
    );
  }
  if (!isAuthenticated) {
    return <Auth onSignIn={signIn} onSignUp={signUp} onResetPassword={resetPassword} onUpdatePassword={updatePassword} isPasswordRecovery={false} />;
  }

  const config = getPanelConfig(openPanel);

  return (
    <div className="min-h-screen bg-black text-gray-100">
      <Toaster position="top-right" theme="dark" richColors />

      {/* ── Navbar ── */}
      <nav className="fixed top-0 w-full z-50 bg-black/80 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 py-3">
          <div className="flex justify-between items-center">
            <div className="text-xl font-bold">
              SIFTER <span className="text-purple-500">KYS</span>
            </div>

            <div className="flex gap-3 items-center">
              <WalletActivityMonitor />

              {/* ── Active Analyses pill ── */}
              {activeCount > 0 && (
                <button
                  onClick={() => setShowActiveAnalyses(!showActiveAnalyses)}
                  className="relative flex items-center gap-2 px-3 py-2 bg-green-500/20 hover:bg-green-500/30 rounded-lg transition"
                  title={`${activeCount} active analysis${activeCount > 1 ? 'es' : ''}`}
                >
                  <Activity size={15} className="text-green-400 animate-pulse" />
                  <span className="text-xs font-bold text-green-400">{activeCount}</span>
                </button>
              )}

              {/* Recent analyses */}
              <button
                onClick={() => handleOpenPanel('recents')}
                title="Recent analyses"
                className="flex items-center gap-2 px-3 py-2 bg-white/5 hover:bg-white/10 rounded-lg transition"
              >
                <Clock size={15} className={recentsLoading ? 'text-purple-400 animate-pulse' : 'text-gray-400'} />
                {recentResults.length > 0 && <span className="text-xs font-bold text-gray-300">{recentResults.length}</span>}
              </button>

              {/* ── Active Analyses dropdown ── */}
              {showActiveAnalyses && activeCount > 0 && (
                <div className="absolute right-44 top-12 w-80 bg-black/95 backdrop-blur-xl border border-white/10 rounded-xl shadow-2xl overflow-hidden z-[100]">
                  <div className="p-3 border-b border-white/10">
                    <h3 className="text-sm font-semibold flex items-center gap-2">
                      <Activity size={14} className="text-green-400" />
                      Active Analyses ({activeCount})
                    </h3>
                  </div>
                  <div className="p-2 max-h-96 overflow-y-auto">
                    {Object.entries(activeAnalyses).map(([type, analysis]) => {
                      if (!analysis) return null;
                      const isCancelling = cancellingRef.current.has(type);
                      const pct = Math.round(((analysis.progress?.current || 0) / (analysis.progress?.total || 1)) * 100);
                      return (
                        <div key={type} className="p-3 hover:bg-white/5 rounded-lg mb-2">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-sm font-semibold capitalize">
                              {type === 'analyze'   ? '🔍 Token Analysis' :
                               type === 'trending'  ? '🔥 Trending Batch' :
                               type === 'discovery' ? '⚡ Auto Discovery'  : type}
                            </span>
                            <button
                              onClick={() => cancelAnalysis(type)}
                              disabled={isCancelling}
                              className={`text-xs transition ${isCancelling ? 'text-gray-600 cursor-not-allowed' : 'text-red-400 hover:text-red-300'}`}
                            >
                              {isCancelling ? 'Cancelling…' : 'Cancel'}
                            </button>
                          </div>
                          {/* Token list for analyze jobs */}
                          {type === 'analyze' && analysis.tokens?.length > 0 && (
                            <div className="flex flex-wrap gap-1 mb-2">
                              {analysis.tokens.slice(0, 4).map((t, i) => (
                                <span key={t} className="text-xs px-1.5 py-0.5 bg-purple-500/20 text-purple-400 rounded">{t}</span>
                              ))}
                              {analysis.tokens.length > 4 && (
                                <span className="text-xs px-1.5 py-0.5 bg-white/10 text-gray-400 rounded">+{analysis.tokens.length - 4}</span>
                              )}
                            </div>
                          )}
                          <div className="text-xs text-gray-400 mb-2">{analysis.progress?.phase || 'Processing…'}</div>
                          <div className="bg-white/10 rounded-full h-1.5 mb-1">
                            <div className="bg-green-500 h-1.5 rounded-full transition-all" style={{ width: `${pct}%` }} />
                          </div>
                          <div className="flex justify-between text-xs text-gray-500">
                            <span>{analysis.progress?.current}/{analysis.progress?.total} · {pct}%</span>
                            <span>{Math.round((Date.now() - analysis.startTime) / 60000)}m elapsed</span>
                          </div>
                          {analysis.in_queue && (
                            <div className="mt-2 text-xs text-yellow-400 flex items-center gap-1">
                              <span className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse" />
                              #{analysis.queue_position || '?'} in queue
                              {analysis.estimated_wait && ` · ~${analysis.estimated_wait}m wait`}
                            </div>
                          )}
                          <button
                            onClick={() => { handleOpenPanel(type === 'analyze' ? 'analyze' : type); setShowActiveAnalyses(false); }}
                            className="w-full mt-2 text-xs text-purple-400 hover:text-purple-300 text-center"
                          >
                            Open Panel →
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Points badge */}
              <div
                className="flex items-center gap-2 px-3 py-2 bg-purple-500/20 rounded-lg cursor-pointer hover:bg-purple-500/30 transition"
                onClick={() => handleOpenPanel('profile')}
              >
                <Award className="text-yellow-400" size={16} />
                <span className="text-sm font-bold">{userPoints.toLocaleString()}</span>
              </div>

              {/* Profile dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowProfileDropdown(!showProfileDropdown)}
                  className="flex items-center gap-2 px-3 py-2 bg-white/5 hover:bg-white/10 rounded-lg transition"
                >
                  <div className="w-8 h-8 bg-purple-500/20 rounded-full flex items-center justify-center">
                    <User size={16} className="text-purple-400" />
                  </div>
                  <span className="text-sm font-medium">{user?.email?.split('@')[0]}</span>
                  <ChevronDown size={16} />
                </button>
                {showProfileDropdown && (
                  <div className="absolute right-0 top-12 w-64 bg-black/95 backdrop-blur-xl border border-white/10 rounded-xl shadow-2xl overflow-hidden z-[100]">
                    <div className="p-4 border-b border-white/10">
                      <div className="text-xs text-gray-400">{user?.email}</div>
                    </div>
                    <div className="p-2">
                      <button onClick={() => handleOpenPanel('profile')} className="w-full p-2 hover:bg-white/10 rounded-lg text-left text-sm transition flex items-center gap-2">
                        <BarChart3 size={16} className="text-purple-400" /> My Dashboard
                      </button>
                      <button onClick={() => handleOpenPanel('profile')} className="w-full p-2 hover:bg-white/10 rounded-lg text-left text-sm transition flex items-center gap-2">
                        <Settings size={16} className="text-gray-400" /> Settings
                      </button>
                      <button onClick={() => handleOpenPanel('help')} className="w-full p-2 hover:bg-white/10 rounded-lg text-left text-sm transition flex items-center gap-2">
                        <HelpCircle size={16} className="text-blue-400" /> Help & Support
                      </button>
                    </div>
                    <div className="p-2 border-t border-white/10 sticky bottom-0 bg-black/95">
                      <button onClick={signOut} className="w-full p-2 hover:bg-red-500/10 rounded-lg text-left text-sm transition flex items-center gap-2 text-red-400">
                        <LogOut size={16} /> Sign Out
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <a href="https://whop.com/sifter" target="_blank" rel="noopener noreferrer"
                className="px-3 py-2 bg-purple-600 rounded-lg hover:bg-purple-700 transition text-sm">
                Upgrade
              </a>
            </div>
          </div>
        </div>
      </nav>

      {/* ── Dashboard ── */}
      <div className="pt-20 max-w-7xl mx-auto px-6 py-6">
        <DashboardHome user={user} onOpenPanel={handleOpenPanel} recentActivity={[]} />
      </div>

      {/* ── Slide-out panels ── */}
      <SlideOutPanel
        isOpen={openPanel !== null}
        onClose={handleClosePanel}
        direction={config.direction}
        width={config.width}
        title={config.title}
      >
        <Suspense fallback={<div className="flex items-center justify-center h-full"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-emerald-400"></div></div>}>
        {openPanel === 'analyze' && (
          <AnalyzePanel
            searchQuery={searchQuery}
            setSearchQuery={setSearchQuery}
            searchResults={searchResults}
            isSearching={isSearching}
            showDropdown={showDropdown}
            searchRef={searchRef}
            selectedTokens={selectedTokens}
            toggleTokenSelection={toggleTokenSelection}
            removeToken={removeToken}
            analysisType={analysisType}
            setAnalysisType={setAnalysisType}
            useGlobalSettings={useGlobalSettings}
            setUseGlobalSettings={setUseGlobalSettings}
            tokenSettings={tokenSettings}
            updateTokenSetting={updateTokenSetting}
            daysBack={daysBack}
            setDaysBack={setDaysBack}
            candleSize={candleSize}
            setCandleSize={setCandleSize}
            tMinusWindow={tMinusWindow}
            setTMinusWindow={setTMinusWindow}
            tPlusWindow={tPlusWindow}
            setTPlusWindow={setTPlusWindow}
            handleAnalysisStreaming={handleAnalysisPolling}
            isAnalyzing={!!activeAnalyses.analyze}
            onClose={handleClosePanel}
            setSelectedTokens={setSelectedTokens}
            formatNumber={formatNumber}
            formatPrice={formatPrice}
            onResultsReady={handleResultsReady}
            onRefreshSearch={fireSearch}
            activeAnalysis={activeAnalyses.analyze}
            onMinimize={() => { handleClosePanel(); setShowActiveAnalyses(true); }}
          />
        )}

        {openPanel === 'trending' && (
          <TrendingPanel
            userId={userId} apiUrl={API_URL}
            onClose={handleClosePanel}
            formatNumber={formatNumber} formatPrice={formatPrice}
            onResultsReady={handleResultsReady}
            onAnalysisStart={(data) => startAnalysis('trending', data)}
            onAnalysisProgress={(progress) => updateAnalysisProgress('trending', progress)}
            onAnalysisComplete={(results) => completeAnalysis('trending', results)}
            activeAnalysis={activeAnalyses.trending}
            cachedRunners={cachedTrendingRunners}
            onRunnersLoaded={saveTrendingToCache}
            onMinimize={() => { handleClosePanel(); setShowActiveAnalyses(true); }}
          />
        )}

        {openPanel === 'discovery' && (
          <DiscoveryPanel
            userId={userId} apiUrl={API_URL}
            onClose={handleClosePanel}
            onAddToWatchlist={addToWalletWatchlist}
            formatNumber={formatNumber}
            onResultsReady={handleResultsReady}
            onAnalysisStart={(data) => startAnalysis('discovery', data)}
            onAnalysisProgress={(progress) => updateAnalysisProgress('discovery', progress)}
            onAnalysisComplete={(results) => completeAnalysis('discovery', results)}
            activeAnalysis={activeAnalyses.discovery}
            onMinimize={() => { handleClosePanel(); setShowActiveAnalyses(true); }}
          />
        )}

        {openPanel === 'watchlist' && (
          <WatchlistPanel userId={userId} apiUrl={API_URL}
            onConfigure={(wallet) => setAlertSettingsWallet(wallet.wallet_address)} />
        )}
        {openPanel === 'top100' && (
          <Top100CommunityPanel userId={userId} apiUrl={API_URL} onAddToWatchlist={addToWalletWatchlist} />
        )}
        {openPanel === 'premium100' && (
          <PremiumElite100Panel userId={userId} apiUrl={API_URL} isPremium={false}
            onUpgrade={() => window.open('https://whop.com/sifter', '_blank')} onAddToWatchlist={addToWalletWatchlist} />
        )}
        {openPanel === 'quickadd' && (
          <QuickAddWalletPanel userId={userId} apiUrl={API_URL} onSuccess={handleClosePanel} getAccessToken={getAccessToken} />
        )}
        {openPanel === 'profile' && (
          <ProfilePanel user={user} userId={userId} apiUrl={API_URL}
            onNavigate={handleOpenPanel} onSignOut={signOut}
            getAccessToken={getAccessToken} refreshKey={dashboardRefreshKey} />
        )}
        {openPanel === 'help' && <HelpSupportPanel userId={userId} apiUrl={API_URL} />}
        {openPanel === 'recents' && (
          <RecentResultsList
            recents={recentResults} loading={recentsLoading} error={recentsError}
            onOpen={(entry) => { handleClosePanel(); setTimeout(() => setResultsPanel({ isOpen: true, type: entry.resultType, data: entry.data }), 150); }}
            onRemove={removeRecent} onClear={clearRecents} onRefresh={refreshRecents}
          />
        )}
        </Suspense>
      </SlideOutPanel>

      {/* ── Results overlay ── */}
      <Suspense fallback={null}>
      {resultsPanel.isOpen && (
        <ResultsPanel
          data={resultsPanel.data} resultType={resultsPanel.type}
          onClose={() => setResultsPanel({ isOpen: false, type: null, data: null })}
          onAddToWatchlist={addToWalletWatchlist}
          onSimulate={(walletData) => setSimulatorWallet(walletData)}
          formatNumber={formatNumber} formatPrice={formatPrice}
        />
      )}

      {simulatorWallet && (
        <SimulatorModal walletData={simulatorWallet} onClose={() => setSimulatorWallet(null)}
          apiUrl={API_URL} getAccessToken={getAccessToken} />
      )}

      {alertSettingsWallet && (
        <WalletAlertSettings walletAddress={alertSettingsWallet} userId={userId} apiUrl={API_URL}
          onClose={() => setAlertSettingsWallet(null)} />
      )}

      {replacementData && (
        <WalletReplacementModal
          currentWallet={replacementData.wallet} suggestions={replacementData.suggestions}
          onReplace={async (newWallet) => {
            try {
              const authToken = getAccessToken();
              const res = await fetch(`${API_URL}/api/wallets/watchlist/replace`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
                body: JSON.stringify({ user_id: userId, old_wallet: replacementData.wallet.wallet_address, new_wallet: newWallet.wallet })
              });
              const data = await res.json();
              if (data.success) { toast.success('Wallet replaced successfully!'); setReplacementData(null); }
              else toast.error(`Failed: ${data.error}`);
            } catch (e) { toast.error('Failed to replace wallet'); }
          }}
          onDismiss={() => setReplacementData(null)}
        />
      )}
      </Suspense>

      <footer className="fixed bottom-0 w-full bg-black/80 border-t border-white/10 py-2 z-30">
        <div className="max-w-7xl mx-auto px-6 text-center text-xs text-gray-500">
          © 2026 Sifter KYS • @SifterKYS • Terms • Privacy
        </div>
      </footer>
    </div>
  );
}