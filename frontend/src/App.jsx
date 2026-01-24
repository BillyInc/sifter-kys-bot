import React, { useState, useEffect, useRef } from 'react';
import { Search, CheckSquare, Square, TrendingUp, Clock, Settings, Wallet, BarChart3, BookmarkPlus, X, ExternalLink, Users, Trash2, Tag, StickyNote } from 'lucide-react';

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
  
  // FIXED Issue 2: Per-token customization state
  const [useGlobalSettings, setUseGlobalSettings] = useState(true);
  const [tokenSettings, setTokenSettings] = useState({});
  
  // Global settings
  const [analysisTimeframe, setAnalysisTimeframe] = useState('first_7d');
  const [pumpTimeframe, setPumpTimeframe] = useState('5m');
  const [tMinusWindow, setTMinusWindow] = useState(35);
  const [tPlusWindow, setTPlusWindow] = useState(10);
  
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResults, setAnalysisResults] = useState(null);
  
  // FIXED Issue 1: Watchlist state
  const [watchlist, setWatchlist] = useState([]);
  const [watchlistStats, setWatchlistStats] = useState(null);
  const [editingNotes, setEditingNotes] = useState(null);
  const [editingTags, setEditingTags] = useState(null);
  const [newNote, setNewNote] = useState('');
  const [newTags, setNewTags] = useState('');

  const API_URL = 'http://localhost:5000';
  const userId = 'demo_user'; // In production, get from wallet/auth

  useEffect(() => {
    function handleClickOutside(event) {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // FIXED Issue 1: Load watchlist when tab changes
  useEffect(() => {
    if (activeTab === 'watchlist') {
      loadWatchlist();
      loadWatchlistStats();
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
      // FIXED Issue 2: Remove token-specific settings
      const key = `${token.chain}-${token.address}`;
      const newSettings = { ...tokenSettings };
      delete newSettings[key];
      setTokenSettings(newSettings);
    } else {
      setSelectedTokens([...selectedTokens, token]);
      // FIXED Issue 2: Initialize settings for new token
      if (!useGlobalSettings) {
        const key = `${token.chain}-${token.address}`;
        setTokenSettings({
          ...tokenSettings,
          [key]: {
            analysis_timeframe: analysisTimeframe,
            candle_size: pumpTimeframe,
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

  // FIXED Issue 2: Update individual token settings
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
          analysis_timeframe: analysisTimeframe,
          candle_size: pumpTimeframe,
          t_minus: tMinusWindow,
          t_plus: tPlusWindow
        } : (tokenSettings[key] || {
          analysis_timeframe: analysisTimeframe,
          candle_size: pumpTimeframe,
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

  // FIXED Issue 1: Watchlist functions
  const loadWatchlist = async () => {
    try {
      const response = await fetch(`${API_URL}/api/watchlist/get?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setWatchlist(data.accounts);
      }
    } catch (error) {
      console.error('Error loading watchlist:', error);
    }
  };

  const loadWatchlistStats = async () => {
    try {
      const response = await fetch(`${API_URL}/api/watchlist/stats?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setWatchlistStats(data.stats);
      }
    } catch (error) {
      console.error('Error loading stats:', error);
    }
  };

  const addToWatchlist = async (account) => {
    try {
      const response = await fetch(`${API_URL}/api/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, account })
      });
      const data = await response.json();
      if (data.success) {
        alert('Added to watchlist!');
        if (activeTab === 'watchlist') {
          loadWatchlist();
        }
      }
    } catch (error) {
      console.error('Error adding to watchlist:', error);
    }
  };

  const removeFromWatchlist = async (authorId) => {
    if (!confirm('Remove this account from watchlist?')) return;

    try {
      const response = await fetch(`${API_URL}/api/watchlist/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, author_id: authorId })
      });
      const data = await response.json();
      if (data.success) {
        loadWatchlist();
        loadWatchlistStats();
      }
    } catch (error) {
      console.error('Error removing from watchlist:', error);
    }
  };

  const updateWatchlistNotes = async (authorId, notes) => {
    try {
      const response = await fetch(`${API_URL}/api/watchlist/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, author_id: authorId, notes })
      });
      const data = await response.json();
      if (data.success) {
        loadWatchlist();
        setEditingNotes(null);
        setNewNote('');
      }
    } catch (error) {
      console.error('Error updating notes:', error);
    }
  };

  const updateWatchlistTags = async (authorId, tags) => {
    try {
      const tagsArray = tags.split(',').map(t => t.trim()).filter(t => t);
      const response = await fetch(`${API_URL}/api/watchlist/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, author_id: authorId, tags: tagsArray })
      });
      const data = await response.json();
      if (data.success) {
        loadWatchlist();
        setEditingTags(null);
        setNewTags('');
      }
    } catch (error) {
      console.error('Error updating tags:', error);
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
        {/* FIXED Issue 1 & 7: Updated tabs */}
        <div className="flex gap-3 mb-6 border-b border-white/10">
          {[
            { id: 'analyze', label: 'Analyze', icon: Search },
            { id: 'results', label: 'Results', icon: BarChart3 },
            { id: 'watchlist', label: 'Watchlist', icon: BookmarkPlus },
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
                      analysis_timeframe: analysisTimeframe,
                      candle_size: pumpTimeframe,
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

                        {/* FIXED Issue 2: Per-token settings UI */}
                        {!useGlobalSettings && (
                          <div className="mt-3 pt-3 border-t border-white/10">
                            <div className="grid grid-cols-2 gap-2">
                              <div>
                                <label className="block text-xs font-medium mb-1">Timeframe</label>
                                <select
                                  value={settings.analysis_timeframe}
                                  onChange={(e) => updateTokenSetting(token.address, token.chain, 'analysis_timeframe', e.target.value)}
                                  className="w-full bg-black/50 border border-white/10 rounded px-2 py-1 text-xs focus:outline-none focus:border-purple-500"
                                >
                                  <option value="first_5m">First 5m</option>
                                  <option value="first_24h">First 24h</option>
                                  <option value="first_7d">First 7d</option>
                                  <option value="first_30d">First 30d</option>
                                  <option value="last_1h">Last 1h</option>
                                  <option value="last_24h">Last 24h</option>
                                  <option value="last_7d">Last 7d</option>
                                  <option value="last_30d">Last 30d</option>
                                  <option value="all">All Time</option>
                                </select>
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

                {/* FIXED Issue 7: Settings only in Analyze tab */}
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
                        <label className="block text-xs font-medium mb-1">Analysis Timeframe</label>
                        <select
                          value={analysisTimeframe}
                          onChange={(e) => setAnalysisTimeframe(e.target.value)}
                          className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
                        >
                          <option value="first_5m">First 5 Minutes After Launch</option>
                          <option value="first_24h">First 24 Hours After Launch</option>
                          <option value="first_7d">First 7 Days After Launch</option>
                          <option value="first_30d">First 30 Days After Launch</option>
                          <option value="last_1h">Last 1 Hour</option>
                          <option value="last_24h">Last 24 Hours</option>
                          <option value="last_7d">Last 7 Days</option>
                          <option value="last_30d">Last 30 Days</option>
                          <option value="all">All Time</option>
                        </select>
                      </div>

                      <div>
                        <label className="block text-xs font-medium mb-1">Candle Size</label>
                        <select
                          value={pumpTimeframe}
                          onChange={(e) => setPumpTimeframe(e.target.value)}
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
                <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-4">
                  <h2 className="text-xl font-bold mb-3">Analysis Complete</h2>
                  <div className="grid grid-cols-3 gap-3">
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-purple-400">{analysisResults.summary.total_tokens}</div>
                      <div className="text-xs text-gray-400">Tokens Analyzed</div>
                    </div>
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-green-400">{analysisResults.summary.successful_analyses}</div>
                      <div className="text-xs text-gray-400">Successful</div>
                    </div>
                    <div className="bg-black/30 rounded-lg p-3 text-center">
                      <div className="text-xl font-bold text-yellow-400">{analysisResults.summary.cross_token_accounts || 0}</div>
                      <div className="text-xs text-gray-400">Cross-Token Accounts</div>
                    </div>
                  </div>
                </div>

                {analysisResults.results.map((result, idx) => (
                  <div key={idx} className="bg-white/5 border border-white/10 rounded-xl p-4">
                    <div className="flex justify-between items-start mb-3">
                      <div>
                        <h3 className="text-lg font-semibold">{result.token.ticker}</h3>
                        <p className="text-sm text-gray-400">{result.token.name}</p>
                      </div>
                      <span className={`px-3 py-1 rounded text-sm ${
                        result.success ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                      }`}>
                        {result.success ? '✓ Success' : '✗ Failed'}
                      </span>
                    </div>

                    {result.success && (
                      <>
                        {result.rally_details && result.rally_details.length > 0 && (
                          <div className="mb-4 space-y-3">
                            <div className="flex items-center gap-2 mb-2">
                              <TrendingUp className="text-blue-400" size={16} />
                              <span className="font-semibold text-blue-400">
                                {result.rally_details.length} Pump{result.rally_details.length > 1 ? 's' : ''} Detected
                              </span>
                            </div>

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
                                    {/* FIXED Issue 4: Now using total_gain_pct from backend */}
                                    <div className="text-green-400 font-bold text-sm">+{rally.total_gain_pct}%</div>
                                    <div className="text-xs text-gray-400">Peak: +{rally.peak_gain_pct}%</div>
                                  </div>
                                </div>

                                <div className="grid grid-cols-2 gap-2 text-xs">
                                  {/* FIXED Issue 3: Using Unix timestamp directly (no * 1000 on string) */}
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

                                {/* FIXED Issue 5: Using volume_data object */}
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

                        {result.rallies > 0 && (!result.rally_details || result.rally_details.length === 0) && (
                          <div className="mb-4 p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg">
                            <div className="flex items-center gap-2 mb-1">
                              <TrendingUp className="text-blue-400" size={16} />
                              <span className="font-semibold text-blue-400">
                                {result.rallies} Pump{result.rallies > 1 ? 's' : ''} Detected
                              </span>
                            </div>
                            <p className="text-xs text-gray-400">
                              Found {result.rallies} significant price movement{result.rallies > 1 ? 's' : ''} during analysis period
                            </p>
                          </div>
                        )}

                        {result.top_accounts && result.top_accounts.length > 0 ? (
                          <div>
                            <h4 className="font-semibold mb-2 flex items-center justify-between">
                              <span>Top Accounts ({result.top_accounts.length})</span>
                            </h4>
                            <div className="space-y-2">
                              {result.top_accounts.slice(0, 10).map((account) => (
                                <div key={account.author_id} className="bg-black/30 rounded-lg p-3">
                                  <div className="flex justify-between items-center mb-2">
                                    <div className="font-semibold">@{account.username || account.author_id}</div>
                                    <div className="flex items-center gap-2">
                                      <div className="text-purple-400 font-bold">{account.influence_score}</div>
                                      <button
                                        onClick={() => addToWatchlist(account)}
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
                          <div className="p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
                            <p className="text-sm text-yellow-400">
                              ⚠️ No Twitter accounts found for this token's pumps
                            </p>
                            <p className="text-xs text-gray-400 mt-1">
                              The pump occurred but no tweets were found in the analysis window.
                            </p>
                          </div>
                        ) : null}
                      </>
                    )}

                    {!result.success && (
                      <p className="text-red-400 text-sm">{result.error}</p>
                    )}
                  </div>
                ))}
              </>
            ) : (
              <div className="text-center py-12 text-gray-400">
                <BarChart3 size={48} className="mx-auto mb-3 opacity-50" />
                <p>No analysis results yet. Run an analysis to see results here.</p>
              </div>
            )}
          </div>
        )}

        {/* FIXED Issue 1: Watchlist Tab */}
        {activeTab === 'watchlist' && (
          <div className="space-y-4">
            {watchlistStats && (
              <div className="grid grid-cols-4 gap-4">
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-2xl font-bold text-purple-400">{watchlistStats.total_accounts}</div>
                  <div className="text-xs text-gray-400">Total Accounts</div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-2xl font-bold text-green-400">{watchlistStats.avg_influence}</div>
                  <div className="text-xs text-gray-400">Avg Influence</div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-2xl font-bold text-blue-400">{watchlistStats.total_pumps_tracked}</div>
                  <div className="text-xs text-gray-400">Total Pumps</div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                  <div className="text-sm font-bold text-yellow-400">@{watchlistStats.best_performer?.username || 'N/A'}</div>
                  <div className="text-xs text-gray-400">Best Performer</div>
                </div>
              </div>
            )}

            {watchlist.length === 0 ? (
              <div className="bg-white/5 border border-white/10 rounded-lg p-12 text-center">
                <BookmarkPlus className="mx-auto mb-4 text-gray-400" size={48} />
                <h3 className="text-lg font-semibold mb-2">No Accounts in Watchlist</h3>
                <p className="text-sm text-gray-400">
                  Analyze tokens and click the bookmark icon next to accounts to add them here
                </p>
              </div>
            ) : (
              <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                <h3 className="text-lg font-semibold mb-4">
                  Watchlist ({watchlist.length} accounts)
                </h3>

                <div className="space-y-3">
                  {watchlist.map((account) => (
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
                            onClick={() => removeFromWatchlist(account.author_id)}
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
                              onClick={() => updateWatchlistTags(account.author_id, newTags)}
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
                                onClick={() => updateWatchlistNotes(account.author_id, newNote)}
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
      </div>
    </div>
  );
}