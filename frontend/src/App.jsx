import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from './contexts/AuthContext';
import { User, ChevronDown, Settings, HelpCircle, LogOut, BarChart3, Award, Clock } from 'lucide-react';

import DashboardHome      from './components/dashboard/DashboardHome';
import SlideOutPanel      from './components/panels/SlideOutPanel';
import AnalyzePanel       from './components/panels/AnalyzePanel';
import TrendingPanel      from './components/panels/TrendingPanel';
import DiscoveryPanel     from './components/panels/DiscoveryPanel';
import WatchlistPanel     from './components/panels/WatchlistPanel';
import Top100CommunityPanel  from './components/panels/Top100CommunityPanel';
import PremiumElite100Panel  from './components/panels/PremiumElite100Panel';
import QuickAddWalletPanel   from './components/panels/QuickAddWalletPanel';
import ProfilePanel       from './components/panels/ProfilePanel';
import HelpSupportPanel   from './components/panels/HelpSupportPanel';
import ResultsPanel       from './components/panels/ResultsPanel';
import RecentResultsList  from './components/RecentResultsList';
import { useRecents }     from './components/hooks/useRecentResults';

import WalletActivityMonitor  from './WalletActivityMonitor';
import WalletAlertSettings    from './WalletAlertSettings';
import WalletReplacementModal from './WalletReplacementModal';
import Auth from './components/Auth';

// ─── Constants ────────────────────────────────────────────────────────────────
const POLL_INTERVAL_MS  = 3_000;
const MAX_POLL_ATTEMPTS = 400;          // 400 × 3 s = 20 minutes

