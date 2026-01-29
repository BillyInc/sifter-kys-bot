import React, { useState, useEffect, useRef } from 'react';
import { Search, CheckSquare, Square, TrendingUp, Clock, Settings, Wallet, BarChart3, BookmarkPlus, X, ExternalLink, Users, Trash2, Tag, StickyNote, ChevronDown, ChevronUp, RotateCcw, AlertCircle } from 'lucide-react';
import WalletActivityMonitor from './WalletActivityMonitor.jsx';
import WalletAlertSettings from './WalletAlertSettings.jsx';

export default function SifterKYS() {
  const [activeTab, setActiveTab] = useState('analyze');
  const [walletAddress, setWalletAddress] = useState(null);
  const [showWalletMenu, setShowWalletMenu] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedTokens, setSelectedTokens] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchRef = useRef(null);
  
  // Per-token customization state
  const [useGlobalSettings, setUseGlobalSettings] = useState(true);
  const [tokenSettings, setTokenSettings] = useState({});
  
  // Global settings
  const [daysBack, setDaysBack] = useState(7);
  const [candleSize, setCandleSize] = useState('5m');
  const [tMinusWindow, setTMinusWindow] = useState(35);
  const [tPlusWindow, setTPlusWindow] = useState(10);
  
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResults, setAnalysisResults] = useState(null);
  
  // Twitter Watchlist state
  const [twitterWatchlist, setTwitterWatchlist] = useState([]);
  const [twitterWatchlistStats, setTwitterWatchlistStats] = useState(null);
  const [editingNotes, setEditingNotes] = useState(null);
  const [editingTags, setEditingTags] = useState(null);
  const [newNote, setNewNote] = useState('');
  const [newTags, setNewTags] = useState('');

  // Wallet Watchlist state
  const [walletWatchlist, setWalletWatchlist] = useState([]);
  const [walletWatchlistStats, setWalletWatchlistStats] = useState(null);

  // Expanded tokens state
  const [expandedTokens, setExpandedTokens] = useState({});

  // Wallet analysis state
  const [walletAnalysisResults, setWalletAnalysisResults] = useState(null);
  const [isAnalyzingWallets, setIsAnalyzingWallets] = useState(false);
  const [expandedWallets, setExpandedWallets] = useState({});

  // ⭐ NEW: Alert settings state
  const [alertSettingsWallet, setAlertSettingsWallet] = useState(null);

  const API_URL = 'http://localhost:5000';
  const userId = 'demo_user';

  useEffect(() => {
    function handleClickOutside(event) {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Load appropriate watchlist based on active tab
  useEffect(() => {
    if (activeTab === 'twitter-watchlist') {
      loadTwitterWatchlist();
      loadTwitterWatchlistStats();
    } else if (activeTab === 'wallet-watchlist') {
      loadWalletWatchlist();
      loadWalletWatchlistStats();
    }
  }, [activeTab]);

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

  useEffect(() => {
    const saved = localStorage.getItem('sifter_wallet');
    if (saved) setWalletAddress(saved);
  }, []);

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

      const response = await fetch(`${API_URL}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tokens: tokensToAnalyze })
      });

      const data = await response.json();

      if (response.ok) {
        setAnalysisResults(data);
        const expanded = {};
        data.results.forEach((_, idx) => {
          expanded[idx] = true;
        });
        setExpandedTokens(expanded);
      } else {
        throw new Error(data.error || 'Analysis failed');
      }
    } catch (error) {
      console.error('Analysis error:', error);
      alert(`Analysis failed: ${error.message}`);
      setActiveTab('analyze');
    }

    setIsAnalyzing(false);
  };

  const handleWalletAnalysis = async () => {
    if (selectedTokens.length === 0) {
      alert('Please select at least one token');
      return;
    }

    setIsAnalyzingWallets(true);
    setActiveTab('wallet-analysis');

    try {
      const tokensToAnalyze = selectedTokens.map(token => {
        const key = `${token.chain}-${token.address}`;
        
        const settings = useGlobalSettings ? {
          days_back: daysBack,
          candle_size: candleSize,
          wallet_window_before: 35,
          wallet_window_after: 0
        } : (tokenSettings[key] || {
          days_back: daysBack,
          candle_size: candleSize,
          wallet_window_before: 35,
          wallet_window_after: 0
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

      const response = await fetch(`${API_URL}/api/wallets/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          tokens: tokensToAnalyze,
          global_settings: {
            min_pump_count: 5,
            wallet_window_before: 35,
            wallet_window_after: 0
          }
        })
      });

      const data = await response.json();

      if (response.ok && data.success) {
        setWalletAnalysisResults(data);
        const expanded = {};
        if (data.top_wallets) {
          data.top_wallets.forEach((_, idx) => {
            expanded[idx] = true;
          });
        }
        setExpandedWallets(expanded);
      } else {
        throw new Error(data.error || 'Wallet analysis failed');
      }
    } catch (error) {
      console.error('Wallet analysis error:', error);
      alert(`Wallet analysis failed: ${error.message}`);
      setActiveTab('analyze');
    }

    setIsAnalyzingWallets(false);
  };

  // ⭐ UPDATED: Add alert settings to wallet watchlist payload
  const addWalletToWatchlist = async (wallet) => {
    try {
      const response = await fetch(`${API_URL}/api/wallets/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          user_id: userId, 
          wallet: {
            wallet_address: wallet.wallet,
            tier: wallet.tier,
            pump_count: wallet.pump_count,
            avg_distance_to_peak: wallet.avg_distance_to_peak_pct,
            avg_roi_to_peak: wallet.avg_roi_to_peak_pct,
            consistency_score: wallet.consistency_score,
            tokens_hit: wallet.token_list.join(', ')
          },
          // ⭐ NEW: Default alert settings for new wallets
          alert_settings: {
            alert_enabled: true,
            alert_on_buy: true,
            alert_on_sell: false,
            min_trade_usd: 100
          }
        })
      });
      
      const data = await response.json();
      if (data.success) {
        alert('✅ Added to wallet watchlist with alerts enabled!');
      }
    } catch (error) {
      console.error('Error adding wallet to watchlist:', error);
    }
  };

  const toggleWalletExpansion = (idx) => {
    setExpandedWallets(prev => ({
      ...prev,
      [idx]: !prev[idx]
    }));
  };

  const clearWalletResults = () => {
    if (confirm('Clear wallet analysis results?')) {
      setWalletAnalysisResults(null);
      setExpandedWallets({});
    }
  };

  const clearResults = () => {
    if (confirm('Clear all analysis results?')) {
      setAnalysisResults(null);
      setExpandedTokens({});
    }
  };

  const toggleTokenExpansion = (idx) => {
    setExpandedTokens(prev => ({
      ...prev,
      [idx]: !prev[idx]
    }));
  };

  const expandAll = () => {
    const expanded = {};
    analysisResults.results.forEach((_, idx) => {
      expanded[idx] = true;
    });
    setExpandedTokens(expanded);
  };

  const collapseAll = () => {
    setExpandedTokens({});
  };

  // Twitter Watchlist functions
  const loadTwitterWatchlist = async () => {
    try {
      const response = await fetch(`${API_URL}/api/watchlist/get?user_id=${userId}`);
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
      const response = await fetch(`${API_URL}/api/watchlist/stats?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setTwitterWatchlistStats(data.stats);
      }
    } catch (error) {
      console.error('Error loading twitter stats:', error);
    }
  };

  const addToTwitterWatchlist = async (account) => {
    try {
      const response = await fetch(`${API_URL}/api/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, account })
      });
      const data = await response.json();
      if (data.success) {
        alert('Added to Twitter watchlist!');
        if (activeTab === 'twitter-watchlist') {
          loadTwitterWatchlist();
        }
      }
    } catch (error) {
      console.error('Error adding to twitter watchlist:', error);
    }
  };

  const removeFromTwitterWatchlist = async (authorId) => {
    if (!confirm('Remove this account from watchlist?')) return;

    try {
      const response = await fetch(`${API_URL}/api/watchlist/remove`, {
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

  const updateTwitterWatchlistNotes = async (authorId, notes) => {
    try {
      const response = await fetch(`${API_URL}/api/watchlist/update`, {
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
      const response = await fetch(`${API_URL}/api/watchlist/update`, {
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

  // Wallet Watchlist functions
  const loadWalletWatchlist = async () => {
    try {
      const response = await fetch(`${API_URL}/api/wallets/watchlist/get?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setWalletWatchlist(data.wallets);
      }
    } catch (error) {
      console.error('Error loading wallet watchlist:', error);
    }
  };

  const loadWalletWatchlistStats = async () => {
    try {
      const response = await fetch(`${API_URL}/api/wallets/watchlist/stats?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setWalletWatchlistStats(data.stats);
      }
    } catch (error) {
      console.error('Error loading wallet stats:', error);
    }
  };

  const removeFromWalletWatchlist = async (walletAddress) => {
    if (!confirm('Remove this wallet from watchlist?')) return;

    try {
      const response = await fetch(`${API_URL}/api/wallets/watchlist/remove`, {
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

  const updateWalletWatchlistNotes = async (walletAddress, notes) => {
    try {
      const response = await fetch(`${API_URL}/api/wallets/watchlist/update`, {
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
      const response = await fetch(`${API_URL}/api/wallets/watchlist/update`, {
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

  return (
    <div className="min-h-screen bg-black text-gray-100">
      <nav className="fixed top-0 w-full z-50 bg-black/80 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 py-3 flex justify-between items-center">
          <div className="text-xl font-bold">
            SIFTER <span className="text-purple-500">KYS</span>
          </div>
          
          <div className="flex gap-3 items-center">
            {/* ⭐ NEW: Wallet Activity Monitor - Bell icon with notifications */}
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
          </div>
        </div>
      </nav>

      <div className="pt-16 max-w-7xl mx-auto px-6 py-6">
        {/* UPDATED: Separate top-level tabs for Twitter and Wallet watchlists */}
        <div className="flex gap-3 mb-6 border-b border-white/10">
          {[
            { id: 'analyze', label: 'Analyze', icon: Search },
            { id: 'results', label: 'Twitter Results', icon: BarChart3 },
            { id: 'wallet-analysis', label: 'Wallet Analysis', icon: Wallet },
            { id: 'twitter-watchlist', label: 'Twitter Watchlist', icon: Users },
            { id: 'wallet-watchlist', label: 'Wallet Watchlist', icon: BookmarkPlus },
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
            </button>
          ))}
        </div>

        {/* Analyze Tab */}
        {activeTab === 'analyze' && (
          <div className="space-y-4">
            <div className="bg-white/5 border border-white/10 rounded-xl p-4">
              <h3 className="text-base font-semibold mb-3">Token Search</h3>
              
              <div className="flex gap-3 mb-3">
                <div className="relative flex-1" ref={searchRef}>
                  <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && searchTokens(searchQuery)}
                    placeholder="Search by token name, ticker, or contract address..."
                    className="w-full bg-black/50 border border-white/10 rounded-lg pl-12 pr-4 py-3 text-sm focus:outline-none focus:border-purple-500"
                  />
                  {isSearching && (
                    <div className="absolute right-4 top-1/2 transform -translate-y-1/2">
                      <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    </div>
                  )}
                </div>

                <button
                  onClick={() => searchTokens(searchQuery)}
                  disabled={isSearching || !searchQuery.trim()}
                  className="px-4 py-3 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/30 rounded-lg font-semibold transition flex items-center gap-2 text-sm"
                >
                  {isSearching ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Searching...
                    </>
                  ) : (
                    <>
                      <Search size={16} />
                      Search
                    </>
                  )}
                </button>
              </div>

              <div className="relative" ref={searchRef}>
                {showDropdown && searchResults.length > 0 && (
                  <div className="absolute top-0 w-full bg-black border border-white/10 rounded-lg shadow-xl max-h-96 overflow-y-auto z-50">
                    {searchResults.map((token, idx) => {
                      const isSelected = selectedTokens.some(
                        t => t.address.toLowerCase() === token.address.toLowerCase() && t.chain === token.chain
                      );
                      
                      return (
                        <div
                          key={`${token.chain}-${token.address}-${idx}`}
                          onClick={() => toggleTokenSelection(token)}
                          className={`p-3 border-b border-white/5 hover:bg-white/5 cursor-pointer ${
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

                {showDropdown && searchQuery && !isSearching && searchResults.length === 0 && (
                  <div className="absolute top-0 w-full bg-black border border-white/10 rounded-lg shadow-xl p-4 text-center z-50">
                    <p className="text-gray-400 text-sm">No tokens found for "{searchQuery}"</p>
                    <p className="text-xs text-gray-500 mt-1">Try a different search term</p>
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

                <div className="space-y-2">
                  {selectedTokens.map((token) => {
                    const key = `${token.chain}-${token.address}`;
                    const settings = tokenSettings[key] || {
                      days_back: daysBack,
                      candle_size: candleSize,
                      t_minus: tMinusWindow,
                      t_plus: tPlusWindow
                    };

                    return (
                      <div
                        key={key}
                        className="bg-black/30 rounded-lg p-3"
                      >
                        <div className="flex justify-between items-start mb-2">
                          <div className="flex-1">
                            <div className="font-semibold text-sm">{token.ticker}</div>
                            <div className="text-xs text-gray-400">{token.chain.toUpperCase()}</div>
                          </div>
                          <button
                            onClick={() => removeToken(token.address, token.chain)}
                            className="p-1 hover:bg-white/10 rounded"
                          >
                            <X size={14} />
                          </button>
                        </div>

                        {!useGlobalSettings && (
                          <div className="mt-3 pt-3 border-t border-white/10">
                            <div className="grid grid-cols-2 gap-2">
                              <div>
                                <label className="block text-xs font-medium mb-1">Days Back</label>
                                <input
                                  type="number"
                                  value={settings.days_back}
                                  onChange={(e) => updateTokenSetting(token.address, token.chain, 'days_back', Math.max(1, Math.min(90, parseInt(e.target.value) || 7)))}
                                  min="1"
                                  max="90"
                                  className="w-full bg-black/50 border border-white/10 rounded px-2 py-1 text-xs focus:outline-none focus:border-purple-500"
                                />
                              </div>

                              <div>
                                <label className="block text-xs font-medium mb-1">Candle</label>
                                <select
                                  value={settings.candle_size}
                                  onChange={(e) => updateTokenSetting(token.address, token.chain, 'candle_size', e.target.value)}
                                  className="w-full bg-black/50 border border-white/10 rounded px-2 py-1 text-xs focus:outline-none focus:border-purple-500"
                                >
                                  <option value="1m">1m</option>
                                  <option value="5m">5m</option>
                                  <option value="15m">15m</option>
                                  <option value="1h">1h</option>
                                  <option value="4h">4h</option>
                                  <option value="1d">1d</option>
                                </select>
                              </div>

                              <div>
                                <label className="block text-xs font-medium mb-1">T-Minus</label>
                                <input
                                  type="number"
                                  value={settings.t_minus}
                                  onChange={(e) => updateTokenSetting(token.address, token.chain, 't_minus', parseInt(e.target.value))}
                                  className="w-full bg-black/50 border border-white/10 rounded px-2 py-1 text-xs focus:outline-none focus:border-purple-500"
                                />
                              </div>

                              <div>
                                <label className="block text-xs font-medium mb-1">T-Plus</label>
                                <input
                                  type="number"
                                  value={settings.t_plus}
                                  onChange={(e) => updateTokenSetting(token.address, token.chain, 't_plus', parseInt(e.target.value))}
                                  className="w-full bg-black/50 border border-white/10 rounded px-2 py-1 text-xs focus:outline-none focus:border-purple-500"
                                />
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                <div className="mt-4 pt-4 border-t border-white/10">
                  <div className="flex items-center gap-2 mb-3">
                    <button
                      onClick={() => setUseGlobalSettings(!useGlobalSettings)}
                      className={`w-12 h-6 rounded-full transition ${
                        useGlobalSettings ? 'bg-purple-600' : 'bg-gray-600'
                      }`}
                    >
                      <div className={`w-5 h-5 bg-white rounded-full transition transform ${
                        useGlobalSettings ? 'translate-x-6' : 'translate-x-1'
                      }`} />
                    </button>
                    <span className="font-semibold text-sm">
                      {useGlobalSettings ? 'Global Settings (Quick Mode)' : 'Per-Token Customization'}
                    </span>
                  </div>

                  {useGlobalSettings && (
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium mb-1">Days Back</label>
                        <input
                          type="number"
                          value={daysBack}
                          onChange={(e) => setDaysBack(Math.max(1, Math.min(90, parseInt(e.target.value) || 7)))}
                          min="1"
                          max="90"
                          className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
                        />
                        <p className="text-xs text-gray-500 mt-1">1-90 days</p>
                      </div>

                      <div>
                        <label className="block text-xs font-medium mb-1">Candle Size</label>
                        <select
                          value={candleSize}
                          onChange={(e) => setCandleSize(e.target.value)}
                          className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
                        >
                          <option value="1m">1 Minute (M1)</option>
                          <option value="5m">5 Minutes (M5)</option>
                          <option value="15m">15 Minutes (M15)</option>
                          <option value="1h">1 Hour</option>
                          <option value="4h">4 Hours</option>
                          <option value="1d">1 Day</option>
                        </select>
                      </div>

                      <div>
                        <label className="block text-xs font-medium mb-1">T-Minus (minutes)</label>
                        <input
                          type="number"
                          value={tMinusWindow}
                          onChange={(e) => setTMinusWindow(parseInt(e.target.value))}
                          className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
                        />
                      </div>

                      <div>
                        <label className="block text-xs font-medium mb-1">T-Plus (minutes)</label>
                        <input
                          type="number"
                          value={tPlusWindow}
                          onChange={(e) => setTPlusWindow(parseInt(e.target.value))}
                          className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
                        />
                      </div>
                    </div>
                  )}
                </div>

                <button
                  onClick={handleAnalysis}
                  disabled={isAnalyzing}
                  className="w-full mt-4 px-4 py-3 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/30 rounded-lg font-semibold transition flex items-center justify-center gap-2 text-sm"
                >
                  {isAnalyzing ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Analyzing {selectedTokens.length} token{selectedTokens.length > 1 ? 's' : ''}...
                    </>
                  ) : (
                    <>
                      <TrendingUp size={18} />
                      Analyze {selectedTokens.length} Token{selectedTokens.length > 1 ? 's' : ''}
                    </>
                  )}
                </button>

                <button
                  onClick={handleWalletAnalysis}
                  disabled={isAnalyzingWallets}
                  className="w-full mt-2 px-4 py-3 bg-green-600 hover:bg-green-700 disabled:bg-green-600/30 rounded-lg font-semibold transition flex items-center justify-center gap-2 text-sm"
                >
                  {isAnalyzingWallets ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Analyzing Wallets...
                    </>
                  ) : (
                    <>
                      <Wallet size={18} />
                      Analyze Wallets (Find Smart Money)
                    </>
                  )}
                </button>
              </div>
            )}

            <div className="grid grid-cols-3 gap-4">
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <TrendingUp className="text-purple-400 mb-2" size={24} />
                <h4 className="font-semibold mb-1">Pump Detection</h4>
                <p className="text-xs text-gray-400">Identifies major volume spikes using precision candle analysis</p>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <Clock className="text-purple-400 mb-2" size={24} />
                <h4 className="font-semibold mb-1">T-35 Window</h4>
                <p className="text-xs text-gray-400">Finds tweets 35 mins before to 10 mins after each pump</p>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <Users className="text-purple-400 mb-2" size={24} />
                <h4 className="font-semibold mb-1">Network Analysis</h4>
                <p className="text-xs text-gray-400">Detects coordinated groups vs organic alpha callers</p>
              </div>
            </div>
          </div>
        )}

        {/* Results Tab */}
        {activeTab === 'results' && (
          <div className="space-y-4">
            {analysisResults ? (
              <>
                <div className="flex justify-between items-center mb-4">
                  <h2 className="text-2xl font-bold">Analysis Results</h2>
                  <div className="flex gap-2">
                    <button
                      onClick={expandAll}
                      className="px-3 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-sm flex items-center gap-2"
                    >
                      <ChevronDown size={16} />
                      Expand All
                    </button>
                    <button
                      onClick={collapseAll}
                      className="px-3 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-sm flex items-center gap-2"
                    >
                      <ChevronUp size={16} />
                      Collapse All
                    </button>
                    <button
                      onClick={clearResults}
                      className="px-3 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 rounded-lg text-sm flex items-center gap-2"
                    >
                      <RotateCcw size={16} />
                      Clear Results
                    </button>
                  </div>
                </div>
                
                <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-4">
                  <h3 className="text-lg font-semibold mb-3">Summary</h3>
                  <div className="grid grid-cols-4 gap-3">
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-purple-400">{analysisResults.summary.total_tokens}</div>
                      <div className="text-xs text-gray-400">Total Tokens</div>
                    </div>
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-green-400">{analysisResults.summary.successful_analyses}</div>
                      <div className="text-xs text-gray-400">Successful</div>
                    </div>
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-blue-400">{analysisResults.summary.total_pumps}</div>
                      <div className="text-xs text-gray-400">Total Pumps</div>
                    </div>
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-yellow-400">{analysisResults.summary.cross_token_accounts || 0}</div>
                      <div className="text-xs text-gray-400">Cross-Token Accounts</div>
                    </div>
                  </div>
                </div>
                
                {analysisResults.results.map((result, idx) => {
                  const isExpanded = expandedTokens[idx];
                  
                  return (
                    <div key={idx} className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
                      <button
                        onClick={() => toggleTokenExpansion(idx)}
                        className="w-full px-4 py-4 flex items-center justify-between hover:bg-white/5 transition"
                      >
                        <div className="flex items-center gap-3">
                          <span className="text-xl font-bold text-purple-400">#{idx + 1}</span>
                          <div className="text-left">
                            <h3 className="text-lg font-semibold">{result.token.ticker}</h3>
                            <p className="text-sm text-gray-400">{result.token.name}</p>
                          </div>
                          <span className={`px-3 py-1 rounded text-sm ${
                            result.success ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                          }`}>
                            {result.success ? '✓ Success' : '✗ Failed'}
                          </span>
                          {result.success && (
                            <span className="px-3 py-1 bg-blue-500/20 text-blue-400 rounded text-sm">
                              {result.rallies} Pump{result.rallies !== 1 ? 's' : ''}
                            </span>
                          )}
                        </div>
                        {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                      </button>
                      
                      {isExpanded && (
                        <div className="px-4 pb-4 border-t border-white/10 pt-4">
                          {result.success ? (
                            <>
                              {result.rally_details && result.rally_details.length > 0 && (
                                <div className="mb-4 space-y-3">
                                  {result.rally_details.map((rally, rallyIdx) => (
                                    <div key={rallyIdx} className="bg-black/30 border border-blue-500/20 rounded-lg p-3">
                                      <div className="flex justify-between items-start mb-2">
                                        <div>
                                          <span className="font-semibold text-sm">Pump #{rallyIdx + 1}</span>
                                          <span className={`ml-2 text-xs px-2 py-0.5 rounded ${
                                            rally.rally_type === 'explosive' ? 'bg-red-500/20 text-red-400' :
                                            rally.rally_type === 'choppy' ? 'bg-yellow-500/20 text-yellow-400' :
                                            'bg-green-500/20 text-green-400'
                                          }`}>
                                            {rally.rally_type}
                                          </span>
                                        </div>
                                        <div className="text-right">
                                          <div className="text-green-400 font-bold text-sm">+{rally.total_gain_pct}%</div>
                                          <div className="text-xs text-gray-400">Peak: +{rally.peak_gain_pct}%</div>
                                        </div>
                                      </div>
                                      
                                      <div className="grid grid-cols-2 gap-2 text-xs">
                                        <div className="text-gray-400">
                                          <span className="text-gray-500">Start:</span> {new Date(rally.start_time * 1000).toLocaleString()}
                                        </div>
                                        <div className="text-gray-400">
                                          <span className="text-gray-500">End:</span> {new Date(rally.end_time * 1000).toLocaleString()}
                                        </div>
                                        <div className="text-gray-400">
                                          <span className="text-gray-500">Candles:</span> {rally.candle_count}
                                        </div>
                                        <div className="text-gray-400">
                                          <span className="text-gray-500">Green Ratio:</span> {rally.green_ratio}%
                                        </div>
                                      </div>
                                      
                                      {rally.volume_data && (
                                        <div className="mt-2 pt-2 border-t border-white/5">
                                          <div className="grid grid-cols-3 gap-2 text-xs">
                                            <div className="text-gray-400">
                                              <span className="text-gray-500">Avg Vol:</span> {formatNumber(rally.volume_data.avg_volume)}
                                            </div>
                                            <div className="text-gray-400">
                                              <span className="text-gray-500">Peak Vol:</span> {formatNumber(rally.volume_data.peak_volume)}
                                            </div>
                                            <div className="text-gray-400">
                                              <span className="text-gray-500">Spike:</span> {rally.volume_data.volume_spike_ratio}x
                                            </div>
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}
                              
                              {result.top_accounts && result.top_accounts.length > 0 ? (
                                <div>
                                  <h4 className="font-semibold mb-2">Top Accounts ({result.top_accounts.length})</h4>
                                  <div className="space-y-2">
                                    {result.top_accounts.slice(0, 10).map((account) => (
                                      <div key={account.author_id} className="bg-black/30 rounded-lg p-3">
                                        <div className="flex justify-between items-center mb-2">
                                          <div className="font-semibold">@{account.username || account.author_id}</div>
                                          <div className="flex items-center gap-2">
                                            <div className="text-purple-400 font-bold">{account.influence_score}</div>
                                            <button
                                              onClick={() => addToTwitterWatchlist(account)}
                                              className="p-1 hover:bg-purple-500/20 rounded text-purple-400"
                                              title="Add to watchlist"
                                            >
                                              <BookmarkPlus size={16} />
                                            </button>
                                          </div>
                                        </div>
                                        <div className="grid grid-cols-3 gap-2 text-xs text-gray-400">
                                          <div>Pumps: {account.pumps_called}</div>
                                          <div>Avg: {account.avg_timing}m</div>
                                          <div>Earliest: {account.earliest_call}m</div>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ) : result.rallies > 0 ? (
                                <div className="p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-lg flex items-start gap-2">
                                  <AlertCircle className="text-yellow-400 flex-shrink-0" size={18} />
                                  <div>
                                    <p className="text-sm text-yellow-400 font-semibold">No Twitter accounts found</p>
                                    <p className="text-xs text-gray-400 mt-1">
                                      The pump occurred but no tweets were found in the analysis window. Try adjusting T-minus/T-plus settings.
                                    </p>
                                  </div>
                                </div>
                              ) : null}
                            </>
                          ) : (
                            <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                              <p className="text-red-400 text-sm">{result.error}</p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </>
            ) : isAnalyzing ? (
              <div className="text-center py-12">
                <div className="w-16 h-16 border-4 border-white/30 border-t-purple-500 rounded-full animate-spin mx-auto mb-4" />
                <p className="text-gray-400">Analyzing tokens...</p>
                <p className="text-sm text-gray-500 mt-2">This may take 1-3 minutes depending on the number of tokens and pumps found</p>
              </div>
            ) : (
              <div className="text-center py-12 text-gray-400">
                <BarChart3 size={48} className="mx-auto mb-3 opacity-50" />
                <p>No analysis results yet. Run an analysis to see results here.</p>
              </div>
            )}
          </div>
        )}

        {/* Wallet Analysis Tab */}
        {activeTab === 'wallet-analysis' && (
          <div className="space-y-4">
            {walletAnalysisResults ? (
              <>
                <div className="flex justify-between items-center mb-4">
                  <h2 className="text-2xl font-bold">Wallet Analysis Results</h2>
                  <button
                    onClick={clearWalletResults}
                    className="px-3 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 rounded-lg text-sm flex items-center gap-2"
                  >
                    <RotateCcw size={16} />
                    Clear Results
                  </button>
                </div>

                <div className="bg-gradient-to-br from-green-900/20 to-green-800/10 border border-green-500/20 rounded-xl p-4">
                  <h3 className="text-lg font-semibold mb-3">Wallet Analysis Summary</h3>
                  <div className="grid grid-cols-4 gap-3">
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-green-400">
                        {walletAnalysisResults.summary.qualified_wallets}
                      </div>
                      <div className="text-xs text-gray-400">Qualified Wallets</div>
                    </div>
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-yellow-400">
                        {walletAnalysisResults.summary.s_tier}
                      </div>
                      <div className="text-xs text-gray-400">S-Tier Wallets</div>
                    </div>
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-blue-400">
                        {walletAnalysisResults.summary.total_rallies}
                      </div>
                      <div className="text-xs text-gray-400">Total Rallies</div>
                    </div>
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-purple-400">
                        {walletAnalysisResults.summary.tokens_analyzed}
                      </div>
                      <div className="text-xs text-gray-400">Tokens Analyzed</div>
                    </div>
                  </div>
                </div>

                <div className="space-y-3">
                  {walletAnalysisResults.top_wallets && walletAnalysisResults.top_wallets.slice(0, 20).map((wallet, idx) => {
                    const isExpanded = expandedWallets[idx];
                    
                    return (
                      <div key={wallet.wallet} className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
                        <button
                          onClick={() => toggleWalletExpansion(idx)}
                          className="w-full px-4 py-4 flex items-center justify-between hover:bg-white/5 transition"
                        >
                          <div className="flex items-center gap-3">
                            <span className="text-lg font-bold text-purple-400">#{idx + 1}</span>
                            <span className={`px-2 py-1 rounded text-sm font-bold ${
                              wallet.tier === 'S' ? 'bg-yellow-500/20 text-yellow-400' :
                              wallet.tier === 'A' ? 'bg-green-500/20 text-green-400' :
                              wallet.tier === 'B' ? 'bg-blue-500/20 text-blue-400' :
                              'bg-gray-500/20 text-gray-400'
                            }`}>
                              Tier {wallet.tier}
                            </span>
                            <div className="text-left">
                              <div className="text-xs font-mono text-gray-400">
                                {wallet.wallet.slice(0, 8)}...{wallet.wallet.slice(-6)}
                              </div>
                            </div>
                          </div>
                          {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                        </button>

                        {isExpanded && (
                          <div className="px-4 pb-4 border-t border-white/10 pt-4">
                            <div className="flex justify-between items-start mb-3">
                              <div className="flex-1">
                                <div className="text-xs font-mono text-gray-400 mb-2">
                                  {wallet.wallet}
                                </div>
                                {wallet.token_list && wallet.token_list.length > 0 && (
                                  <div className="text-xs text-gray-500">
                                    <strong>Tokens:</strong> {wallet.token_list.join(', ')}
                                  </div>
                                )}
                              </div>
                              <button
                                onClick={() => addWalletToWatchlist(wallet)}
                                className="p-2 hover:bg-purple-500/20 rounded text-purple-400"
                                title="Add to wallet watchlist"
                              >
                                <BookmarkPlus size={16} />
                              </button>
                            </div>

                            <div className="grid grid-cols-4 gap-3 mb-3">
                              <div className="bg-black/30 rounded p-2 text-center">
                                <div className="font-bold text-green-400">{wallet.pump_count}</div>
                                <div className="text-xs text-gray-400">Pumps Hit</div>
                              </div>
                              <div className="bg-black/30 rounded p-2 text-center">
                                <div className="font-bold text-yellow-400">{wallet.avg_distance_to_peak_pct}%</div>
                                <div className="text-xs text-gray-400">Avg Distance</div>
                              </div>
                              <div className="bg-black/30 rounded p-2 text-center">
                                <div className="font-bold text-blue-400">{wallet.avg_roi_to_peak_pct}%</div>
                                <div className="text-xs text-gray-400">Avg ROI</div>
                              </div>
                              <div className="bg-black/30 rounded p-2 text-center">
                                <div className="font-bold text-purple-400">{wallet.consistency_score}</div>
                                <div className="text-xs text-gray-400">Consistency</div>
                              </div>
                            </div>

                            {wallet.rally_history && wallet.rally_history.length > 0 && (
                              <div className="mt-3 pt-3 border-t border-white/10">
                                <h4 className="text-xs font-semibold mb-2 text-gray-400">Recent Rallies:</h4>
                                <div className="space-y-1">
                                  {wallet.rally_history.slice(0, 5).map((rally, ridx) => (
                                    <div key={ridx} className="text-xs text-gray-500">
                                      • {rally.token} on {rally.rally_date}: {rally.distance_pct}% to ATH, {rally.roi_pct}% ROI
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            ) : isAnalyzingWallets ? (
              <div className="text-center py-12">
                <div className="w-16 h-16 border-4 border-white/30 border-t-green-500 rounded-full animate-spin mx-auto mb-4" />
                <p className="text-gray-400">Analyzing wallet behavior...</p>
                <p className="text-sm text-gray-500 mt-2">Finding smart money wallets...</p>
              </div>
            ) : (
              <div className="text-center py-12 text-gray-400">
                <Wallet size={48} className="mx-auto mb-3 opacity-50" />
                <p>No wallet analysis yet. Run wallet analysis to find smart money.</p>
              </div>
            )}
          </div>
        )}

        {/* NEW: Twitter Watchlist Tab (Separate) */}
        {activeTab === 'twitter-watchlist' && (
          <div className="space-y-4">
            {twitterWatchlistStats && (
              <div className="grid grid-cols-4 gap-4">
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-2xl font-bold text-purple-400">{twitterWatchlistStats.total_accounts}</div>
                  <div className="text-xs text-gray-400">Total Accounts</div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-2xl font-bold text-green-400">{twitterWatchlistStats.avg_influence}</div>
                  <div className="text-xs text-gray-400">Avg Influence</div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-2xl font-bold text-blue-400">{twitterWatchlistStats.total_pumps_tracked}</div>
                  <div className="text-xs text-gray-400">Total Pumps</div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-sm font-bold text-yellow-400">@{twitterWatchlistStats.best_performer?.username || 'N/A'}</div>
                  <div className="text-xs text-gray-400">Best Performer</div>
                </div>
              </div>
            )}

            {twitterWatchlist.length === 0 ? (
              <div className="bg-white/5 border border-white/10 rounded-lg p-12 text-center">
                <Users className="mx-auto mb-4 text-gray-400" size={48} />
                <h3 className="text-lg font-semibold mb-2">No Accounts in Watchlist</h3>
                <p className="text-sm text-gray-400">
                  Analyze tokens and click the bookmark icon next to accounts to add them here
                </p>
              </div>
            ) : (
              <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                <h3 className="text-lg font-semibold mb-4">
                  Twitter Watchlist ({twitterWatchlist.length} accounts)
                </h3>

                <div className="space-y-3">
                  {twitterWatchlist.map((account) => (
                    <div key={account.author_id} className="bg-black/30 border border-white/10 rounded-lg p-4">
                      <div className="flex justify-between items-start mb-3">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-semibold text-lg">@{account.username || account.author_id}</span>
                            {account.verified && (
                              <span className="text-blue-400">✓</span>
                            )}
                          </div>
                          {account.name && (
                            <div className="text-sm text-gray-400">{account.name}</div>
                          )}
                          {account.followers > 0 && (
                            <div className="text-xs text-gray-500 mt-1">
                              <Users size={12} className="inline mr-1" />
                              {account.followers.toLocaleString()} followers
                            </div>
                          )}
                        </div>

                        <div className="flex gap-2 items-center">
                          <div className="text-right">
                            <div className="text-xl font-bold text-purple-400">{account.influence_score}</div>
                            <div className="text-xs text-gray-400">Influence</div>
                          </div>
                          <button
                            onClick={() => removeFromTwitterWatchlist(account.author_id)}
                            className="p-2 hover:bg-red-500/20 rounded text-red-400"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </div>

                      <div className="grid grid-cols-3 gap-3 mb-3 text-sm">
                        <div className="bg-white/5 rounded p-2 text-center">
                          <div className="font-bold text-green-400">{account.pumps_called}</div>
                          <div className="text-xs text-gray-400">Pumps Called</div>
                        </div>
                        <div className="bg-white/5 rounded p-2 text-center">
                          <div className="font-bold text-blue-400">{account.avg_timing}m</div>
                          <div className="text-xs text-gray-400">Avg Timing</div>
                        </div>
                        <div className="bg-white/5 rounded p-2 text-center">
                          <div className="font-bold text-yellow-400">{new Date(account.added_at).toLocaleDateString()}</div>
                          <div className="text-xs text-gray-400">Added</div>
                        </div>
                      </div>

                      <div className="mb-2">
                        {editingTags === account.author_id ? (
                          <div className="flex gap-2">
                            <input
                              type="text"
                              value={newTags}
                              onChange={(e) => setNewTags(e.target.value)}
                              placeholder="Enter tags (comma separated)"
                              className="flex-1 bg-black/50 border border-white/10 rounded px-3 py-1 text-sm"
                            />
                            <button
                              onClick={() => updateTwitterWatchlistTags(account.author_id, newTags)}
                              className="px-3 py-1 bg-purple-600 rounded text-sm"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => {
                                setEditingTags(null);
                                setNewTags('');
                              }}
                              className="px-3 py-1 bg-white/10 rounded text-sm"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 flex-wrap">
                            <Tag size={14} className="text-gray-400" />
                            {account.tags && account.tags.length > 0 ? (
                              account.tags.map((tag, idx) => (
                                <span key={idx} className="px-2 py-0.5 bg-purple-600/20 border border-purple-500/30 rounded text-xs">
                                  {tag}
                                </span>
                              ))
                            ) : (
                              <span className="text-xs text-gray-500">No tags</span>
                            )}
                            <button
                              onClick={() => {
                                setEditingTags(account.author_id);
                                setNewTags(account.tags ? account.tags.join(', ') : '');
                              }}
                              className="text-xs text-purple-400 hover:text-purple-300"
                            >
                              Edit
                            </button>
                          </div>
                        )}
                      </div>

                      <div>
                        {editingNotes === account.author_id ? (
                          <div className="space-y-2">
                            <textarea
                              value={newNote}
                              onChange={(e) => setNewNote(e.target.value)}
                              placeholder="Add notes about this account..."
                              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                              rows={3}
                            />
                            <div className="flex gap-2">
                              <button
                                onClick={() => updateTwitterWatchlistNotes(account.author_id, newNote)}
                                className="px-3 py-1 bg-purple-600 rounded text-sm"
                              >
                                Save
                              </button>
                              <button
                                onClick={() => {
                                  setEditingNotes(null);
                                  setNewNote('');
                                }}
                                className="px-3 py-1 bg-white/10 rounded text-sm"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-start gap-2">
                            <StickyNote size={14} className="text-gray-400 mt-0.5" />
                            <div className="flex-1">
                              {account.notes ? (
                                <p className="text-sm text-gray-300">{account.notes}</p>
                              ) : (
                                <span className="text-xs text-gray-500">No notes</span>
                              )}
                            </div>
                            <button
                              onClick={() => {
                                setEditingNotes(account.author_id);
                                setNewNote(account.notes || '');
                              }}
                              className="text-xs text-purple-400 hover:text-purple-300"
                            >
                              {account.notes ? 'Edit' : 'Add'}
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* NEW: Wallet Watchlist Tab (Separate) */}
        {activeTab === 'wallet-watchlist' && (
          <div className="space-y-4">
            {walletWatchlistStats && (
              <div className="grid grid-cols-4 gap-4">
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-2xl font-bold text-purple-400">{walletWatchlistStats.total_wallets || 0}</div>
                  <div className="text-xs text-gray-400">Total Wallets</div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-2xl font-bold text-yellow-400">{walletWatchlistStats.s_tier_count || 0}</div>
                  <div className="text-xs text-gray-400">S-Tier Wallets</div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-2xl font-bold text-green-400">{walletWatchlistStats.avg_distance?.toFixed(1) || 0}%</div>
                  <div className="text-xs text-gray-400">Avg Distance</div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-2xl font-bold text-blue-400">{walletWatchlistStats.total_pumps || 0}</div>
                  <div className="text-xs text-gray-400">Total Pumps</div>
                </div>
              </div>
            )}

            {walletWatchlist.length === 0 ? (
              <div className="bg-white/5 border border-white/10 rounded-lg p-12 text-center">
                <Wallet className="mx-auto mb-4 text-gray-400" size={48} />
                <h3 className="text-lg font-semibold mb-2">No Wallets in Watchlist</h3>
                <p className="text-sm text-gray-400">
                  Run wallet analysis and bookmark high-performing wallets to track them here
                </p>
              </div>
            ) : (
              <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                <h3 className="text-lg font-semibold mb-4">
                  Wallet Watchlist ({walletWatchlist.length} wallets)
                </h3>

                <div className="space-y-3">
                  {walletWatchlist.map((wallet) => (
                    <div key={wallet.wallet_address} className="bg-black/30 border border-white/10 rounded-lg p-4">
                      <div className="flex justify-between items-start mb-3">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-2">
                            <span className={`px-2 py-1 rounded text-sm font-bold ${
                              wallet.tier === 'S' ? 'bg-yellow-500/20 text-yellow-400' :
                              wallet.tier === 'A' ? 'bg-green-500/20 text-green-400' :
                              wallet.tier === 'B' ? 'bg-blue-500/20 text-blue-400' :
                              'bg-gray-500/20 text-gray-400'
                            }`}>
                              Tier {wallet.tier}
                            </span>
                          </div>
                          <div className="text-xs font-mono text-gray-400 mb-2">
                            {wallet.wallet_address}
                          </div>
                          {wallet.tokens_hit && (
                            <div className="text-xs text-gray-500">
                              Tokens: {wallet.tokens_hit}
                            </div>
                          )}
                        </div>
                        
                        {/* ⭐ NEW: Alert Settings and Delete buttons */}
                        <div className="flex gap-2 items-center">
                          <button
                            onClick={() => setAlertSettingsWallet(wallet.wallet_address)}
                            className="p-2 hover:bg-purple-500/20 rounded text-purple-400"
                            title="Configure alerts"
                          >
                            <Settings size={16} />
                          </button>
                          
                          <button
                            onClick={() => removeFromWalletWatchlist(wallet.wallet_address)}
                            className="p-2 hover:bg-red-500/20 rounded text-red-400"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </div>

                      <div className="grid grid-cols-4 gap-3 mb-3 text-sm">
                        <div className="bg-white/5 rounded p-2 text-center">
                          <div className="font-bold text-green-400">{wallet.pump_count}</div>
                          <div className="text-xs text-gray-400">Pumps</div>
                        </div>
                        <div className="bg-white/5 rounded p-2 text-center">
                          <div className="font-bold text-yellow-400">{wallet.avg_distance_to_peak}%</div>
                          <div className="text-xs text-gray-400">Avg Distance</div>
                        </div>
                        <div className="bg-white/5 rounded p-2 text-center">
                          <div className="font-bold text-blue-400">{wallet.avg_roi_to_peak}%</div>
                          <div className="text-xs text-gray-400">Avg ROI</div>
                        </div>
                        <div className="bg-white/5 rounded p-2 text-center">
                          <div className="font-bold text-purple-400">{wallet.consistency_score}</div>
                          <div className="text-xs text-gray-400">Consistency</div>
                        </div>
                      </div>

                      <div className="mb-2">
                        {editingTags === wallet.wallet_address ? (
                          <div className="flex gap-2">
                            <input
                              type="text"
                              value={newTags}
                              onChange={(e) => setNewTags(e.target.value)}
                              placeholder="Enter tags (comma separated)"
                              className="flex-1 bg-black/50 border border-white/10 rounded px-3 py-1 text-sm"
                            />
                            <button
                              onClick={() => updateWalletWatchlistTags(wallet.wallet_address, newTags)}
                              className="px-3 py-1 bg-purple-600 rounded text-sm"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => {
                                setEditingTags(null);
                                setNewTags('');
                              }}
                              className="px-3 py-1 bg-white/10 rounded text-sm"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 flex-wrap">
                            <Tag size={14} className="text-gray-400" />
                            {wallet.tags && wallet.tags.length > 0 ? (
                              wallet.tags.map((tag, idx) => (
                                <span key={idx} className="px-2 py-0.5 bg-purple-600/20 border border-purple-500/30 rounded text-xs">
                                  {tag}
                                </span>
                              ))
                            ) : (
                              <span className="text-xs text-gray-500">No tags</span>
                            )}
                            <button
                              onClick={() => {
                                setEditingTags(wallet.wallet_address);
                                setNewTags(wallet.tags ? wallet.tags.join(', ') : '');
                              }}
                              className="text-xs text-purple-400 hover:text-purple-300"
                            >
                              Edit
                            </button>
                          </div>
                        )}
                      </div>

                      <div>
                        {editingNotes === wallet.wallet_address ? (
                          <div className="space-y-2">
                            <textarea
                              value={newNote}
                              onChange={(e) => setNewNote(e.target.value)}
                              placeholder="Add notes about this wallet..."
                              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm"
                              rows={3}
                            />
                            <div className="flex gap-2">
                              <button
                                onClick={() => updateWalletWatchlistNotes(wallet.wallet_address, newNote)}
                                className="px-3 py-1 bg-purple-600 rounded text-sm"
                              >
                                Save
                              </button>
                              <button
                                onClick={() => {
                                  setEditingNotes(null);
                                  setNewNote('');
                                }}
                                className="px-3 py-1 bg-white/10 rounded text-sm"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-start gap-2">
                            <StickyNote size={14} className="text-gray-400 mt-0.5" />
                            <div className="flex-1">
                              {wallet.notes ? (
                                <p className="text-sm text-gray-300">{wallet.notes}</p>
                              ) : (
                                <span className="text-xs text-gray-500">No notes</span>
                              )}
                            </div>
                            <button
                              onClick={() => {
                                setEditingNotes(wallet.wallet_address);
                                setNewNote(wallet.notes || '');
                              }}
                              className="text-xs text-purple-400 hover:text-purple-300"
                            >
                              {wallet.notes ? 'Edit' : 'Add'}
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ⭐ NEW: Alert Settings Modal - renders when a wallet is selected for alert config */}
      {alertSettingsWallet && (
        <WalletAlertSettings
          walletAddress={alertSettingsWallet}
          onClose={() => setAlertSettingsWallet(null)}
          onSave={(settings) => {
            console.log('Alert settings saved:', settings);
            loadWalletWatchlist(); // Refresh the watchlist
            setAlertSettingsWallet(null);
          }}
        />
      )}
    </div>
  );
}