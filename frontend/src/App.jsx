import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from './contexts/AuthContext';
import { User, ChevronDown, Settings, HelpCircle, LogOut, BarChart3, Award } from 'lucide-react';

import DashboardHome from './components/dashboard/DashboardHome';
import SlideOutPanel from './components/panels/SlideOutPanel';
import AnalyzePanel from './components/panels/AnalyzePanel';
import TrendingPanel from './components/panels/TrendingPanel';
import DiscoveryPanel from './components/panels/DiscoveryPanel';
import WatchlistPanel from './components/panels/WatchlistPanel';
import Top100CommunityPanel from './components/panels/Top100CommunityPanel';
import PremiumElite100Panel from './components/panels/PremiumElite100Panel';
import QuickAddWalletPanel from './components/panels/QuickAddWalletPanel';
import ProfilePanel from './components/panels/ProfilePanel';
import HelpSupportPanel from './components/panels/HelpSupportPanel';

import WalletActivityMonitor from './WalletActivityMonitor';
import WalletAlertSettings from './WalletAlertSettings';
import WalletReplacementModal from './WalletReplacementModal';
import Auth from './components/Auth';

export default function SifterKYS() {
  const { user, loading: authLoading, isAuthenticated, signOut, getAccessToken, signIn, signUp, resetPassword, updatePassword } = useAuth();

  const [openPanel, setOpenPanel] = useState(null);
  const [showProfileDropdown, setShowProfileDropdown] = useState(false);

  const [mode, setMode] = useState('wallet');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedTokens, setSelectedTokens] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchRef = useRef(null);

  const [analysisType, setAnalysisType] = useState('general');
  const [useGlobalSettings, setUseGlobalSettings] = useState(true);
  const [tokenSettings, setTokenSettings] = useState({});
  const [daysBack, setDaysBack] = useState(7);
  const [candleSize, setCandleSize] = useState('5m');
  const [tMinusWindow, setTMinusWindow] = useState(4);
  const [tPlusWindow, setTPlusWindow] = useState(2);

  const [walletResults, setWalletResults] = useState(null);
  const [batchResults, setBatchResults] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [streamingMessage, setStreamingMessage] = useState('');

  const [alertSettingsWallet, setAlertSettingsWallet] = useState(null);
  const [replacementModalWallet, setReplacementModalWallet] = useState(null);
  const [replacementData, setReplacementData] = useState(null);
  
  const [userPoints, setUserPoints] = useState(0);

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';
  const userId = user?.id;

  const handleOpenPanel = (panelId) => {
    setOpenPanel(panelId);
    setShowProfileDropdown(false);
  };

  const handleClosePanel = () => {
    setOpenPanel(null);
  };

  const getPanelConfig = (panelId) => {
    const configs = {
      analyze: { direction: 'left', width: 'w-96', title: '🔍 Analyze Tokens' },
      trending: { direction: 'right', width: 'w-[600px]', title: '🔥 Trending Runners' },
      discovery: { direction: 'right', width: 'w-96', title: '⚡ Auto Discovery' },
      watchlist: { direction: 'right', width: 'w-full max-w-4xl', title: '👁️ Watchlist' },
      top100: { direction: 'right', width: 'w-full max-w-4xl', title: '🏆 Top 100 Community' },
      premium100: { direction: 'right', width: 'w-full max-w-4xl', title: '👑 Premium Elite 100' },
      quickadd: { direction: 'right', width: 'w-96', title: '➕ Quick Add Wallet' },
      profile: { direction: 'right', width: 'w-96', title: 'Profile' },
      help: { direction: 'right', width: 'w-96', title: '❓ Help & Support' },
    };
    return configs[panelId] || configs.analyze;
  };

  const formatNumber = (num) => {
    if (!num) return '0';
    if (num >= 1000000000) return `$${(num / 1000000000).toFixed(2)}B`;
    if (num >= 1000000) return `$${(num / 1000000).toFixed(2)}M`;
    if (num >= 1000) return `$${(num / 1000).toFixed(2)}K`;
    return `$${num.toFixed(2)}`;
  };

  const formatPrice = (price) => {
    if (!price) return '$0';
    if (price < 0.000001) return `$${price.toExponential(2)}`;
    if (price < 0.01) return `$${price.toFixed(6)}`;
    if (price < 1) return `$${price.toFixed(4)}`;
    return `$${price.toFixed(2)}`;
  };

  const awardPoints = async (actionType, metadata = {}) => {
    try {
      const token = getAccessToken();
      await fetch(`${API_URL}/api/referral-points/points/award`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          action_type: actionType,
          metadata
        })
      });
      loadUserPoints();
    } catch (error) {
      console.error('Points award error:', error);
    }
  };

  const loadUserPoints = async () => {
    if (!userId) return;
    
    try {
      const token = getAccessToken();
      const response = await fetch(`${API_URL}/api/referral-points/dashboard`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await response.json();
      
      if (data.success) {
        setUserPoints(data.points?.total || 0);
      }
    } catch (error) {
      console.error('Load points error:', error);
    }
  };

  useEffect(() => {
    if (isAuthenticated && userId) {
      loadUserPoints();
      awardPoints('daily_login');
    }
  }, [isAuthenticated, userId]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const searchTokens = async () => {
      if (searchQuery.length < 2) {
        setSearchResults([]);
        setShowDropdown(false);
        return;
      }

      setIsSearching(true);
      setShowDropdown(true);

      try {
        const response = await fetch(
          `${API_URL}/api/tokens/search?query=${encodeURIComponent(searchQuery)}`
        );
        const data = await response.json();

        if (data.success) {
          setSearchResults(data.tokens || []);
        }
      } catch (error) {
        console.error('Search error:', error);
        setSearchResults([]);
      }

      setIsSearching(false);
    };

    const debounceTimer = setTimeout(searchTokens, 300);
    return () => clearTimeout(debounceTimer);
  }, [searchQuery, API_URL]);

  const toggleTokenSelection = (token) => {
    const isSelected = selectedTokens.some(
      (t) => t.address.toLowerCase() === token.address.toLowerCase() && t.chain === token.chain
    );

    if (isSelected) {
      setSelectedTokens(
        selectedTokens.filter(
          (t) => !(t.address.toLowerCase() === token.address.toLowerCase() && t.chain === token.chain)
        )
      );
    } else {
      setSelectedTokens([...selectedTokens, token]);
      if (!tokenSettings[token.address]) {
        setTokenSettings({
          ...tokenSettings,
          [token.address]: {
            daysBack: 7,
            candleSize: '5m',
            tMinusWindow: 4,
            tPlusWindow: 2,
          },
        });
      }
    }

    setShowDropdown(false);
    setSearchQuery('');
  };

  const removeToken = (address, chain) => {
    setSelectedTokens(
      selectedTokens.filter(
        (t) => !(t.address.toLowerCase() === address.toLowerCase() && t.chain === chain)
      )
    );
  };

  const updateTokenSetting = (address, setting, value) => {
    setTokenSettings({
      ...tokenSettings,
      [address]: {
        ...tokenSettings[address],
        [setting]: value,
      },
    });
  };

  // ========== ANALYSIS FUNCTION - RQ POLLING ==========
  const handleAnalysisPolling = async () => {
    if (selectedTokens.length === 0) {
      alert('Please select at least one token');
      return;
    }

    setIsAnalyzing(true);
    setWalletResults(null);
    setStreamingMessage(`Analyzing 0 of ${selectedTokens.length} token${selectedTokens.length !== 1 ? 's' : ''}...`);

    try {
      const token = getAccessToken();

      const submitRes = await fetch(`${API_URL}/api/wallets/analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          user_id: userId,
          tokens: selectedTokens.map((t) => ({
            address: t.address,
            chain: t.chain,
            ticker: t.ticker,
          })),
          global_settings: useGlobalSettings
            ? { days_back: daysBack, candle_size: candleSize, t_minus_window: tMinusWindow, t_plus_window: tPlusWindow }
            : null,
          analysis_type: analysisType,
        }),
      });

      const submitData = await submitRes.json();
      if (!submitData.success) throw new Error(submitData.error || 'Failed to queue job');

      const jobId = submitData.job_id;

      const pollInterval = setInterval(async () => {
        try {
          const progressRes = await fetch(`${API_URL}/api/wallets/jobs/${jobId}/progress`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          const progressData = await progressRes.json();

          if (!progressData.success) return;

          const { status, progress, phase, tokens_completed, tokens_total } = progressData;

          const total = tokens_total || selectedTokens.length;
          const completed = tokens_completed ?? Math.round((progress / 100) * total);

          setStreamingMessage(
            `Analyzing ${completed} of ${total} token${total !== 1 ? 's' : ''}...`
          );

          if (status === 'completed') {
            clearInterval(pollInterval);

            const resultRes = await fetch(`${API_URL}/api/wallets/jobs/${jobId}`, {
              headers: { Authorization: `Bearer ${token}` },
            });
            const resultData = await resultRes.json();

            setWalletResults(resultData);
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
        }
      }, 3000);

    } catch (error) {
      console.error('Analysis error:', error);
      alert(`Analysis failed: ${error.message}`);
      setIsAnalyzing(false);
    }
  };

  // ========== WATCHLIST FUNCTIONS ==========
  const addToWalletWatchlist = async (walletData) => {
    try {
      const token = getAccessToken();
      const response = await fetch(`${API_URL}/api/wallets/watchlist/add`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          user_id: userId,
          wallet_address: walletData.wallet_address || walletData.wallet,
          tags: walletData.tags || [],
          notes: walletData.notes || '',
        }),
      });

      const data = await response.json();

      if (data.success) {
        alert('✅ Wallet added to watchlist!');
        await awardPoints('add_watchlist');
      } else {
        alert(`Failed: ${data.error}`);
      }
    } catch (error) {
      console.error('Add to watchlist error:', error);
      alert('Failed to add wallet to watchlist');
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="w-12 h-12 border-4 border-white/20 border-t-purple-500 rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Auth
      onSignIn={signIn}
      onSignUp={signUp}
      onResetPassword={resetPassword}
      onUpdatePassword={updatePassword}
      isPasswordRecovery={false}
    />;
  }

  const config = getPanelConfig(openPanel);

  return (
    <div className="min-h-screen bg-black text-gray-100">
      {/* ========== NAVBAR ========== */}
      <nav className="fixed top-0 w-full z-50 bg-black/80 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 py-3">
          <div className="flex justify-between items-center">
            <div className="text-xl font-bold">
              SIFTER <span className="text-purple-500">KYS</span>
            </div>

            <div className="flex gap-3 items-center">
              <WalletActivityMonitor />

              <div className="flex items-center gap-2 px-3 py-2 bg-purple-500/20 rounded-lg cursor-pointer hover:bg-purple-500/30 transition"
                   onClick={() => handleOpenPanel('profile')}>
                <Award className="text-yellow-400" size={16} />
                <span className="text-sm font-bold">{userPoints.toLocaleString()}</span>
              </div>

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
                      <button
                        onClick={() => handleOpenPanel('profile')}
                        className="w-full p-2 hover:bg-white/10 rounded-lg text-left text-sm transition flex items-center gap-2"
                      >
                        <BarChart3 size={16} className="text-purple-400" />
                        My Dashboard
                      </button>
                      <button
                        onClick={() => handleOpenPanel('profile')}
                        className="w-full p-2 hover:bg-white/10 rounded-lg text-left text-sm transition flex items-center gap-2"
                      >
                        <Settings size={16} className="text-gray-400" />
                        Settings
                      </button>
                      <button
                        onClick={() => handleOpenPanel('help')}
                        className="w-full p-2 hover:bg-white/10 rounded-lg text-left text-sm transition flex items-center gap-2"
                      >
                        <HelpCircle size={16} className="text-blue-400" />
                        Help & Support
                      </button>
                    </div>

                    <div className="p-2 border-t border-white/10">
                      <button
                        onClick={signOut}
                        className="w-full p-2 hover:bg-red-500/10 rounded-lg text-left text-sm transition flex items-center gap-2 text-red-400"
                      >
                        <LogOut size={16} />
                        Sign Out
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <a
                href="https://whop.com/sifter"
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-2 bg-purple-600 rounded-lg hover:bg-purple-700 transition text-sm"
              >
                Upgrade
              </a>
            </div>
          </div>
        </div>
      </nav>

      <div className="pt-20 max-w-7xl mx-auto px-6 py-6">
        <DashboardHome
          user={user}
          onOpenPanel={handleOpenPanel}
          recentActivity={[]}
          analysisResults={walletResults}
          isAnalyzing={isAnalyzing}
        />
      </div>

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
            onClose={handleClosePanel}
            setSelectedTokens={setSelectedTokens}
            formatNumber={formatNumber}
            formatPrice={formatPrice}
          />
        )}

        {openPanel === 'trending' && (
          <TrendingPanel
            userId={userId}
            apiUrl={API_URL}
            onClose={handleClosePanel}
            formatNumber={formatNumber}
            formatPrice={formatPrice}
          />
        )}

        {openPanel === 'discovery' && (
          <DiscoveryPanel
            userId={userId}
            apiUrl={API_URL}
            onClose={handleClosePanel}
            onAddToWatchlist={addToWalletWatchlist}
            formatNumber={formatNumber}
          />
        )}

        {openPanel === 'watchlist' && (
          <WatchlistPanel
            userId={userId}
            apiUrl={API_URL}
            onConfigure={(wallet) => setAlertSettingsWallet(wallet.wallet_address)}
          />
        )}

        {openPanel === 'top100' && (
          <Top100CommunityPanel
            userId={userId}
            apiUrl={API_URL}
            onAddToWatchlist={addToWalletWatchlist}
          />
        )}

        {openPanel === 'premium100' && (
          <PremiumElite100Panel
            userId={userId}
            apiUrl={API_URL}
            isPremium={false}
            onUpgrade={() => window.open('https://whop.com/sifter', '_blank')}
            onAddToWatchlist={addToWalletWatchlist}
          />
        )}

        {openPanel === 'quickadd' && (
          <QuickAddWalletPanel
            userId={userId}
            apiUrl={API_URL}
            onSuccess={() => {
              handleClosePanel();
            }}
          />
        )}

        {openPanel === 'profile' && (
          <ProfilePanel
            user={user}
            userId={userId}
            apiUrl={API_URL}
            onNavigate={handleOpenPanel}
            onSignOut={signOut}
            getAccessToken={getAccessToken}
          />
        )}

        {openPanel === 'help' && <HelpSupportPanel userId={userId} apiUrl={API_URL} />}
      </SlideOutPanel>

      <footer className="fixed bottom-0 w-full bg-black/80 border-t border-white/10 py-2 z-30">
        <div className="max-w-7xl mx-auto px-6 text-center text-xs text-gray-500">
          © 2026 Sifter.io • support@sifter.io • @SifterIO • Terms • Privacy
        </div>
      </footer>

      {alertSettingsWallet && (
        <WalletAlertSettings
          walletAddress={alertSettingsWallet}
          userId={userId}
          apiUrl={API_URL}
          onClose={() => setAlertSettingsWallet(null)}
        />
      )}

      {replacementData && (
        <WalletReplacementModal
          currentWallet={replacementData.wallet}
          suggestions={replacementData.suggestions}
          onReplace={async (newWallet) => {
            try {
              const token = getAccessToken();
              const response = await fetch(`${API_URL}/api/wallets/watchlist/replace`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                  user_id: userId,
                  old_wallet: replacementData.wallet.wallet_address,
                  new_wallet: newWallet.wallet
                })
              });

              const data = await response.json();
              
              if (data.success) {
                alert('✅ Wallet replaced successfully!');
                setReplacementData(null);
              } else {
                alert(`Failed: ${data.error}`);
              }
            } catch (error) {
              console.error('Replace error:', error);
              alert('Failed to replace wallet');
            }
          }}
          onDismiss={() => setReplacementData(null)}
        />
      )}

      {isAnalyzing && streamingMessage && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60] flex items-center justify-center">
          <div className="bg-gradient-to-br from-gray-900 to-black border border-white/10 rounded-xl p-6 max-w-md mx-4">
            <div className="flex flex-col items-center gap-4">
              <div className="w-12 h-12 border-4 border-white/20 border-t-purple-500 rounded-full animate-spin" />
              <p className="text-sm text-gray-300 text-center">{streamingMessage}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}