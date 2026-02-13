import React, { useState, useEffect, useRef,  useCallback } from 'react';
import { Search, CheckSquare, Square, TrendingUp, Clock, Settings, Wallet, BarChart3, BookmarkPlus, X, ExternalLink, Users, Trash2, Tag, StickyNote, ChevronDown, ChevronUp, RotateCcw, AlertCircle, Zap, Filter, Sliders, LogOut, Loader2, Plus } from 'lucide-react';
import WalletActivityMonitor from './WalletActivityMonitor.jsx';
import WalletAlertSettings from './WalletAlertSettings.jsx';
import TelegramSettings from './TelegramSettings';
import WalletHealthDashboard from './WalletHealthDashboard';
import WalletLeagueTable from './WalletLeagueTable';
import WalletReplacementModal from './WalletReplacementModal';
import Auth from './components/Auth';
import { useAuth } from './contexts/AuthContext';
import AnalysisSettings from './Analysis_Setting.jsx';
import { supabase } from './lib/supabase'; // Adjust path if your lib folder is elsewhere

// ========== WALLET RESULT CARD COMPONENT ==========
const WalletResultCard = ({ wallet, idx, onAddToWatchlist }) => {
  const [showRunners, setShowRunners] = useState(false);
  
  // ✅ Determine token display
  const getTokenDisplay = () => {
    const analyzedTokens = wallet.analyzed_tokens || [];
    const otherTokens = wallet.other_runners?.map(r => r.symbol) || [];
    const allTokens = [...new Set([...analyzedTokens, ...otherTokens])];
    
    if (allTokens.length === 0) return 'Unknown';
    if (allTokens.length === 1) return allTokens[0];
    if (allTokens.length <= 3) return allTokens.join(', ');
    return `${allTokens.slice(0, 3).join(', ')} +${allTokens.length - 3} more`;
  };

  const [isAddingWallet, setIsAddingWallet] = useState(false);
  



  const tokenDisplay = getTokenDisplay();
  const isSingleToken = (wallet.analyzed_tokens?.length || 0) === 1;
  
  return (
    <div className="bg-black/30 border border-white/10 rounded-xl overflow-hidden">
      <div className="p-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-1">
              <span className="text-purple-400 font-bold text-sm">#{idx + 1}</span>
              <span className="font-mono text-sm">
                {wallet.wallet?.slice(0, 8)}...{wallet.wallet?.slice(-4)}
              </span>
              {wallet.is_fresh && (
                <span className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded font-semibold">
                  ✨ Fresh
                </span>
              )}
              {wallet.professional_grade && wallet.professional_score && (
                <span className="px-2 py-1 bg-purple-500/20 text-purple-400 rounded text-xs font-bold">
                  {wallet.professional_grade} • {wallet.professional_score}
                </span>
              )}
            </div>
            
            {/* ✅ Token/Tokens display (NO "main token") */}
            <div className="text-xs text-gray-400">
              {isSingleToken ? 'Token: ' : 'Tokens: '}
              {tokenDisplay}
            </div>
          </div>
          
          <button
            onClick={() => onAddToWatchlist(wallet)}
            className="p-2 hover:bg-purple-500/20 rounded-lg text-purple-400 transition"
            title="Add to Watchlist"
          >
            <BookmarkPlus size={16} />
          </button>
        </div>

        {/* Professional Score Breakdown with CORRECT LABELS */}
        {wallet.score_breakdown && (
          <div className="mb-3 border-t border-white/10 pt-3">
            <div className="text-xs font-semibold text-gray-400 mb-2">
              Professional Score Breakdown (60/30/10):
            </div>
            <div className="grid grid-cols-3 gap-2">
              
              {/* Distance to ATH (60%) */}
              <div className="bg-white/5 rounded p-2">
                <div className="text-sm font-bold text-blue-400 mb-1">
                  {wallet.score_breakdown.distance_to_ath_score || 0}
                </div>
                <div className="text-xs text-gray-500 mb-2">Distance to ATH (60%)</div>
                
                {wallet.entry_to_ath_multiplier && (
                  <div className="text-xs">
                    <div className="text-blue-300">{wallet.entry_to_ath_multiplier}x below</div>
                    {wallet.distance_to_ath_pct && (
                      <div className="text-blue-300">{wallet.distance_to_ath_pct.toFixed(1)}% below</div>
                    )}
                  </div>
                )}
              </div>
              
              {/* Realized Profit (30%) */}
              <div className="bg-white/5 rounded p-2">
                <div className="text-sm font-bold text-green-400 mb-1">
                  {wallet.score_breakdown.realized_profit_score || 0}
                </div>
                <div className="text-xs text-gray-500 mb-2">Realized Profit (30%)</div>
                
                {wallet.realized_multiplier && (
                  <div className="text-xs text-green-300">
                    {wallet.realized_multiplier}x realized
                  </div>
                )}
              </div>
              
              {/* Total Position (10%) */}
              <div className="bg-white/5 rounded p-2">
                <div className="text-sm font-bold text-purple-400 mb-1">
                  {wallet.score_breakdown.total_position_score || 0}
                </div>
                <div className="text-xs text-gray-500 mb-2">Total Position (10%)</div>
                
                {wallet.total_multiplier && (
                  <div className="text-xs text-purple-300">
                    {wallet.total_multiplier}x total
                  </div>
                )}
              </div>
            </div>
            
            {/* ✅ ONLY SHOW CONSISTENCY FOR MULTI-TOKEN */}
            {wallet.consistency_score !== undefined && (
              <div className="mt-2 p-2 bg-purple-500/10 rounded border border-purple-500/20">
                <div className="text-xs font-semibold text-purple-400 mb-1">
                  Consistency Score: {wallet.consistency_score}
                </div>
                <div className="text-xs text-gray-500">
                  How consistently this wallet enters at similar price points across multiple tokens
                </div>
              </div>
            )}
          </div>
        )}

        {/* Main Stats */}
        <div className="grid grid-cols-4 gap-3 mb-3">
          {wallet.entry_to_ath_multiplier && (
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <div className="text-lg font-bold text-blue-400">
                {wallet.entry_to_ath_multiplier}x
              </div>
              <div className="text-xs text-gray-400">Entry→ATH</div>
            </div>
          )}
          
          {wallet.distance_to_ath_pct && (
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <div className="text-lg font-bold text-cyan-400">
                {wallet.distance_to_ath_pct.toFixed(1)}%
              </div>
              <div className="text-xs text-gray-400">Below ATH</div>
            </div>
          )}
          
          {wallet.realized_multiplier && (
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <div className="text-lg font-bold text-green-400">
                {wallet.realized_multiplier}x
              </div>
              <div className="text-xs text-gray-400">Realized</div>
            </div>
          )}
          
          {wallet.total_multiplier && (
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <div className="text-lg font-bold text-purple-400">
                {wallet.total_multiplier}x
              </div>
              <div className="text-xs text-gray-400">Total</div>
            </div>
          )}
        </div>

        {/* ✅ 30-Day Runner Dropdown with Per-Runner Stats */}
        {wallet.other_runners && wallet.other_runners.length > 0 && (
          <div className="border-t border-white/10 pt-3">
            <button
              onClick={() => setShowRunners(!showRunners)}
              className="w-full flex items-center justify-between p-2 hover:bg-white/5 rounded transition"
            >
              <div className="flex items-center gap-2">
                <TrendingUp size={14} className="text-purple-400" />
                <span className="text-sm font-semibold text-purple-400">
                  Other 5x+ Runners (Last 30 Days)
                </span>
                <span className="text-xs bg-purple-500/20 px-2 py-0.5 rounded">
                  {wallet.runner_hits_30d || wallet.other_runners.length}
                </span>
              </div>
              <ChevronDown 
                size={16} 
                className={`text-gray-400 transition-transform ${showRunners ? 'rotate-180' : ''}`}
              />
            </button>

            {showRunners && (
              <div className="mt-3 space-y-3">
                
                {/* Summary Stats */}
                {(wallet.other_runners_stats || wallet.runner_success_rate) && (
                  <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-3">
                    <div className="text-xs font-semibold text-purple-400 mb-2">
                      Summary Stats:
                    </div>
                    <div className="grid grid-cols-2 gap-3 text-xs">
                      {(wallet.other_runners_stats?.avg_entry_to_ath || wallet.runner_avg_roi) && (
                        <div>
                          <div className="text-gray-400 mb-1">Avg Distance to ATH:</div>
                          <div className="flex items-center gap-2">
                            {wallet.other_runners_stats?.avg_entry_to_ath && (
                              <span className="text-blue-400 font-bold">
                                {wallet.other_runners_stats.avg_entry_to_ath}x
                              </span>
                            )}
                            {wallet.other_runners_stats?.avg_distance_to_ath_pct && (
                              <span className="text-cyan-400 font-bold">
                                ({wallet.other_runners_stats.avg_distance_to_ath_pct.toFixed(1)}%)
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                      
                      {(wallet.other_runners_stats?.avg_roi || wallet.runner_avg_roi) && (
                        <div>
                          <div className="text-gray-400 mb-1">Avg ROI:</div>
                          <div className="text-green-400 font-bold">
                            {(wallet.other_runners_stats?.avg_roi || wallet.runner_avg_roi).toFixed(1)}x
                          </div>
                        </div>
                      )}
                      
                      {(wallet.other_runners_stats?.success_rate || wallet.runner_success_rate) && (
                        <div>
                          <div className="text-gray-400 mb-1">Success Rate:</div>
                          <div className="text-green-400 font-bold">
                            {(wallet.other_runners_stats?.success_rate || wallet.runner_success_rate).toFixed(0)}%
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Individual Runner Cards */}
                <div className="space-y-2">
                  {wallet.other_runners.map((runner, ri) => (
                    <div key={ri} className="bg-black/40 rounded-lg border border-white/5 overflow-hidden">
                      
                      {/* Runner Header */}
                      <div className="p-3 bg-gradient-to-r from-white/5 to-transparent border-b border-white/5">
                        <div className="flex items-center justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-sm font-bold text-white">
                                {runner.symbol}
                              </span>
                              <span className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded font-semibold">
                                {runner.multiplier}x pump
                              </span>
                            </div>
                            <div className="text-xs text-gray-500">{runner.name}</div>
                          </div>
                        </div>
                      </div>
                      
                      {/* Distance to ATH Section */}
                      {runner.entry_to_ath_multiplier && (
                        <div className="p-3 border-b border-white/5">
                          <div className="flex items-center gap-2 mb-2">
                            <TrendingUp size={12} className="text-blue-400" />
                            <span className="text-xs font-semibold text-gray-400">
                              Entry Distance to ATH
                            </span>
                          </div>
                          
                          <div className="grid grid-cols-2 gap-2">
                            <div className="bg-white/5 rounded-lg p-2 text-center border border-blue-500/20">
                              <div className="text-base font-bold text-blue-400">
                                {runner.entry_to_ath_multiplier}x
                              </div>
                              <div className="text-xs text-gray-500">below ATH</div>
                            </div>
                            
                            <div className="bg-white/5 rounded-lg p-2 text-center border border-cyan-500/20">
                              <div className="text-base font-bold text-cyan-400">
                                {runner.distance_to_ath_pct?.toFixed(1)}%
                              </div>
                              <div className="text-xs text-gray-500">below ATH</div>
                            </div>
                          </div>
                        </div>
                      )}
                      
                      {/* Profit Performance Section */}
                      {runner.roi_multiplier && (
                        <div className="p-3">
                          <div className="flex items-center gap-2 mb-2">
                            <BarChart3 size={12} className="text-green-400" />
                            <span className="text-xs font-semibold text-gray-400">
                              Profit Performance
                            </span>
                          </div>
                          
                          <div className="grid grid-cols-3 gap-2">
                            <div className="bg-white/5 rounded-lg p-2 text-center border border-green-500/20">
                              <div className="text-base font-bold text-green-400">
                                {runner.roi_multiplier}x
                              </div>
                              <div className="text-xs text-gray-500">ROI</div>
                            </div>
                            
                            <div className="bg-white/5 rounded-lg p-2 text-center border border-blue-500/20">
                              <div className="text-sm font-bold text-blue-400">
                                ${runner.invested}
                              </div>
                              <div className="text-xs text-gray-500">Invested</div>
                            </div>
                            
                            <div className="bg-white/5 rounded-lg p-2 text-center border border-purple-500/20">
                              <div className="text-sm font-bold text-purple-400">
                                ${runner.realized}
                              </div>
                              <div className="text-xs text-gray-500">Realized</div>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default function SifterKYS() {
  // ========== AUTHENTICATION ==========
  const {
    user,
    loading: authLoading,
    isAuthenticated,
    isPasswordRecovery,
    signIn,
    signUp,
    signOut,
    resetPassword,
    updatePassword,
    getAccessToken,
  } = useAuth();

  // ========== MODE TOGGLE ==========
  const [mode, setMode] = useState('twitter'); // 'twitter' or 'wallet'
  const [isSwitchingMode, setIsSwitchingMode] = useState(false);
  
  // ========== TAB STATE ==========
  const [activeTab, setActiveTab] = useState('analyze');
  
  // ========== WALLET CONNECTION ==========
  const [walletAddress, setWalletAddress] = useState(null);
  const [showWalletMenu, setShowWalletMenu] = useState(false);
  
  // ========== TOKEN SEARCH ==========
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedTokens, setSelectedTokens] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchRef = useRef(null);
  
  // ========== ANALYSIS SETTINGS ==========
  const [analysisType, setAnalysisType] = useState('general'); // 'pump_window' or 'general'
  const [useGlobalSettings, setUseGlobalSettings] = useState(true);
  const [tokenSettings, setTokenSettings] = useState({});
  
  // Global settings
  const [daysBack, setDaysBack] = useState(7);
  const [candleSize, setCandleSize] = useState('5m');
  const [tMinusWindow, setTMinusWindow] = useState(35);
  const [tPlusWindow, setTPlusWindow] = useState(10);
  
  // ========== ANALYSIS RESULTS ==========
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [twitterResults, setTwitterResults] = useState(null);
  const [walletResults, setWalletResults] = useState(null);
  const [expandedTokens, setExpandedTokens] = useState({});
  const [expandedWallets, setExpandedWallets] = useState({});
  
  // ========== ANALYSIS PROGRESS ==========
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [analysisPhase, setAnalysisPhase] = useState('');
  
  // ========== WATCHLIST ==========
  const [twitterWatchlist, setTwitterWatchlist] = useState([]);
  const [twitterWatchlistStats, setTwitterWatchlistStats] = useState(null);
  const [walletWatchlist, setWalletWatchlist] = useState([]);
  const [walletWatchlistStats, setWalletWatchlistStats] = useState(null);
  const [isLoadingWatchlist, setIsLoadingWatchlist] = useState(false);  
  const [editingNotes, setEditingNotes] = useState(null);
  const [editingTags, setEditingTags] = useState(null);
  const [newNote, setNewNote] = useState('');
  const [newTags, setNewTags] = useState('');

  // ========== BATCH ANALYSIS ==========
  const [selectedRunners, setSelectedRunners] = useState([]);
  const [isBatchAnalyzing, setIsBatchAnalyzing] = useState(false);
  const [batchResults, setBatchResults] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastRefreshTime, setLastRefreshTime] = useState(null);

  // ========== WALLET ALERTS ==========
  const [alertSettingsWallet, setAlertSettingsWallet] = useState(null);
  const [activeSettingsTab, setActiveSettingsTab] = useState('telegram');

  // ========== TRENDING RUNNERS ==========
  const [trendingRunners, setTrendingRunners] = useState([]);
  const [isLoadingRunners, setIsLoadingRunners] = useState(false);
  const [runnerFilters, setRunnerFilters] = useState({
    timeframe: '7d',
    minLiquidity: 50000,
    maxLiquidity: 10000000,
    minVolume: 0,
    maxVolume: 100000000,
    minMultiplier: 5,
    minTokenAge: 0,
    maxTokenAge: 30
  });
  const [showFilterModal, setShowFilterModal] = useState(false);
  const [tempFilters, setTempFilters] = useState(runnerFilters);
  const [expandedRunners, setExpandedRunners] = useState({});
  
  // ========== AUTO DISCOVERY ==========
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discoveryResults, setDiscoveryResults] = useState(null);

  // ========== WALLET REPLACEMENT ==========
  const [showReplacementModal, setShowReplacementModal] = useState(false);
  const [currentDecliningWallet, setCurrentDecliningWallet] = useState(null);
  const [replacementSuggestions, setReplacementSuggestions] = useState([]);
  const [isLoadingReplacements, setIsLoadingReplacements] = useState(false);

  const API_URL = 'http://localhost:5000';
  const userId = user?.id;

  // Helper for authenticated API calls
  const authFetch = async (url, options = {}) => {
    const token = getAccessToken();
    const headers = {
      ...options.headers,
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    };
    return fetch(url, { ...options, headers });
  };

  // ========== EFFECTS ==========
  useEffect(() => {
    function handleClickOutside(event) {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (activeTab === 'watchlist') {
      if (mode === 'twitter') {
        loadTwitterWatchlist();
        loadTwitterWatchlistStats();
      } else {
        loadWalletWatchlist();
        loadWalletWatchlistStats();
      }
    } 
  }, [activeTab, mode, userId]);


  

  useEffect(() => {
    const saved = localStorage.getItem('sifter_wallet');
    if (saved) setWalletAddress(saved);
  }, []);

  // Auto-load trending runners when tab is opened
  useEffect(() => {
    if (activeTab === 'trending') {
      loadTrendingRunners();
    }
  }, [activeTab]);

  // Load watchlist when tab opens
  useEffect(() => {
    if (activeTab === 'watchlist' && mode === 'wallet') {
      loadWalletWatchlist();
    }
  }, [activeTab, mode]);

  // Auto-reload trending runners when filters change
  useEffect(() => {
    if (activeTab === 'trending') {
      loadTrendingRunners();
    }
  }, [runnerFilters.timeframe, runnerFilters.minLiquidity, runnerFilters.maxLiquidity, 
      runnerFilters.minVolume, runnerFilters.maxVolume, runnerFilters.minMultiplier, 
      runnerFilters.minTokenAge, runnerFilters.maxTokenAge]);

  // Auto-refresh trending runners every 60 seconds
  useEffect(() => {
    if (!autoRefresh || activeTab !== 'trending') return;
    
    const interval = setInterval(() => {
      console.log('Auto-refreshing trending runners...');
      loadTrendingRunners();
      setLastRefreshTime(new Date());
    }, 60000); // 60 seconds
    
    return () => clearInterval(interval);
  }, [autoRefresh, activeTab]);

  // ========== MODE SWITCHING WITH TRANSITION ==========
  const handleModeSwitch = async (newMode) => {
    if (newMode === mode) return;
    
    setIsSwitchingMode(true);
    
    await new Promise(resolve => setTimeout(resolve, 400));
    
    setMode(newMode);
    setIsSwitchingMode(false);
  };

  // ========== WALLET CONNECTION ==========
  const connectWallet = async () => {
    try {
      if (window.solana && window.solana.isPhantom) {
        const response = await window.solana.connect();
        const address = response.publicKey.toString();
        setWalletAddress(address);
        localStorage.setItem('sifter_wallet', address);
      } else {
        alert('Please install Phantom wallet');
        window.open('https://phantom.app/', '_blank');
      }
    } catch (error) {
      console.error('Wallet error:', error);
    }
  };

  const disconnectWallet = () => {
    setWalletAddress(null);
    localStorage.removeItem('sifter_wallet');
    setShowWalletMenu(false);
  };

  // ========== TOKEN SEARCH ==========
  const searchTokens = async (query) => {
    if (!query || query.length < 2) {
      setSearchResults([]);
      return;
    }

    setIsSearching(true);

    try {
      const response = await fetch(`https://api.dexscreener.com/latest/dex/search/?q=${encodeURIComponent(query)}`);
      const data = await response.json();

      if (data.pairs && data.pairs.length > 0) {
        const formatted = data.pairs.map(pair => ({
          address: pair.baseToken.address,
          ticker: pair.baseToken.symbol,
          name: pair.baseToken.name,
          chain: pair.chainId,
          dex: pair.dexId,
          price: pair.priceUsd,
          liquidity: pair.liquidity?.usd || 0,
          pairAddress: pair.pairAddress,
          url: pair.url
        }));

        formatted.sort((a, b) => b.liquidity - a.liquidity);
        setSearchResults(formatted.slice(0, 20));
      } else {
        setSearchResults([]);
      }
    } catch (error) {
      console.error('Search error:', error);
      setSearchResults([]);
    }

    setIsSearching(false);
  };

  useEffect(() => {
    setSearchResults([]);
    setShowDropdown(false);
    
    const timer = setTimeout(() => {
      if (searchQuery.trim()) {
        searchTokens(searchQuery.trim());
        setShowDropdown(true);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  const toggleTokenSelection = (token) => {
    const isSelected = selectedTokens.some(
      t => t.address.toLowerCase() === token.address.toLowerCase() && t.chain === token.chain
    );
    
    if (isSelected) {
      setSelectedTokens(selectedTokens.filter(
        t => !(t.address.toLowerCase() === token.address.toLowerCase() && t.chain === token.chain)
      ));
      const key = `${token.chain}-${token.address}`;
      const newSettings = { ...tokenSettings };
      delete newSettings[key];
      setTokenSettings(newSettings);
    } else {
      setSelectedTokens([...selectedTokens, token]);
      if (!useGlobalSettings) {
        const key = `${token.chain}-${token.address}`;
        setTokenSettings({
          ...tokenSettings,
          [key]: {
            days_back: daysBack,
            candle_size: candleSize,
            t_minus: tMinusWindow,
            t_plus: tPlusWindow
          }
        });
      }
    }
    
    setShowDropdown(false);
    setSearchQuery('');
  };

  const removeToken = (address, chain) => {
    setSelectedTokens(selectedTokens.filter(
      t => !(t.address.toLowerCase() === address.toLowerCase() && t.chain === chain)
    ));
    const key = `${chain}-${address}`;
    const newSettings = { ...tokenSettings };
    delete newSettings[key];
    setTokenSettings(newSettings);
  };

  const updateTokenSetting = (address, chain, field, value) => {
    const key = `${chain}-${address}`;
    setTokenSettings({
      ...tokenSettings,
      [key]: {
        ...tokenSettings[key],
        [field]: value
      }
    });
  };

  // ========== ANALYSIS FUNCTIONS ==========
  const handleAnalysis = async () => {
    if (selectedTokens.length === 0) {
      alert('Please select at least one token');
      return;
    }

    setIsAnalyzing(true);
    setActiveTab('results');

    try {
      const tokensToAnalyze = selectedTokens.map(token => {
        const key = `${token.chain}-${token.address}`;
        
        const settings = useGlobalSettings ? {
          days_back: daysBack,
          candle_size: candleSize,
          t_minus: tMinusWindow,
          t_plus: tPlusWindow
        } : (tokenSettings[key] || {
          days_back: daysBack,
          candle_size: candleSize,
          t_minus: tMinusWindow,
          t_plus: tPlusWindow
        });

        return {
          address: token.address,
          ticker: token.ticker,
          name: token.name,
          chain: token.chain,
          pair_address: token.pairAddress,
          settings: settings
        };
      });

      if (mode === 'twitter') {
        const endpoint = '/api/wallets/analyze';
        const response = await authFetch(`${API_URL}${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tokens: tokensToAnalyze })
        });

        const data = await response.json();

        if (response.ok) {
          setTwitterResults(data);
          const expanded = {};
          data.results?.forEach((_, idx) => {
            expanded[idx] = true;
          });
          setExpandedTokens(expanded);
        } else {
          throw new Error(data.error || 'Analysis failed');
        }
      } else {
        // ✅ Use Realtime - Submit job and listen for updates
        const response = await authFetch(`${API_URL}/api/wallets/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            tokens: tokensToAnalyze,
            user_id: userId,
            global_settings: {
              min_pump_count: 1,
              wallet_window_before: 35,
              wallet_window_after: 0,
              mode: analysisType === 'pump_window' ? 'pump' : 'general',
              min_roi_multiplier: 3.0
            }
          })
        });

        const data = await response.json();

        if (response.status === 202 && data.job_id) {
          // Listen for completion via Realtime
          const subscription = supabase
            .channel('analysis_updates')
            .on('postgres_changes', {
              event: 'UPDATE',
              schema: 'sifter_dev',
              table: 'analysis_jobs',
              filter: `job_id=eq.${data.job_id}`
            }, (payload) => {
              console.log('Analysis update:', payload.new);
              
              // ✅ Update progress
              setAnalysisProgress(payload.new.progress || 0);
              setAnalysisPhase(payload.new.phase || '');
              
              if (payload.new.status === 'completed') {
                setWalletResults(payload.new.results);
                setIsAnalyzing(false);
                subscription.unsubscribe();
              } else if (payload.new.status === 'failed') {
                alert('Analysis failed: ' + payload.new.results?.error);
                setIsAnalyzing(false);
                subscription.unsubscribe();
              }
            })
            .subscribe();
        } else if (response.ok && data.success) {
          setWalletResults(data);
          const expanded = {};
          data.top_wallets?.forEach((_, idx) => {
            expanded[idx] = true;
          });
          setExpandedWallets(expanded);
          setIsAnalyzing(false);
        } else {
          throw new Error(data.error || 'Wallet analysis failed');
        }
      }
    } catch (error) {
      console.error('Analysis error:', error);
      alert(`Analysis failed: ${error.message}`);
      setIsAnalyzing(false);
    }
  };

  // ========== STREAMING ANALYSIS FUNCTION ==========
  const handleAnalysisStreaming = async () => {
    if (selectedTokens.length === 0) {
      alert('Please select at least one token');
      return;
    }

    setIsAnalyzing(true);
    setActiveTab('results');
    setWalletResults({ top_wallets: [] });  // Initialize empty

    const tokensToAnalyze = selectedTokens.map(token => ({
      address: token.address,
      ticker: token.ticker,
      name: token.name,
      chain: token.chain,
      pair_address: token.pairAddress
    }));

    // ✅ Use EventSource for streaming
    const eventSource = new EventSource(
      `${API_URL}/api/wallets/analyze/stream?` + 
      new URLSearchParams({ tokens: JSON.stringify(tokensToAnalyze), user_id: userId })
    );

    eventSource.onmessage = (event) => {
      const tokenResult = JSON.parse(event.data);
      
      if (tokenResult.done) {
        eventSource.close();
        setIsAnalyzing(false);
        return;
      }

      // ✅ Append results progressively
      setWalletResults(prev => ({
        ...prev,
        top_wallets: [...(prev.top_wallets || []), ...tokenResult.top_wallets]
      }));
    };

    eventSource.onerror = (error) => {
      console.error('Stream error:', error);
      eventSource.close();
      setIsAnalyzing(false);
      alert('Analysis stream failed');
    };
  };

  // ========== BATCH ANALYSIS FUNCTIONS ==========
  const analyzeBatchRunners = async () => {
    if (selectedRunners.length === 0) {
      alert('Please select at least one runner');
      return;
    }

    setIsBatchAnalyzing(true);

    try {
      const response = await authFetch(`${API_URL}/api/wallets/trending/analyze-batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          runners: selectedRunners,
          user_id: userId,
          min_roi_multiplier: 3.0,
          min_runner_hits: 2
        })
      });

      const data = await response.json();

      if (data.success) {
        setBatchResults(data);
        setActiveTab('results'); // Switch to results tab
      } else {
        alert('Batch analysis failed');
      }
    } catch (error) {
      console.error('Batch analysis error:', error);
      alert('Batch analysis failed');
    }

    setIsBatchAnalyzing(false);
  };

  const toggleRunnerSelection = (runner) => {
    const isSelected = selectedRunners.some(r => r.address === runner.address);
    
    if (isSelected) {
      setSelectedRunners(selectedRunners.filter(r => r.address !== runner.address));
    } else {
      setSelectedRunners([...selectedRunners, runner]);
    }
  };

  const selectAllRunners = () => {
    setSelectedRunners([...trendingRunners]);
  };

  const clearRunnerSelection = () => {
    setSelectedRunners([]);
  };

  // ========== WATCHLIST FUNCTIONS ==========
  const loadTwitterWatchlist = async () => {
    try {
      const response = await authFetch(`${API_URL}/api/watchlist/get?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setTwitterWatchlist(data.accounts);
      }
    } catch (error) {
      console.error('Error loading twitter watchlist:', error);
    }
  };

  const loadTwitterWatchlistStats = async () => {
    try {
      const response = await authFetch(`${API_URL}/api/watchlist/stats?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setTwitterWatchlistStats(data.stats);
      }
    } catch (error) {
      console.error('Error loading twitter stats:', error);
    }
  };

 const loadWalletWatchlist = useCallback(async () => {
   if (isLoadingWatchlist) return;  // ← Prevent duplicate calls
  
 setIsLoadingWatchlist(true);
  try {
    const response = await authFetch(`${API_URL}/api/wallets/watchlist/table?user_id=${userId}`);
    const data = await response.json();
    
    if (response.status === 429) {
      console.warn('Rate limited - will retry in 5 seconds');
      setTimeout(loadWalletWatchlist, 5000);
      return;
    }
    
    if (data.success) {
      setWalletWatchlist(data.wallets || []);
      setWalletWatchlistStats(data.stats || null);
    }
  } catch (error) {
    console.error('Error loading wallet watchlist:', error);
  } finally {
    setIsLoadingWatchlist(false);
  }
}, [userId, isLoadingWatchlist, authFetch]);  // ← Add dependencies

  const loadWalletWatchlistStats = async () => {
    try {
      const response = await authFetch(`${API_URL}/api/wallets/watchlist/stats?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setWalletWatchlistStats(data.stats);
      }
    } catch (error) {
      console.error('Error loading wallet stats:', error);
    }
  };

  const addToTwitterWatchlist = async (account) => {
    try {
      const response = await authFetch(`${API_URL}/api/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, account })
      });
      const data = await response.json();
      if (data.success) {
        alert('✅ Added to Twitter watchlist!');
      }
    } catch (error) {
      console.error('Error adding to twitter watchlist:', error);
    }
  };

  const addToWalletWatchlist = async (wallet) => {
    try {
      // ✅ Let backend handle the mapping - send the whole object
      const response = await authFetch(`${API_URL}/api/wallets/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          user_id: userId, 
          wallet: wallet  // ✅ Just send the whole object
        })
      });
      
      const data = await response.json();
      
      if (data.success) {
        alert('✅ Added to wallet watchlist with alerts enabled!');
        loadWalletWatchlist();
      } else {
        alert(`❌ Failed: ${data.error}`);
      }
    } catch (error) {
      console.error('Error adding wallet to watchlist:', error);
      alert('❌ Error adding to watchlist');
    }
  };

  const removeFromTwitterWatchlist = async (authorId) => {
    if (!confirm('Remove this account from watchlist?')) return;
    try {
      const response = await authFetch(`${API_URL}/api/watchlist/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, author_id: authorId })
      });
      const data = await response.json();
      if (data.success) {
        loadTwitterWatchlist();
        loadTwitterWatchlistStats();
      }
    } catch (error) {
      console.error('Error removing from twitter watchlist:', error);
    }
  };

  const removeFromWalletWatchlist = async (walletAddress) => {
    if (!confirm('Remove this wallet from watchlist?')) return;
    try {
      const response = await authFetch(`${API_URL}/api/wallets/watchlist/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, wallet_address: walletAddress })
      });
      const data = await response.json();
      if (data.success) {
        loadWalletWatchlist();
        loadWalletWatchlistStats();
      }
    } catch (error) {
      console.error('Error removing wallet from watchlist:', error);
    }
  };

  const updateTwitterWatchlistNotes = async (authorId, notes) => {
    try {
      const response = await authFetch(`${API_URL}/api/watchlist/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, author_id: authorId, notes })
      });
      const data = await response.json();
      if (data.success) {
        loadTwitterWatchlist();
        setEditingNotes(null);
        setNewNote('');
      }
    } catch (error) {
      console.error('Error updating twitter notes:', error);
    }
  };

  const updateTwitterWatchlistTags = async (authorId, tags) => {
    try {
      const tagsArray = tags.split(',').map(t => t.trim()).filter(t => t);
      const response = await authFetch(`${API_URL}/api/watchlist/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, author_id: authorId, tags: tagsArray })
      });
      const data = await response.json();
      if (data.success) {
        loadTwitterWatchlist();
        setEditingTags(null);
        setNewTags('');
      }
    } catch (error) {
      console.error('Error updating twitter tags:', error);
    }
  };

  const updateWalletWatchlistNotes = async (walletAddress, notes) => {
    try {
      const response = await authFetch(`${API_URL}/api/wallets/watchlist/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, wallet_address: walletAddress, notes })
      });
      const data = await response.json();
      if (data.success) {
        loadWalletWatchlist();
        setEditingNotes(null);
        setNewNote('');
      }
    } catch (error) {
      console.error('Error updating wallet notes:', error);
    }
  };

  const updateWalletWatchlistTags = async (walletAddress, tags) => {
    try {
      const tagsArray = tags.split(',').map(t => t.trim()).filter(t => t);
      const response = await authFetch(`${API_URL}/api/wallets/watchlist/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, wallet_address: walletAddress, tags: tagsArray })
      });
      const data = await response.json();
      if (data.success) {
        loadWalletWatchlist();
        setEditingTags(null);
        setNewTags('');
      }
    } catch (error) {
      console.error('Error updating wallet tags:', error);
    }
  };

  // ========== WALLET REPLACEMENT FUNCTIONS ==========
  const findReplacements = async (walletAddress) => {
    try {
      setIsLoadingReplacements(true);
      setCurrentDecliningWallet(walletWatchlist.find(w => w.wallet_address === walletAddress));
      
      const token = getAccessToken();
      const response = await fetch(`${API_URL}/api/wallets/watchlist/suggest-replacement`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          user_id: userId,
          wallet_address: walletAddress,
          min_professional_score: 85
        })
      });
      
      const data = await response.json();
      
      if (data.success) {
        setReplacementSuggestions(data.replacements || []);
        setShowReplacementModal(true);
      }
    } catch (error) {
      console.error('Error finding replacements:', error);
    } finally {
      setIsLoadingReplacements(false);
    }
  };

  const handleReplaceWallet = async (newWallet) => {
    try {
      const token = getAccessToken();
      const response = await fetch(`${API_URL}/api/wallets/watchlist/replace`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          user_id: userId,
          old_wallet: currentDecliningWallet.wallet_address,
          new_wallet: newWallet.wallet
        })
      });
      
      const data = await response.json();
      
      if (data.success) {
        await loadWalletWatchlist();
        setShowReplacementModal(false);
        setCurrentDecliningWallet(null);
        setReplacementSuggestions([]);
        alert('Wallet replaced successfully!');
      }
    } catch (error) {
      console.error('Error replacing wallet:', error);
      alert('Failed to replace wallet');
    }
  };

  // ========== TRENDING RUNNERS ==========
  const loadTrendingRunners = async () => {
    setIsLoadingRunners(true);
    try {
      const params = new URLSearchParams({
        timeframe: runnerFilters.timeframe,
        min_liquidity: runnerFilters.minLiquidity,
        max_liquidity: runnerFilters.maxLiquidity,
        min_volume: runnerFilters.minVolume,
        max_volume: runnerFilters.maxVolume,
        min_multiplier: runnerFilters.minMultiplier,
        min_age_days: runnerFilters.minTokenAge,
        max_age_days: runnerFilters.maxTokenAge
      });

      const response = await authFetch(`${API_URL}/api/wallets/trending/runners?${params}`);
      const data = await response.json();
      
      if (data.success) {
        setTrendingRunners(data.runners);
      }
    } catch (error) {
      console.error('Error loading trending runners:', error);
    }
    setIsLoadingRunners(false);
  };

  const analyzeRunner = async (runner) => {
    const runnerKey = `${runner.chain}-${runner.address}`;
    
    setExpandedRunners(prev => ({
      ...prev,
      [runnerKey]: { ...prev[runnerKey], loading: true }
    }));

    try {
      if (mode === 'twitter') {
        const response = await authFetch(`${API_URL}/api/analyze/runner`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            runner: {
              address: runner.address,
              chain: runner.chain,
              ticker: runner.ticker,
              pair_address: runner.pairAddress
            }
          })
        });
        const data = await response.json();
        
        setExpandedRunners(prev => ({
          ...prev,
          [runnerKey]: { 
            expanded: true, 
            loading: false,
            data: data.accounts || []
          }
        }));
      } else {
        const response = await authFetch(`${API_URL}/api/trending/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            runner: {
              address: runner.address,
              chain: runner.chain,
              ticker: runner.ticker,
              pair_address: runner.pairAddress
            },
            user_id: userId,
            min_roi_multiplier: 3.0
          })
        });
        const data = await response.json();
        
        setExpandedRunners(prev => ({
          ...prev,
          [runnerKey]: { 
            expanded: true, 
            loading: false,
            data: data.wallets || []
          }
        }));
      }
    } catch (error) {
      console.error('Error analyzing runner:', error);
      setExpandedRunners(prev => ({
        ...prev,
        [runnerKey]: { 
          expanded: true, 
          loading: false,
          error: 'Failed to analyze'
        }
      }));
    }
  };

  // ========== AUTO DISCOVERY ==========
  const runAutoDiscovery = async () => {
    setIsDiscovering(true);
    
    try {
      const endpoint = mode === 'twitter' 
        ? '/api/discover/twitter'
        : '/api/wallets/discover';

      const response = await authFetch(`${API_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          min_runner_hits: 2,
          days_back: 30,
          min_multiplier: 5,
          min_liquidity: 50000
        })
      });

      const data = await response.json();
      
      if (data.success) {
        setDiscoveryResults(data);
      }
    } catch (error) {
      console.error('Error running auto discovery:', error);
      alert('Auto discovery failed');
    }

    setIsDiscovering(false);
  };

  // ========== HELPER FUNCTIONS ==========
  const formatNumber = (num) => {
    if (num >= 1000000) return `$${(num / 1000000).toFixed(2)}M`;
    if (num >= 1000) return `$${(num / 1000).toFixed(1)}K`;
    return `$${num.toFixed(2)}`;
  };

  const formatPrice = (price) => {
    if (!price) return '$0.00';
    const num = parseFloat(price);
    if (num < 0.000001) return `$${num.toExponential(2)}`;
    if (num < 0.01) return `$${num.toFixed(6)}`;
    return `$${num.toFixed(4)}`;
  };

  const toggleTokenExpansion = (idx) => {
    setExpandedTokens(prev => ({
      ...prev,
      [idx]: !prev[idx]
    }));
  };

  const toggleWalletExpansion = (idx) => {
    setExpandedWallets(prev => ({
      ...prev,
      [idx]: !prev[idx]
    }));
  };

  const clearResults = () => {
    if (confirm('Clear analysis results?')) {
      setTwitterResults(null);
      setWalletResults(null);
      setBatchResults(null);
      setExpandedTokens({});
      setExpandedWallets({});
      setAnalysisProgress(0);
      setAnalysisPhase('');
    }
  };

  const hasResults = isAnalyzing || twitterResults || walletResults || batchResults;

  // Show loading spinner while checking auth
  if (authLoading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 size={48} className="animate-spin text-purple-500" />
          <p className="text-gray-400">Loading...</p>
        </div>
      </div>
    );
  }

  // Show auth screen if not authenticated
  if (!isAuthenticated || isPasswordRecovery) {
    return (
      <Auth
        onSignIn={signIn}
        onSignUp={signUp}
        onResetPassword={resetPassword}
        onUpdatePassword={updatePassword}
        isPasswordRecovery={isPasswordRecovery}
      />
    );
  }

  return (
    <div className="min-h-screen bg-black text-gray-100">
      {/* NAVBAR */}
      <nav className="fixed top-0 w-full z-50 bg-black/80 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 py-3">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-4">
              <div className="text-xl font-bold">
                SIFTER <span className="text-purple-500">KYS</span>
              </div>
              
              {/* MODE TOGGLE */}
              <div className="relative flex items-center gap-1 bg-gradient-to-r from-gray-900 to-gray-800 rounded-lg p-1 border border-white/10">
                <button
                  onClick={() => handleModeSwitch('twitter')}
                  disabled={isSwitchingMode}
                  className={`relative px-4 py-1.5 rounded-md text-xs font-bold transition-all duration-300 flex items-center gap-1.5 ${
                    mode === 'twitter'
                      ? 'bg-gradient-to-r from-blue-600 to-blue-500 text-white shadow-lg shadow-blue-500/50'
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  <Users size={13} />
                  Twitter
                </button>
                <button
                  onClick={() => handleModeSwitch('wallet')}
                  disabled={isSwitchingMode}
                  className={`relative px-4 py-1.5 rounded-md text-xs font-bold transition-all duration-300 flex items-center gap-1.5 ${
                    mode === 'wallet'
                      ? 'bg-gradient-to-r from-green-600 to-green-500 text-white shadow-lg shadow-green-500/50'
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  <Wallet size={13} />
                  Wallet
                </button>
              </div>
            </div>
            
            <div className="flex gap-3 items-center">
              <WalletActivityMonitor />

              {walletAddress ? (
                <div className="relative">
                  <button
                    onClick={() => setShowWalletMenu(!showWalletMenu)}
                    className="px-3 py-2 bg-green-600 rounded-lg hover:bg-green-700 transition text-sm flex items-center gap-2"
                  >
                    <div className="w-2 h-2 bg-white rounded-full animate-pulse" />
                    {walletAddress.slice(0, 6)}...{walletAddress.slice(-4)}
                  </button>

                  {showWalletMenu && (
                    <div className="absolute right-0 top-12 bg-black border border-white/10 rounded-lg p-3 w-48 shadow-xl">
                      <button
                        onClick={disconnectWallet}
                        className="w-full px-3 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 rounded text-sm"
                      >
                        Disconnect
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <button
                  onClick={connectWallet}
                  className="px-3 py-2 bg-white/5 rounded-lg hover:bg-white/10 transition text-sm flex items-center gap-2"
                >
                  <Wallet size={16} />
                  Connect Wallet
                </button>
              )}

              <a
                href="https://whop.com/sifter"
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-2 bg-purple-600 rounded-lg hover:bg-purple-700 transition text-sm"
              >
                Upgrade
              </a>

              <button
                onClick={() => signOut()}
                className="px-3 py-2 bg-white/5 rounded-lg hover:bg-white/10 transition text-sm flex items-center gap-2"
                title={user?.email}
              >
                <LogOut size={16} />
                <span className="hidden sm:inline">Sign Out</span>
              </button>
            </div>
          </div>
        </div>
      </nav>

      {/* Mode Switching Overlay */}
      {isSwitchingMode && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 flex items-center justify-center">
          <div className="bg-gradient-to-br from-gray-900 to-black border border-white/20 rounded-2xl p-8 flex flex-col items-center gap-4">
            <div className="w-16 h-16 border-4 border-white/20 border-t-purple-500 rounded-full animate-spin" />
            <div className="text-lg font-semibold">
              Switching to {mode === 'twitter' ? 'Wallet' : 'Twitter'} Mode...
            </div>
          </div>
        </div>
      )}

      <div className="pt-20 max-w-7xl mx-auto px-6 py-6">
        {/* MAIN TABS */}
        <div className="flex gap-3 mb-6 border-b border-white/10">
          {[
            { id: 'analyze', label: 'Analyze', icon: Search },
            { id: 'results', label: `${mode === 'twitter' ? 'Twitter' : 'Wallet'} Results`, icon: BarChart3 },
            { id: 'trending', label: 'Trending Runners', icon: TrendingUp },
            { id: 'discover', label: 'Auto Discovery', icon: Zap },
            { id: 'watchlist', label: 'Watchlist', icon: BookmarkPlus },
            { id: 'settings', label: 'Settings', icon: Settings },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2 border-b-2 transition text-sm ${
                activeTab === tab.id
                  ? 'border-purple-500 text-white'
                  : 'border-transparent text-gray-400 hover:text-white'
              }`}
            >
              <tab.icon size={16} />
              {tab.label}
              {tab.id === 'results' && (isAnalyzing || isBatchAnalyzing) && (
                <span className="w-2 h-2 bg-purple-400 rounded-full animate-pulse" />
              )}
            </button>
          ))}
        </div>

        {/* ========== ANALYZE TAB ========== */}
        {activeTab === 'analyze' && (
          <div className="space-y-4">
            {/* Token Search */}
            <div className="bg-white/5 border border-white/10 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-base font-semibold">Token Search</h3>
                
                {/* Analysis Type Dropdown */}
                <div className="relative">
                  <select
                    value={analysisType}
                    onChange={(e) => setAnalysisType(e.target.value)}
                    className="appearance-none bg-gradient-to-br from-gray-800 to-gray-900 border border-gray-700 rounded-lg px-4 py-2.5 pr-10 text-sm font-semibold cursor-pointer hover:border-purple-500/50 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-purple-500/40 focus:border-purple-500 text-white shadow-lg"
                    style={{
                      backgroundImage: 'linear-gradient(135deg, #1f2937 0%, #111827 100%)'
                    }}
                  >
                  <option value="general" className="bg-gray-900 text-white py-2">📊 General Analysis</option>
                    <option value="pump_window" className="bg-gray-900 text-white py-2">🎯 Pump Window</option>
                    
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-gray-400" size={16} />
                </div>
              </div>
              
              <div className="relative flex-1" ref={searchRef}>
                <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search by token name, ticker, or contract address..."
                  className="w-full bg-black/50 border border-white/10 rounded-lg pl-12 pr-4 py-3 text-sm focus:outline-none focus:border-purple-500 transition"
                />
                {isSearching && (
                  <div className="absolute right-4 top-1/2 transform -translate-y-1/2">
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  </div>
                )}
                
                {/* Search Dropdown */}
                {showDropdown && searchResults.length > 0 && (
                  <div className="absolute top-full left-0 right-0 mt-2 bg-gray-900 border border-white/20 rounded-xl shadow-2xl max-h-96 overflow-y-auto z-50">
                    {searchResults.map((token, idx) => {
                      const isSelected = selectedTokens.some(
                        t => t.address.toLowerCase() === token.address.toLowerCase() && t.chain === token.chain
                      );
                      
                      return (
                        <div
                          key={`${token.chain}-${token.address}-${idx}`}
                          onClick={() => toggleTokenSelection(token)}
                          className={`p-3 border-b border-white/5 hover:bg-white/5 cursor-pointer transition ${
                            isSelected ? 'bg-purple-500/10' : ''
                          }`}
                        >
                          <div className="flex items-start gap-2">
                            <div className="mt-1">
                              {isSelected ? (
                                <CheckSquare className="text-purple-400" size={18} />
                              ) : (
                                <Square className="text-gray-400" size={18} />
                              )}
                            </div>
                            <div className="flex-1">
                              <div className="flex items-center gap-2 mb-1">
                                <span className="font-semibold text-sm">{token.ticker}</span>
                                <span className="text-xs px-2 py-0.5 bg-white/10 rounded">{token.chain.toUpperCase()}</span>
                              </div>
                              <div className="text-xs text-gray-400">{token.name}</div>
                              <div className="text-xs text-gray-500 mt-1">Liq: {formatNumber(token.liquidity)}</div>
                            </div>
                            
                            <a
                              href={token.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-gray-400 hover:text-purple-400"
                            >
                              <ExternalLink size={14} />
                            </a>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* Selected Tokens */}
            {selectedTokens.length > 0 && (
              <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-4">
                <div className="flex justify-between items-center mb-3">
                  <h3 className="text-base font-semibold">
                    Selected Tokens ({selectedTokens.length})
                  </h3>
                  <button
                    onClick={() => setSelectedTokens([])}
                    className="text-xs text-gray-400 hover:text-white"
                  >
                    Clear All
                  </button>
                </div>

                {/* Token List */}
                <div className="space-y-2 mb-4">
                  {selectedTokens.map((token) => (
                    <div key={`${token.chain}-${token.address}`} className="bg-black/30 rounded-lg p-3">
                      <div className="flex justify-between items-start">
                        <div className="flex-1">
                          <div className="font-semibold text-sm">{token.ticker}</div>
                          <div className="text-xs text-gray-400">{token.chain.toUpperCase()}</div>
                        </div>
                        <button
                          onClick={() => removeToken(token.address, token.chain)}
                          className="p-1 hover:bg-white/10 rounded transition"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                {/* ✅ USE THE AnalysisSettings COMPONENT */}
                <AnalysisSettings
                  analysisType={analysisType}
                  selectedTokens={selectedTokens}
                  useGlobalSettings={useGlobalSettings}
                  setUseGlobalSettings={setUseGlobalSettings}
                  tokenSettings={tokenSettings}
                  updateTokenSetting={updateTokenSetting}
                  globalSettings={{
                    daysBack,
                    candleSize,
                    tMinusWindow,
                    tPlusWindow
                  }}
                  onGlobalSettingsChange={(settings) => {
                    if (settings.daysBack !== undefined) setDaysBack(settings.daysBack);
                    if (settings.candleSize !== undefined) setCandleSize(settings.candleSize);
                    if (settings.tMinusWindow !== undefined) setTMinusWindow(settings.tMinusWindow);
                    if (settings.tPlusWindow !== undefined) setTPlusWindow(settings.tPlusWindow);
                  }}
                />

                {/* Run Analysis Button */}
                <button
                  onClick={handleAnalysisStreaming}  // Changed from handleAnalysis to handleAnalysisStreaming
                  disabled={isAnalyzing}
                  className="w-full mt-4 px-4 py-3 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 disabled:from-purple-600/30 disabled:to-purple-500/30 rounded-lg font-semibold transition-all duration-300 flex items-center justify-center gap-2 shadow-lg shadow-purple-500/30"
                >
                  {isAnalyzing ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Analyzing...
                    </>
                  ) : (
                    <>
                      <BarChart3 size={18} />
                      Run Analysis (Streaming)
                    </>
                  )}
                </button>
              </div>
            )}
          </div>
        )}

        {/* ========== RESULTS TAB ========== */}
        {activeTab === 'results' && (
          <div className="space-y-4">
            {isAnalyzing && !(mode === 'twitter' ? twitterResults : walletResults) && (
              <div className="bg-white/5 border border-white/10 rounded-xl p-12 flex flex-col items-center justify-center gap-4">
                <div className="w-10 h-10 border-4 border-white/20 border-t-purple-500 rounded-full animate-spin" />
                <div className="text-base text-gray-300 font-semibold">
                  Analyzing... {analysisProgress}%
                </div>
                {analysisPhase && (
                  <div className="text-xs text-gray-500">
                    {analysisPhase.replace('_', ' ')}
                  </div>
                )}
              </div>
            )}

            {(mode === 'twitter' ? twitterResults : walletResults || batchResults) && (
              <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-lg font-semibold">
                    {batchResults ? '🔥 Batch Analysis Results' : 
                     mode === 'twitter' ? 'Twitter Analysis Results' : 'Wallet Analysis Results'}
                  </h3>
                  <button
                    onClick={clearResults}
                    className="px-3 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 rounded-lg text-sm flex items-center gap-2 transition"
                  >
                    <RotateCcw size={14} />
                    Clear
                  </button>
                </div>

                {mode === 'twitter' && twitterResults && (
                  <div className="space-y-3">
                    {twitterResults.results?.map((result, idx) => (
                      <div key={idx} className="bg-black/30 border border-white/10 rounded-lg p-4">
                        <h4 className="font-semibold mb-2">{result.token?.ticker}</h4>
                        {result.top_accounts?.map((account) => (
                          <div key={account.author_id} className="flex justify-between items-center p-2 bg-white/5 rounded mb-2">
                            <div>
                              <div className="font-semibold">@{account.username}</div>
                              <div className="text-xs text-gray-400">Influence: {account.influence_score}</div>
                            </div>
                            <button
                              onClick={() => addToTwitterWatchlist(account)}
                              className="p-2 hover:bg-purple-500/20 rounded text-purple-400 transition"
                            >
                              <BookmarkPlus size={16} />
                            </button>
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                )}

                {mode === 'wallet' && (walletResults || batchResults) && (
                  <div className="space-y-4">
                    {/* Batch Results Summary */}
                    {batchResults && (
                      <div className="bg-gradient-to-r from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-lg p-4">
                        <div className="grid grid-cols-4 gap-4">
                          <div>
                            <div className="text-2xl font-bold text-green-400">
                              {batchResults.wallets_discovered}
                            </div>
                            <div className="text-xs text-gray-400">Smart Money Wallets</div>
                          </div>
                          <div>
                            <div className="text-2xl font-bold text-yellow-400">
                              {batchResults.runners_analyzed}
                            </div>
                            <div className="text-xs text-gray-400">Runners Analyzed</div>
                          </div>
                          <div>
                            <div className="text-2xl font-bold text-blue-400">
                              {batchResults.consistency_summary?.avg_runner_hits || 0}
                            </div>
                            <div className="text-xs text-gray-400">Avg Runner Hits</div>
                          </div>
                          <div>
                            <div className="text-2xl font-bold text-purple-400">
                              {batchResults.consistency_summary?.a_plus_consistency || 0}
                            </div>
                            <div className="text-xs text-gray-400">A+ Consistency</div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Wallet Results Summary */}
                    {walletResults && !batchResults && (
                      <div className="grid grid-cols-4 gap-4 p-4 bg-gradient-to-r from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-lg">
                        <div>
                          <div className="text-2xl font-bold text-green-400">
                            {walletResults.summary?.qualified_wallets || walletResults.top_wallets?.length || 0}
                          </div>
                          <div className="text-xs text-gray-400">Qualified Wallets</div>
                        </div>
                        <div>
                          <div className="text-2xl font-bold text-yellow-400">
                            {walletResults.summary?.real_winners || 0}
                          </div>
                          <div className="text-xs text-gray-400">S-Tier Wallets</div>
                        </div>
                        <div>
                          <div className="text-2xl font-bold text-blue-400">
                            {walletResults.summary?.total_rallies || 0}
                          </div>
                          <div className="text-xs text-gray-400">Total Rallies</div>
                        </div>
                        <div>
                          <div className="text-2xl font-bold text-purple-400">
                            {walletResults.summary?.tokens_analyzed || 0}
                          </div>
                          <div className="text-xs text-gray-400">Tokens Analyzed</div>
                        </div>
                      </div>
                    )}

                    <div className="space-y-3">
                      {/* ✅ UPDATED: Use WalletResultCard component */}
                      {walletResults && !batchResults && walletResults.top_wallets?.map((wallet, idx) => (
                        <WalletResultCard
                          key={wallet.wallet}
                          wallet={wallet}
                          idx={idx}
                          onAddToWatchlist={addToWalletWatchlist}
                        />
                      ))}
                      
                      {/* Batch results display */}
                      {batchResults?.smart_money_wallets?.map((wallet, idx) => (
                        <WalletResultCard
                          key={wallet.wallet}
                          wallet={wallet}
                          idx={idx}
                          onAddToWatchlist={addToWalletWatchlist}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {!isAnalyzing && !isBatchAnalyzing && !(mode === 'twitter' ? twitterResults : walletResults || batchResults) && (
              <div className="bg-white/5 border border-white/10 rounded-xl p-12 text-center">
                <BarChart3 className="mx-auto mb-4 text-gray-600" size={48} />
                <h3 className="text-lg font-semibold mb-2">No Results Yet</h3>
                <p className="text-sm text-gray-400 mb-4">
                  Go back to the Analyze tab, select tokens, and run an analysis.
                </p>
                <button
                  onClick={() => setActiveTab('analyze')}
                  className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-semibold transition"
                >
                  Back to Analyze
                </button>
              </div>
            )}
          </div>
        )}

        {/* ========== TRENDING RUNNERS TAB ========== */}
        {activeTab === 'trending' && (
          <div className="space-y-4">
            {/* ✅ UPDATED FILTER BAR - REMOVED CANDLE BUTTONS */}
            <div className="bg-gradient-to-r from-gray-900/50 to-gray-800/50 border border-white/10 rounded-xl p-3">
              <div className="flex items-center gap-3 flex-wrap">
                {/* Timeframe Selector - 7d/14d/30d only */}
                <div className="relative">
                  <select
                    value={runnerFilters.timeframe}
                    onChange={(e) => setRunnerFilters({...runnerFilters, timeframe: e.target.value})}
                    className="appearance-none flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 rounded-lg font-semibold text-sm transition-all duration-300 shadow-lg shadow-blue-500/30 cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500/40 pr-8"
                  >
                    <option value="7d" className="bg-gray-900">7 Days</option>
                    <option value="14d" className="bg-gray-900">14 Days</option>
                    <option value="30d" className="bg-gray-900">30 Days</option>
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-white" size={14} />
                </div>

                <div className="h-8 w-px bg-white/10" />

                {/* Multiplier Buttons */}
                <div className="flex items-center gap-2">
                  {[5, 10, 20, 50].map(mult => (
                    <button
                      key={mult}
                      onClick={() => setRunnerFilters({...runnerFilters, minMultiplier: mult})}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                        runnerFilters.minMultiplier === mult
                          ? 'bg-purple-600 text-white shadow-lg shadow-purple-500/30'
                          : 'bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      {mult}x
                    </button>
                  ))}
                </div>

                <div className="h-8 w-px bg-white/10" />

                {/* Advanced Filters Button */}
                <button
                  onClick={() => {
                    setTempFilters(runnerFilters);
                    setShowFilterModal(true);
                  }}
                  className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 rounded-lg text-sm font-medium transition-all duration-200"
                >
                  <Sliders size={14} />
                  Advanced Filters
                </button>

                {/* Manual Refresh Button */}
                <button
                  onClick={loadTrendingRunners}
                  disabled={isLoadingRunners}
                  className="flex items-center gap-2 px-3 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-sm transition-all duration-200"
                  title="Refresh now"
                >
                  <RotateCcw size={14} className={isLoadingRunners ? 'animate-spin' : ''} />
                  {isLoadingRunners ? 'Loading...' : 'Refresh'}
                </button>
              </div>
            </div>

            {isLoadingRunners && (
              <div className="flex items-center justify-center py-12">
                <div className="flex items-center gap-3">
                  <div className="w-6 h-6 border-2 border-white/30 border-t-purple-500 rounded-full animate-spin" />
                  <span className="text-gray-400">Loading trending runners...</span>
                </div>
              </div>
            )}

            {!isLoadingRunners && trendingRunners.length > 0 && (
              <div className="space-y-3">
                {/* Batch Selection Controls */}
                {mode === 'wallet' && (
                  <div className="bg-gradient-to-r from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="text-sm font-semibold">
                          {selectedRunners.length} selected
                        </div>
                        {selectedRunners.length > 0 && (
                          <button
                            onClick={clearRunnerSelection}
                            className="text-xs text-gray-400 hover:text-white"
                          >
                            Clear
                          </button>
                        )}
                        <button
                          onClick={selectAllRunners}
                          className="text-xs text-purple-400 hover:text-purple-300"
                        >
                          Select All ({trendingRunners.length})
                        </button>
                      </div>

                      <div className="flex items-center gap-3">
                        {/* Auto-refresh toggle */}
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setAutoRefresh(!autoRefresh)}
                            className={`w-10 h-5 rounded-full transition-all duration-300 ${
                              autoRefresh ? 'bg-green-600' : 'bg-gray-600'
                            }`}
                          >
                            <div className={`w-4 h-4 bg-white rounded-full transition-all duration-300 transform ${
                              autoRefresh ? 'translate-x-5' : 'translate-x-1'
                            }`} />
                          </button>
                          <span className="text-xs text-gray-400">
                            Auto-refresh {autoRefresh ? 'ON' : 'OFF'}
                          </span>
                        </div>

                        {lastRefreshTime && (
                          <div className="text-xs text-gray-500">
                            Last: {lastRefreshTime.toLocaleTimeString()}
                          </div>
                        )}

                        <button
                          onClick={analyzeBatchRunners}
                          disabled={selectedRunners.length === 0 || isBatchAnalyzing}
                          className="px-4 py-2 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 disabled:from-purple-600/30 disabled:to-purple-500/30 rounded-lg font-semibold text-sm transition-all duration-300 flex items-center gap-2 shadow-lg shadow-purple-500/30"
                        >
                          {isBatchAnalyzing ? (
                            <>
                              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                              Analyzing {selectedRunners.length}...
                            </>
                          ) : (
                            <>
                              <BarChart3 size={16} />
                              Batch Analyze ({selectedRunners.length})
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead className="bg-gradient-to-r from-gray-900 to-gray-800 border-b border-white/10">
                        <tr>
                          {mode === 'wallet' && (
                            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">
                              <input
                                type="checkbox"
                                checked={selectedRunners.length === trendingRunners.length}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    selectAllRunners();
                                  } else {
                                    clearRunnerSelection();
                                  }
                                }}
                                className="w-4 h-4 rounded bg-white/10 border-white/20 cursor-pointer"
                              />
                            </th>
                          )}
                          <th className="px-4 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">#</th>
                          <th className="px-4 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">Token</th>
                          <th className="px-4 py-3 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider">Price</th>
                          <th className="px-4 py-3 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider">Multiplier</th>
                          <th className="px-4 py-3 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider">Liquidity</th>
                          <th className="px-4 py-3 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider">Age</th>
                          <th className="px-4 py-3 text-right text-xs font-semibold text-gray-300 uppercase tracking-wider">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trendingRunners.map((runner, idx) => {
                          const runnerKey = `${runner.chain}-${runner.address}`;
                          const runnerState = expandedRunners[runnerKey] || {};
                          const isSelected = selectedRunners.some(r => r.address === runner.address);

                          return (
                            <React.Fragment key={runnerKey}>
                              <tr className={`border-b border-white/5 hover:bg-white/5 transition-colors ${
                                isSelected ? 'bg-purple-500/10' : ''
                              }`}>
                                {mode === 'wallet' && (
                                  <td className="px-4 py-3">
                                    <input
                                      type="checkbox"
                                      checked={isSelected}
                                      onChange={() => toggleRunnerSelection(runner)}
                                      className="w-4 h-4 rounded bg-white/10 border-white/20 cursor-pointer"
                                    />
                                  </td>
                                )}
                                <td className="px-4 py-3 text-sm text-gray-400">#{idx + 1}</td>
                                <td className="px-4 py-3">
                                  <div>
                                    <div className="font-semibold text-sm">{runner.ticker}</div>
                                    <div className="text-xs text-gray-400">{runner.chain?.toUpperCase()}</div>
                                  </div>
                                </td>
                                <td className="px-4 py-3 text-right text-sm font-mono">{formatPrice(runner.current_price)}</td>
                                <td className="px-4 py-3 text-right">
                                  <span className="inline-flex items-center px-2 py-1 bg-green-500/20 text-green-400 rounded text-sm font-bold">
                                    {runner.multiplier}x
                                  </span>
                                </td>
                                <td className="px-4 py-3 text-right text-sm">{formatNumber(runner.liquidity)}</td>
                                <td className="px-4 py-3 text-right text-xs text-gray-400">{runner.age || 'N/A'}</td>
                                <td className="px-4 py-3 text-right">
                                  <button
                                    onClick={() => analyzeRunner(runner)}
                                    disabled={runnerState.loading}
                                    className="px-3 py-1.5 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 rounded-lg text-xs font-medium transition-all duration-200"
                                  >
                                    {runnerState.loading ? 'Analyzing...' : 'Analyze'}
                                  </button>
                                </td>
                              </tr>

                              {runnerState.expanded && (
                                <tr className="bg-black/30 border-b border-white/5">
                                  <td colSpan={mode === 'wallet' ? 8 : 7} className="px-4 py-3">
                                    <div className="text-sm">
                                      <div className="font-semibold mb-2 text-purple-400">
                                        {mode === 'twitter' ? 'Twitter Accounts:' : 'Smart Money Wallets:'}
                                      </div>
                                      {runnerState.data && runnerState.data.length === 0 ? (
                                        <div className="text-xs text-gray-500">No data found</div>
                                      ) : (
                                        <div className="grid grid-cols-1 gap-2">
                                          {runnerState.data?.slice(0, 5).map((item, i) => (
                                            <div key={i} className="p-3 bg-white/5 rounded">
                                              {mode === 'twitter' ? (
                                                <div className="text-xs flex justify-between items-center">
                                                  <span>@{item.username}</span>
                                                  <span className="text-gray-400">Influence: {item.influence_score}</span>
                                                </div>
                                              ) : (
                                                <>
                                                  <div className="flex justify-between items-center mb-2">
                                                    <span className="font-mono text-sm">{item.wallet?.slice(0, 16)}...</span>
                                                    <div className="flex items-center gap-2">
                                                      {item.professional_grade && item.professional_score && (
                                                        <span className="px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded text-xs font-bold">
                                                          {item.professional_grade} • {item.professional_score}
                                                        </span>
                                                      )}
                                                    </div>
                                                  </div>
                                                  
                                                  <div className="text-xs text-gray-400 mb-2">
                                                    {item.roi_percent}% ROI • {item.runner_hits_30d} runners (30d)
                                                  </div>
                                                  
                                                  {item.other_runners && item.other_runners.length > 0 && (
                                                    <div className="mt-3 space-y-2">
                                                      <div className="text-xs font-semibold text-gray-400">
                                                        Other 5x+ Runners (Last 30 Days):
                                                      </div>
                                                      {item.other_runners.map((r, ri) => (
                                                        <div key={ri} className="text-xs bg-black/40 rounded p-2">
                                                          <span className="font-semibold">{r.symbol}</span>
                                                          <span className="ml-2">{r.multiplier}x • ROI: {r.roi_multiplier}x</span>
                                                        </div>
                                                      ))}
                                                    </div>
                                                  )}
                                                </>
                                              )}
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              )}
                            </React.Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {!isLoadingRunners && trendingRunners.length === 0 && (
              <div className="bg-white/5 border border-white/10 rounded-xl p-12 text-center">
                <TrendingUp className="mx-auto mb-4 text-gray-400" size={48} />
                <h3 className="text-lg font-semibold mb-2">No Trending Runners Found</h3>
                <p className="text-sm text-gray-400">
                  Try adjusting your filters to see more results
                </p>
              </div>
            )}
          </div>
        )}

        {showFilterModal && (
          <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div className="bg-gradient-to-br from-gray-900 to-black border border-white/20 rounded-2xl p-4 max-w-md w-full shadow-2xl max-h-[85vh] flex flex-col">
              <div className="flex justify-between items-center mb-3 flex-shrink-0">
                <h3 className="text-lg font-bold">Custom Filters</h3>
                <button
                  onClick={() => setShowFilterModal(false)}
                  className="p-2 hover:bg-white/10 rounded-lg transition"
                >
                  <X size={18} />
                </button>
              </div>

              <div className="space-y-3 overflow-y-auto flex-1 pr-2">
                <div className="bg-white/5 rounded-lg p-3 border border-white/10">
                  <label className="block text-sm font-semibold mb-2 text-purple-400">Liquidity Range</label>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs font-medium mb-1 text-gray-400">Min ($)</label>
                      <input
                        type="number"
                        min="0"
                        value={tempFilters.minLiquidity}
                        onChange={(e) => setTempFilters({...tempFilters, minLiquidity: Math.max(0, parseFloat(e.target.value) || 0)})}
                        className="w-full bg-black/60 border border-white/20 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium mb-1 text-gray-400">Max ($)</label>
                      <input
                        type="number"
                        min="0"
                        value={tempFilters.maxLiquidity}
                        onChange={(e) => setTempFilters({...tempFilters, maxLiquidity: Math.max(0, parseFloat(e.target.value) || 0)})}
                        className="w-full bg-black/60 border border-white/20 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                      />
                    </div>
                  </div>
                </div>

                <div className="bg-white/5 rounded-lg p-3 border border-white/10">
                  <label className="block text-sm font-semibold mb-2 text-purple-400">Volume Range</label>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs font-medium mb-1 text-gray-400">Min ($)</label>
                      <input
                        type="number"
                        min="0"
                        value={tempFilters.minVolume}
                        onChange={(e) => setTempFilters({...tempFilters, minVolume: Math.max(0, parseFloat(e.target.value) || 0)})}
                        className="w-full bg-black/60 border border-white/20 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium mb-1 text-gray-400">Max ($)</label>
                      <input
                        type="number"
                        min="0"
                        value={tempFilters.maxVolume}
                        onChange={(e) => setTempFilters({...tempFilters, maxVolume: Math.max(0, parseFloat(e.target.value) || 0)})}
                        className="w-full bg-black/60 border border-white/20 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                      />
                    </div>
                  </div>
                </div>

                <div className="bg-white/5 rounded-lg p-3 border border-white/10">
                  <label className="block text-sm font-semibold mb-2 text-purple-400">Min Multiplier</label>
                  <input
                    type="number"
                    min="0"
                    step="0.1"
                    value={tempFilters.minMultiplier}
                    onChange={(e) => setTempFilters({...tempFilters, minMultiplier: Math.max(0, parseFloat(e.target.value) || 0)})}
                    className="w-full bg-black/60 border border-white/20 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                  />
                </div>

                <div className="bg-white/5 rounded-lg p-3 border border-white/10">
                  <label className="block text-sm font-semibold mb-2 text-purple-400">Token Age (Days)</label>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs font-medium mb-1 text-gray-400">Min</label>
                      <input
                        type="number"
                        min="0"
                        value={tempFilters.minTokenAge}
                        onChange={(e) => setTempFilters({...tempFilters, minTokenAge: Math.max(0, parseInt(e.target.value) || 0)})}
                        className="w-full bg-black/60 border border-white/20 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium mb-1 text-gray-400">Max</label>
                      <input
                        type="number"
                        min="0"
                        value={tempFilters.maxTokenAge}
                        onChange={(e) => setTempFilters({...tempFilters, maxTokenAge: Math.max(0, parseInt(e.target.value) || 0)})}
                        className="w-full bg-black/60 border border-white/20 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex gap-2 mt-3 flex-shrink-0">
                <button
                  onClick={() => setShowFilterModal(false)}
                  className="flex-1 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg font-medium transition text-sm"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setRunnerFilters(tempFilters);
                    setShowFilterModal(false);
                  }}
                  className="flex-1 px-4 py-2 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 rounded-lg font-semibold transition shadow-lg shadow-purple-500/30 text-sm"
                >
                  Apply Filters
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ========== AUTO DISCOVERY TAB ========== */}
        {activeTab === 'discover' && (
          <div className="space-y-4">
            <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-2xl p-6">
              <div className="flex items-start gap-6">
                <div className="flex-shrink-0">
                  <div className="w-14 h-14 bg-gradient-to-br from-purple-600/30 to-purple-500/30 rounded-xl flex items-center justify-center border border-purple-500/30">
                    <Zap className="text-purple-400" size={28} />
                  </div>
                </div>
                
                <div className="flex-1">
                  <h2 className="text-lg font-bold mb-2">Auto Discovery</h2>
                  <p className="text-gray-400 text-sm mb-4">
                    Discover {mode === 'twitter' ? 'Twitter accounts' : 'wallets'} appearing across multiple 5x+ runners
                  </p>
                  
                  <button
                    onClick={runAutoDiscovery}
                    disabled={isDiscovering}
                    className="px-5 py-2 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 disabled:from-purple-600/30 disabled:to-purple-500/30 rounded-lg font-semibold text-sm transition-all duration-300 flex items-center gap-2 shadow-lg shadow-purple-500/30"
                  >
                    {isDiscovering ? (
                      <>
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Discovering...
                      </>
                    ) : (
                      <>
                        <Zap size={16} />
                        Run Discovery
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>

            {discoveryResults && (
              <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                <h3 className="text-lg font-semibold mb-2">Discovery Results</h3>
                <div className="text-sm text-gray-400 mb-4">
                  Found {discoveryResults.total_wallets || discoveryResults.total_found} {mode === 'twitter' ? 'accounts' : 'wallets'}
                </div>
                
                {mode === 'wallet' && discoveryResults.smart_money_wallets && (
                  <div className="space-y-2">
                    {discoveryResults.smart_money_wallets.slice(0, 10).map((wallet, idx) => (
                      <div key={idx} className="bg-black/30 border border-white/10 rounded-lg p-3">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex-1">
                            <div className="font-mono text-sm mb-1">
                              {wallet.wallet?.slice(0, 16)}...
                              {wallet.is_fresh && (
                                <span className="ml-2 text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded">
                                  ✨ Fresh
                                </span>
                              )}
                            </div>
                            
                            {(wallet.consistency_grade || wallet.avg_professional_score || wallet.variance) && (
                              <div className="text-xs text-gray-400 flex items-center gap-2 mb-1">
                                {wallet.consistency_grade && (
                                  <span className="px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded font-bold">
                                    {wallet.consistency_grade}
                                  </span>
                                )}
                                {wallet.avg_professional_score && (
                                  <span>Avg Score: {wallet.avg_professional_score}</span>
                                )}
                                {wallet.variance && (
                                  <span>Variance: {wallet.variance}</span>
                                )}
                              </div>
                            )}
                            
                            <div className="text-xs text-gray-500">
                              {wallet.runner_count} runners
                              {wallet.in_batch_count !== undefined && ` • In Batch: ${wallet.in_batch_count}`}
                              {wallet.outside_batch_count !== undefined && ` • Outside: ${wallet.outside_batch_count}`}
                              {!wallet.in_batch_count && !wallet.outside_batch_count && wallet.avg_roi && ` • ${wallet.avg_roi.toFixed(0)}% avg ROI`}
                              {wallet.runner_hits_30d > 0 && ` • 🎯 ${wallet.runner_hits_30d} hits`}
                            </div>
                          </div>
                          <button
                            onClick={() => addToWalletWatchlist(wallet)}
                            className="p-2 hover:bg-purple-500/20 rounded text-purple-400 transition"
                          >
                            <BookmarkPlus size={16} />
                          </button>
                        </div>
                        
                        {(wallet.roi_details || wallet.outside_batch_runners) && (
                          <div className="mt-3 space-y-2">
                            {wallet.roi_details && wallet.roi_details.length > 0 && (
                              <div>
                                <div className="text-xs font-semibold text-gray-400 mb-1">Batch Runners:</div>
                                {wallet.roi_details.map((r, i) => (
                                  <div key={i} className="text-xs bg-black/40 rounded p-2 mb-1">
                                    <span className="font-semibold">{r.runner}</span>
                                    <span className="ml-2 text-green-400">{r.professional_grade} • {r.roi_percent}%</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            
                            {wallet.outside_batch_runners && wallet.outside_batch_runners.length > 0 && (
                              <div className="border-t border-white/10 pt-2">
                                <div className="text-xs font-semibold text-gray-400 mb-1">
                                  Other Runners (Outside Batch):
                                </div>
                                {wallet.outside_batch_runners.map((r, i) => (
                                  <div key={i} className="text-xs bg-black/40 rounded p-2 mb-1">
                                    <span className="font-semibold">{r.symbol}</span>
                                    <span className="ml-2">{r.multiplier}x • ROI: {r.roi_multiplier}x</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ========== WATCHLIST TAB ========== */}
        {activeTab === 'watchlist' && (
          <div className="space-y-4">
            
            {/* 🧪 QUICK ADD TEST WALLET - ADD THIS SECTION */}
            <div className="bg-purple-500/10 border border-purple-500/30 rounded-xl p-4">
              <h3 className="text-sm font-semibold text-purple-300 mb-3 flex items-center gap-2">
                <Plus size={16} />
                🧪 Quick Add Test Wallet (Stress Test)
              </h3>
              <div className="flex gap-3">
                <input
                  type="text"
                  placeholder="Paste wallet address..."
                  className="flex-1 bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                  id="quickAddInput"
                />
                <button
                  onClick={async () => {if (isAddingWallet) return;setIsAddingWallet(true);




                    const input = document.getElementById('quickAddInput');
                    const address = input.value.trim();
                    
                    if (!address) {
                      alert('Please enter a wallet address');
                      return;
                    }
                    
                    try {
                      const token = getAccessToken();
                      const response = await fetch(`${API_URL}/api/wallets/watchlist/add-quick`, {
                        method: 'POST',
                        headers: { 
                          'Content-Type': 'application/json',
                          'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify({
                          user_id: userId,
                          wallet_address: address,
                          notes: 'Stress test - monitoring 100 txs',
                          tags: ['stress-test', 'exchange', 'high-volume']
                        })
                      });
                      
                      const data = await response.json();
                      
                      if (data.success) {
                        alert(`✅ ${address.slice(0, 8)}... added!\n\nAlerts: ENABLED\nBuys: ON\nSells: ON\nMin Trade: $10\n\nMonitoring will start in 2 minutes.`);
                        input.value = '';
                        loadWalletWatchlist(); // Refresh the table
                      } else {
                        alert(`❌ ${data.error || 'Failed to add wallet'}`);
                      }
                    } catch (error) {
                      console.error('Error adding wallet:', error);
                      alert('Error adding wallet');
                    }
                  }}
                  className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg font-semibold transition flex items-center gap-2"
                >
                  <Plus size={18} />
                  Add to Watchlist
                </button>
              </div>
              <div className="mt-2 text-xs text-gray-400">
                💡 Try: <code className="bg-black/30 px-2 py-0.5 rounded">5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9</code> (Binance hot wallet - high volume)
              </div>
            </div>

            {/* Health Dashboard */}
            <WalletHealthDashboard
              wallets={walletWatchlist}
              stats={walletWatchlistStats}
              onViewWallet={(wallet) => {
                console.log('View wallet:', wallet);
              }}
              onFindReplacements={(walletAddress, autoReplace) => {
                findReplacements(walletAddress);
              }}
              onRefresh={() => {
                loadWalletWatchlist();
              }}
            />

            {/* Premier League Table */}
            <WalletLeagueTable
              wallets={walletWatchlist}
              promotionQueue={walletWatchlistStats?.promotion_queue || []}
              onReplace={(oldWallet, newWallet) => {
                if (oldWallet) {
                  setCurrentDecliningWallet(oldWallet);
                  findReplacements(oldWallet.wallet_address);
                } else {
                  handleReplaceWallet(newWallet);
                }
              }}
              onExpand={(wallet) => {
                console.log('Expanded wallet:', wallet);
              }}
              onConfigure={(wallet) => {
                setAlertSettingsWallet(wallet.wallet_address);
              }}
            />

            {/* Replacement Modal */}
            {showReplacementModal && (
              <WalletReplacementModal
                currentWallet={currentDecliningWallet}
                suggestions={replacementSuggestions}
                onReplace={handleReplaceWallet}
                onDismiss={() => {
                  setShowReplacementModal(false);
                  setCurrentDecliningWallet(null);
                  setReplacementSuggestions([]);
                }}
              />
            )}
          </div>
        )}

        {/* ========== SETTINGS TAB ========== */}
        {activeTab === 'settings' && (
          <div className="space-y-4">
            <div className="flex gap-3 border-b border-white/10 mb-4">
              <button
                onClick={() => setActiveSettingsTab('telegram')}
                className={`px-4 py-2 border-b-2 transition text-sm ${
                  activeSettingsTab === 'telegram'
                    ? 'border-purple-500 text-white'
                    : 'border-transparent text-gray-400 hover:text-white'
                }`}
              >
                📱 Telegram
              </button>
              {/* Add more setting tabs here later */}
            </div>

            {activeSettingsTab === 'telegram' && (
              <TelegramSettings 
                userId={user?.id} 
                apiUrl={import.meta.env.VITE_API_URL} 
              />
            )}
          </div>
        )}
      </div>
      {alertSettingsWallet && (
        <WalletAlertSettings
          walletAddress={alertSettingsWallet}
          onClose={() => setAlertSettingsWallet(null)}
          onSave={(settings) => {
            loadWalletWatchlist();
            setAlertSettingsWallet(null);
          }}
        />
      )}
    </div>
  );
}