export default function SifterKYS() {
  const {
    user, loading: authLoading, isAuthenticated,
    signOut, getAccessToken, signIn, signUp, resetPassword, updatePassword
  } = useAuth();

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';
  const userId  = user?.id;

  const [openPanel, setOpenPanel]     = useState(null);
  const [showProfileDropdown, setShowProfileDropdown] = useState(false);
  const [resultsPanel, setResultsPanel] = useState({ isOpen: false, type: null, data: null });

  // ── Recent results (Redis-backed, cross-device) ─────────────────────────────
  const {
    recents:        recentResults,
    loading:        recentsLoading,
    error:          recentsError,
    saveResult:     addToRecents,
    removeResult:   removeRecent,
    clearAll:       clearRecents,
    refreshRecents,
  } = useRecents({ apiUrl: API_URL, userId, getAccessToken });

  // ── Search state ────────────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery]   = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedTokens, setSelectedTokens] = useState([]);
  const [isSearching, setIsSearching]   = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchRef = useRef(null);

  // ── Analysis settings state ─────────────────────────────────────────────────
  const [analysisType, setAnalysisType]         = useState('general');
  const [useGlobalSettings, setUseGlobalSettings] = useState(true);
  const [tokenSettings, setTokenSettings]       = useState({});
  const [daysBack, setDaysBack]                 = useState(7);
  const [candleSize, setCandleSize]             = useState('5m');
  const [tMinusWindow, setTMinusWindow]         = useState(4);
  const [tPlusWindow, setTPlusWindow]           = useState(2);

  const [isAnalyzing, setIsAnalyzing]           = useState(false);
  const [streamingMessage, setStreamingMessage] = useState('');

  // ── Other state ─────────────────────────────────────────────────────────────
  const [alertSettingsWallet, setAlertSettingsWallet] = useState(null);
  const [replacementData, setReplacementData]   = useState(null);
  const [dashboardRefreshKey, setDashboardRefreshKey] = useState(0);
  const [userPoints, setUserPoints]             = useState(0);

  // ── Panel helpers ───────────────────────────────────────────────────────────
  const handleOpenPanel  = (panelId) => { setOpenPanel(panelId); setShowProfileDropdown(false); };
  const handleClosePanel = ()        => setOpenPanel(null);

  /** Central handler — opens ResultsPanel AND saves to recents. */
  const handleResultsReady = useCallback((data, type) => {
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
    trending:   { direction: 'right', width: 'w-[600px]',        title: '🔥 Trending Runners'  },
    discovery:  { direction: 'right', width: 'w-96',             title: '⚡ Auto Discovery'     },
    watchlist:  { direction: 'right', width: 'w-full max-w-4xl', title: '👁️ Watchlist'          },
    top100:     { direction: 'right', width: 'w-full max-w-4xl', title: '🏆 Top 100 Community'  },
    premium100: { direction: 'right', width: 'w-full max-w-4xl', title: '👑 Premium Elite 100'  },
    quickadd:   { direction: 'right', width: 'w-96',             title: '➕ Quick Add Wallet'   },
    profile:    { direction: 'right', width: 'w-96',             title: 'Profile'               },
    help:       { direction: 'right', width: 'w-96',             title: '❓ Help & Support'     },
    recents:    { direction: 'right', width: 'w-[480px]',        title: '🕐 Recent Analyses'    },
  }[panelId] || { direction: 'left', width: 'w-96', title: '' });

  // ── Formatters ──────────────────────────────────────────────────────────────
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

  // ── Points ──────────────────────────────────────────────────────────────────
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
      const res   = await fetch(`${API_URL}/api/referral-points/dashboard`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (data.success) setUserPoints(data.points?.total || 0);
    } catch (e) { console.error('Load points error:', e); }
  };

  useEffect(() => {
    if (isAuthenticated && userId) { loadUserPoints(); awardPoints('daily_login'); }
  }, [isAuthenticated, userId]);

  // ── Click-outside to close dropdown ────────────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) setShowDropdown(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // ── Search (debounced) ──────────────────────────────────────────────────────
  const [searchTrigger, setSearchTrigger] = useState(0);

  const fireSearch = useCallback(() => {
    setSearchTrigger(t => t + 1);
  }, []);

  useEffect(() => {
    const doSearch = async () => {
      if (searchQuery.length < 2) {
        setSearchResults([]);
        setShowDropdown(false);
        return;
      }
      setIsSearching(true);
      setShowDropdown(true);
      try {
        const res  = await fetch(`${API_URL}/api/tokens/search?query=${encodeURIComponent(searchQuery)}`);
        const data = await res.json();
        if (data.success) setSearchResults(data.tokens || []);
      } catch (e) {
        console.error('Search error:', e);
        setSearchResults([]);
      }
      setIsSearching(false);
    };

    let timer;
    if (searchTrigger > 0) {
      doSearch();
    } else {
      timer = setTimeout(doSearch, 300);
    }
    return () => clearTimeout(timer);
  }, [searchQuery, searchTrigger, API_URL]);

  // ── Token selection ─────────────────────────────────────────────────────────
  const toggleTokenSelection = (token) => {
    const key = (t) => `${t.address?.toLowerCase()}-${t.chain}`;
    const isSelected = selectedTokens.some(t => key(t) === key(token));
    if (isSelected) {
      setSelectedTokens(selectedTokens.filter(t => key(t) !== key(token)));
    } else {
      setSelectedTokens([...selectedTokens, token]);
      if (!tokenSettings[token.address]) {
        setTokenSettings(prev => ({
          ...prev,
          [token.address]: { daysBack: 7, candleSize: '5m', tMinusWindow: 4, tPlusWindow: 2 },
        }));
      }
    }
    setShowDropdown(false);
    setSearchQuery('');
  };

  const removeToken = (address, chain) =>
    setSelectedTokens(selectedTokens.filter(
      t => !(t.address?.toLowerCase() === address.toLowerCase() && t.chain === chain)
    ));

  const updateTokenSetting = (address, setting, value) =>
    setTokenSettings(prev => ({ ...prev, [address]: { ...prev[address], [setting]: value } }));

  // ── Recovery helper ─────────────────────────────────────────────────────────
  const attemptJobRecovery = async (jobId, authToken) => {
    try {
      const res  = await fetch(`${API_URL}/api/wallets/jobs/${jobId}/recover`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${authToken}` },
      });
      const data = await res.json();
      if (data.results) return data.results;
    } catch (err) {
      console.warn('[RECOVER] Recovery request failed:', err);
    }
    return null;
  };

  // ── Analysis polling ────────────────────────────────────────────────────────
  const handleAnalysisPolling = async () => {
    if (selectedTokens.length === 0) { alert('Please select at least one token'); return; }

    setIsAnalyzing(true);
    setStreamingMessage(`Analyzing 0 of ${selectedTokens.length} token${selectedTokens.length !== 1 ? 's' : ''}…`);

    try {
      const authToken = getAccessToken();

      const submitRes = await fetch(`${API_URL}/api/wallets/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
        body: JSON.stringify({
          user_id:      userId,
          tokens:       selectedTokens.map(t => ({ address: t.address, chain: t.chain, ticker: t.ticker })),
          global_settings: useGlobalSettings
            ? { days_back: daysBack, candle_size: candleSize, t_minus_window: tMinusWindow, t_plus_window: tPlusWindow }
            : null,
          analysis_type: analysisType,
        }),
      });

      const submitData = await submitRes.json();
      if (!submitData.success) throw new Error(submitData.error || 'Failed to queue job');

      const jobId    = submitData.job_id;
      let pollCount  = 0;

      const pollInterval = setInterval(async () => {
        pollCount++;

        if (pollCount > MAX_POLL_ATTEMPTS) {
          clearInterval(pollInterval);
          setStreamingMessage('Analysis timed out — attempting recovery…');
          const recovered = await attemptJobRecovery(jobId, authToken);
          if (recovered) {
            handleResultsReady(recovered, 'single-token');
            setDashboardRefreshKey(k => k + 1);
            setStreamingMessage('Analysis complete (recovered)!');
          } else {
            alert('⏱️ Analysis timed out after 20 minutes. Try again or check back later.');
          }
          setIsAnalyzing(false);
          setStreamingMessage('');
          return;
        }

        try {
          const progressRes  = await fetch(`${API_URL}/api/wallets/jobs/${jobId}/progress`, {
            headers: { Authorization: `Bearer ${authToken}` },
          });
          const progressData = await progressRes.json();
          if (!progressData.success) return;

          const { status, progress, tokens_completed, tokens_total } = progressData;
          const total     = tokens_total || selectedTokens.length;
          const completed = tokens_completed ?? Math.round((progress / 100) * total);

          setStreamingMessage(`Analyzing ${completed} of ${total} token${total !== 1 ? 's' : ''}…`);

          if (status === 'completed') {
            clearInterval(pollInterval);
            const resultRes  = await fetch(`${API_URL}/api/wallets/jobs/${jobId}`, {
              headers: { Authorization: `Bearer ${authToken}` },
            });
            const resultData = await resultRes.json();
            handleResultsReady(resultData, 'single-token');
            setDashboardRefreshKey(k => k + 1);
            setStreamingMessage('Analysis complete!');
            setIsAnalyzing(false);
            await awardPoints('run_analysis', { token_count: selectedTokens.length });

          } else if (status === 'failed') {
            clearInterval(pollInterval);
            throw new Error('Analysis job failed');
          }
        } catch (pollError) {
          clearInterval(pollInterval);
          console.error('Polling error:', pollError);
          alert(`Analysis failed: ${pollError.message}`);
          setIsAnalyzing(false);
          setStreamingMessage('');
        }
      }, POLL_INTERVAL_MS);

    } catch (error) {
      console.error('Analysis error:', error);
      alert(`Analysis failed: ${error.message}`);
      setIsAnalyzing(false);
      setStreamingMessage('');
    }
  };

  // ── Watchlist ───────────────────────────────────────────────────────────────
  const addToWalletWatchlist = async (walletData) => {
    try {
      const authToken = getAccessToken();
      const res = await fetch(`${API_URL}/api/wallets/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
        body: JSON.stringify({
          user_id: userId,
          wallet: {
            wallet:               walletData.wallet_address,
            professional_score:   walletData.professional_score,
            tier:                 walletData.tier,
            roi_percent:          walletData.roi_percent,
            runner_hits_30d:      walletData.runner_hits_30d,
            runner_success_rate:  walletData.runner_success_rate,
            total_invested:       walletData.total_invested,
            tokens_hit:           walletData.runners_hit || []
          }
        }),
      });
      const data = await res.json();
      if (data.success) { alert('✅ Wallet added to watchlist!'); await awardPoints('add_watchlist'); }
      else alert(`Failed: ${data.error}`);
    } catch (e) { console.error('Add to watchlist error:', e); alert('Failed to add wallet to watchlist'); }
  };

  // ── Auth guard ──────────────────────────────────────────────────────────────
  if (authLoading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="w-12 h-12 border-4 border-white/20 border-t-purple-500 rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Auth
      onSignIn={signIn} onSignUp={signUp}
      onResetPassword={resetPassword} onUpdatePassword={updatePassword}
      isPasswordRecovery={false}
    />;
  }

  const config = getPanelConfig(openPanel);

  return (
    <div className="min-h-screen bg-black text-gray-100">

      {/* ── Navbar ── */}
      <nav className="fixed top-0 w-full z-50 bg-black/80 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 py-3">
          <div className="flex justify-between items-center">
            <div className="text-xl font-bold">
              SIFTER <span className="text-purple-500">KYS</span>
            </div>

            <div className="flex gap-3 items-center">
              <WalletActivityMonitor />

              {/* Recent analyses button */}
              <button
                onClick={() => handleOpenPanel('recents')}
                title="Recent analyses"
                className="flex items-center gap-2 px-3 py-2 bg-white/5 hover:bg-white/10 rounded-lg transition"
              >
                <Clock size={15} className={recentsLoading ? 'text-purple-400 animate-pulse' : 'text-gray-400'} />
                {recentResults.length > 0 && (
                  <span className="text-xs font-bold text-gray-300">{recentResults.length}</span>
                )}
              </button>

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
                      <div className="font-semibold">{user?.email?.split('@')[0]}</div>
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
                    <div className="p-2 border-t border-white/10">
                      <button onClick={signOut} className="w-full p-2 hover:bg-red-500/10 rounded-lg text-left text-sm transition flex items-center gap-2 text-red-400">
                        <LogOut size={16} /> Sign Out
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <a
                href="https://whop.com/sifter"
                target="_blank" rel="noopener noreferrer"
                className="px-3 py-2 bg-purple-600 rounded-lg hover:bg-purple-700 transition text-sm"
              >
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
            isAnalyzing={isAnalyzing}
            streamingMessage={streamingMessage}
            onClose={handleClosePanel}
            setSelectedTokens={setSelectedTokens}
            formatNumber={formatNumber}
            formatPrice={formatPrice}
            onResultsReady={handleResultsReady}
            onRefreshSearch={fireSearch}
          />
        )}

        {openPanel === 'trending' && (
          <TrendingPanel
            userId={userId} apiUrl={API_URL}
            onClose={handleClosePanel}
            formatNumber={formatNumber} formatPrice={formatPrice}
            onResultsReady={handleResultsReady}
          />
        )}

        {openPanel === 'discovery' && (
          <DiscoveryPanel
            userId={userId} apiUrl={API_URL}
            onClose={handleClosePanel}
            onAddToWatchlist={addToWalletWatchlist}
            formatNumber={formatNumber}
            onResultsReady={handleResultsReady}
          />
        )}

        {openPanel === 'watchlist' && (
          <WatchlistPanel
            userId={userId} apiUrl={API_URL}
            onConfigure={(wallet) => setAlertSettingsWallet(wallet.wallet_address)}
          />
        )}

        {openPanel === 'top100' && (
          <Top100CommunityPanel userId={userId} apiUrl={API_URL} onAddToWatchlist={addToWalletWatchlist} />
        )}

        {openPanel === 'premium100' && (
          <PremiumElite100Panel
            userId={userId} apiUrl={API_URL}
            isPremium={false}
            onUpgrade={() => window.open('https://whop.com/sifter', '_blank')}
            onAddToWatchlist={addToWalletWatchlist}
          />
        )}

        {/* ✅ getAccessToken now passed so auth header is sent — no more "user_id required" */}
        {openPanel === 'quickadd' && (
          <QuickAddWalletPanel
            userId={userId}
            apiUrl={API_URL}
            onSuccess={handleClosePanel}
            getAccessToken={getAccessToken}
          />
        )}

        {openPanel === 'profile' && (
          <ProfilePanel
            user={user} userId={userId} apiUrl={API_URL}
            onNavigate={handleOpenPanel} onSignOut={signOut}
            getAccessToken={getAccessToken} refreshKey={dashboardRefreshKey}
          />
        )}

        {openPanel === 'help' && (
          <HelpSupportPanel userId={userId} apiUrl={API_URL} />
        )}

        {openPanel === 'recents' && (
          <RecentResultsList
            recents={recentResults}
            loading={recentsLoading}
            error={recentsError}
            onOpen={(entry) => {
              handleClosePanel();
              setTimeout(() => {
                setResultsPanel({ isOpen: true, type: entry.resultType, data: entry.data });
              }, 150);
            }}
            onRemove={removeRecent}
            onClear={clearRecents}
            onRefresh={refreshRecents}
          />
        )}
      </SlideOutPanel>

      {/* ── Results overlay ── */}
      {resultsPanel.isOpen && (
        <ResultsPanel
          data={resultsPanel.data}
          resultType={resultsPanel.type}
          onClose={() => setResultsPanel({ isOpen: false, type: null, data: null })}
          onAddToWatchlist={addToWalletWatchlist}
          formatNumber={formatNumber}
          formatPrice={formatPrice}
        />
      )}

      {/* ── Analysis in-progress overlay ── */}
      {isAnalyzing && streamingMessage && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60] flex items-center justify-center">
          <div className="bg-gradient-to-br from-gray-900 to-black border border-white/10 rounded-xl p-6 max-w-md mx-4">
            <div className="flex flex-col items-center gap-4">
              <div className="w-12 h-12 border-4 border-white/20 border-t-purple-500 rounded-full animate-spin" />
              <p className="text-sm text-gray-300 text-center">{streamingMessage}</p>
              <p className="text-xs text-gray-600 text-center">Times out after 20 min — auto-recovery triggers on timeout</p>
            </div>
          </div>
        </div>
      )}

      <footer className="fixed bottom-0 w-full bg-black/80 border-t border-white/10 py-2 z-30">
        <div className="max-w-7xl mx-auto px-6 text-center text-xs text-gray-500">
          © 2026 Sifter.io • support@sifter.io • @SifterIO • Terms • Privacy
        </div>
      </footer>

      {alertSettingsWallet && (
        <WalletAlertSettings
          walletAddress={alertSettingsWallet} userId={userId} apiUrl={API_URL}
          onClose={() => setAlertSettingsWallet(null)}
        />
      )}

      {replacementData && (
        <WalletReplacementModal
          currentWallet={replacementData.wallet}
          suggestions={replacementData.suggestions}
          onReplace={async (newWallet) => {
            try {
              const authToken = getAccessToken();
              const res = await fetch(`${API_URL}/api/wallets/watchlist/replace`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
                body: JSON.stringify({ user_id: userId, old_wallet: replacementData.wallet.wallet_address, new_wallet: newWallet.wallet })
              });
              const data = await res.json();
              if (data.success) { alert('✅ Wallet replaced successfully!'); setReplacementData(null); }
              else alert(`Failed: ${data.error}`);
            } catch (e) { console.error('Replace error:', e); alert('Failed to replace wallet'); }
          }}
          onDismiss={() => setReplacementData(null)}
        />
      )}
    </div>
  );
}