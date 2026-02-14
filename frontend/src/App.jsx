import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from './contexts/AuthContext';
import { User, ChevronDown, Settings, HelpCircle, LogOut, BarChart3, X, Search } from 'lucide-react';

// NEW IMPORTS - Panel System
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

// Keep existing imports
import WalletActivityMonitor from './WalletActivityMonitor';
import WalletAlertSettings from './WalletAlertSettings';
import WalletReplacementModal from './WalletReplacementModal';
import Auth from './components/Auth';

export default function SifterKYS() {
  const { user, loading: authLoading, isAuthenticated, signOut, getAccessToken, signIn, signUp, resetPassword, updatePassword } = useAuth();

  // ========== PANEL STATE (REPLACES activeTab) ==========
  const [openPanel, setOpenPanel] = useState(null);
  const [showProfileDropdown, setShowProfileDropdown] = useState(false);

  // ========== EXISTING STATE - KEEP ALL ==========
  const [mode, setMode] = useState('wallet');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedTokens, setSelectedTokens] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchRef = useRef(null);

  // Analysis state
  const [analysisType, setAnalysisType] = useState('general');
  const [useGlobalSettings, setUseGlobalSettings] = useState(true);
  const [tokenSettings, setTokenSettings] = useState({});
  const [daysBack, setDaysBack] = useState(7);
  const [candleSize, setCandleSize] = useState('5m');
  const [tMinusWindow, setTMinusWindow] = useState(4);
  const [tPlusWindow, setTPlusWindow] = useState(2);

  // Results state
  const [walletResults, setWalletResults] = useState(null);
  const [batchResults, setBatchResults] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [streamingMessage, setStreamingMessage] = useState('');

  // Watchlist state
  const [alertSettingsWallet, setAlertSettingsWallet] = useState(null);
  const [replacementModalWallet, setReplacementModalWallet] = useState(null);

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';
  const userId = user?.id;

  // ========== PANEL HANDLERS ==========
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
      watchlist: { direction: 'right', width: 'w-[600px]', title: '👁️ Watchlist' },
      top100: { direction: 'right', width: 'w-96', title: '🏆 Top 100 Community' },
      premium100: { direction: 'right', width: 'w-96', title: '👑 Premium Elite 100' },
      quickadd: { direction: 'right', width: 'w-96', title: '➕ Quick Add Wallet' },
      profile: { direction: 'right', width: 'w-96', title: 'Profile' },
      help: { direction: 'right', width: 'w-96', title: '❓ Help & Support' },
    };
    return configs[panelId] || configs.analyze;
  };

  // ========== UTILITY FUNCTIONS ==========
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

  // ========== TOKEN SEARCH ==========
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

  // ========== ANALYSIS FUNCTIONS ==========
  const handleAnalysisStreaming = async () => {
    if (selectedTokens.length === 0) {
      alert('Please select at least one token');
      return;
    }

    setIsAnalyzing(true);
    setWalletResults(null);
    setStreamingMessage('Initializing analysis...');

    try {
      const token = getAccessToken();
      const response = await fetch(`${API_URL}/api/analysis/wallet-streaming`, {
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
          use_global_settings: useGlobalSettings,
          global_settings: useGlobalSettings
            ? { days_back: daysBack, candle_size: candleSize, t_minus_window: tMinusWindow, t_plus_window: tPlusWindow }
            : null,
          token_settings: !useGlobalSettings ? tokenSettings : null,
          analysis_type: analysisType,
        }),
      });

      if (!response.ok) {
        throw new Error('Analysis failed');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.trim().startsWith('data: ')) {
            try {
              const jsonData = JSON.parse(line.substring(6));

              if (jsonData.type === 'progress') {
                setStreamingMessage(jsonData.message);
              } else if (jsonData.type === 'complete') {
                setWalletResults(jsonData.data);
                setStreamingMessage('Analysis complete!');
              } else if (jsonData.type === 'error') {
                throw new Error(jsonData.message);
              }
            } catch (parseError) {
              console.error('Parse error:', parseError);
            }
          }
        }
      }
    } catch (error) {
      console.error('Analysis error:', error);
      alert(`Analysis failed: ${error.message}`);
    }

    setIsAnalyzing(false);
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
      } else {
        alert(`Failed: ${data.error}`);
      }
    } catch (error) {
      console.error('Add to watchlist error:', error);
      alert('Failed to add wallet to watchlist');
    }
  };

  // ========== AUTH CHECK ==========
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

              {/* PROFILE DROPDOWN */}
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

      {/* ========== MAIN CONTENT - DASHBOARD HOME ========== */}
      <div className="pt-20 max-w-7xl mx-auto px-6 py-6">
        <DashboardHome
          user={user}
          onOpenPanel={handleOpenPanel}
          recentActivity={[]}
          analysisResults={walletResults}
          isAnalyzing={isAnalyzing}
        />
      </div>

      {/* ========== SLIDE-OUT PANEL SYSTEM ========== */}
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
            handleAnalysisStreaming={handleAnalysisStreaming}
            isAnalyzing={isAnalyzing}
            onClose={handleClosePanel}
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
          />
        )}

        {openPanel === 'help' && <HelpSupportPanel userId={userId} apiUrl={API_URL} />}
      </SlideOutPanel>

      {/* ========== FOOTER ========== */}
      <footer className="fixed bottom-0 w-full bg-black/80 border-t border-white/10 py-2 z-30">
        <div className="max-w-7xl mx-auto px-6 text-center text-xs text-gray-500">
          © 2026 Sifter.io • support@sifter.io • @SifterIO • Terms • Privacy
        </div>
      </footer>

      {/* ========== MODALS ========== */}
      {alertSettingsWallet && (
        <WalletAlertSettings
          walletAddress={alertSettingsWallet}
          userId={userId}
          apiUrl={API_URL}
          onClose={() => setAlertSettingsWallet(null)}
        />
      )}

      {replacementModalWallet && (
        <WalletReplacementModal
          walletAddress={replacementModalWallet}
          userId={userId}
          apiUrl={API_URL}
          onClose={() => setReplacementModalWallet(null)}
        />
      )}

      {/* Streaming Progress Overlay */}
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