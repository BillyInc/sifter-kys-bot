import React, { useState, useEffect, useRef } from 'react';
import { Search, Users, TrendingUp, Network, Clock, BarChart3, Download, Save, Settings, Upload } from 'lucide-react';
import * as d3 from 'd3';


// Network Graph Component
function NetworkGraph({ data, onNodeClick }) {
  const svgRef = useRef(null);
  const [selectedNode, setSelectedNode] = useState(null);

  useEffect(() => {
    if (!data || !data.nodes || !data.links || !svgRef.current) return;

    const width = 800;
    const height = 600;

    d3.select(svgRef.current).selectAll("*").remove();

    const svg = d3.select(svgRef.current)
      .attr("width", "100%")
      .attr("height", height)
      .attr("viewBox", [0, 0, width, height]);

    const g = svg.append("g");

    const zoom = d3.zoom()
      .scaleExtent([0.5, 5])
      .on("zoom", (event) => g.attr("transform", event.transform));

    svg.call(zoom);

    const simulation = d3.forceSimulation(data.nodes)
      .force("link", d3.forceLink(data.links).id(d => d.id).distance(100))
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2));

    const link = g.append("g")
      .selectAll("line")
      .data(data.links)
      .join("line")
      .attr("stroke", "#6b7280")
      .attr("stroke-width", 2)
      .attr("stroke-opacity", 0.6);

    const node = g.append("g")
      .selectAll("circle")
      .data(data.nodes)
      .join("circle")
      .attr("r", d => 5 + Math.sqrt(d.influence || 1))
      .attr("fill", d => {
        const inf = d.influence || 0;
        return inf > 70 ? "#a855f7" : inf > 40 ? "#3b82f6" : "#6b7280";
      })
      .attr("stroke", "#fff")
      .attr("stroke-width", 2)
      .style("cursor", "pointer")
      .on("click", (e, d) => {
        setSelectedNode(d);
        if (onNodeClick) onNodeClick(d);
      })
      .call(d3.drag()
        .on("start", (e) => {
          if (!e.active) simulation.alphaTarget(0.3).restart();
          e.subject.fx = e.subject.x;
          e.subject.fy = e.subject.y;
        })
        .on("drag", (e) => {
          e.subject.fx = e.x;
          e.subject.fy = e.y;
        })
        .on("end", (e) => {
          if (!e.active) simulation.alphaTarget(0);
          e.subject.fx = null;
          e.subject.fy = null;
        }));

    const labels = g.append("g")
      .selectAll("text")
      .data(data.nodes)
      .join("text")
      .attr("text-anchor", "middle")
      .attr("font-size", 10)
      .attr("fill", "#e5e7eb")
      .attr("dy", -15)
      .text(d => d.username || d.id);

    simulation.on("tick", () => {
      link
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x)
        .attr("y2", d => d.target.y);

      node
        .attr("cx", d => d.x)
        .attr("cy", d => d.y);

      labels
        .attr("x", d => d.x)
        .attr("y", d => d.y);
    });

  }, [data]);

  return (
    <div>
      <svg ref={svgRef} className="w-full bg-black/30 rounded-lg" />
      {selectedNode && (
        <div className="mt-4 bg-purple-900/20 border border-purple-500/30 rounded-lg p-4">
          <div className="flex justify-between">
            <div>
              <h4 className="font-semibold">@{selectedNode.username || selectedNode.id}</h4>
              <p className="text-sm text-gray-400">Influence: {selectedNode.influence || 'N/A'}</p>
            </div>
            <button onClick={() => setSelectedNode(null)} className="text-gray-400">✕</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SifterApp() {
  const [apiKeys, setApiKeys] = useState({
    twitter: '',
    birdeye: '35d3d50f74d94c439f6913a7e82cf994'
  });
  const [isKeysSet, setIsKeysSet] = useState(true);
  const [tokenInput, setTokenInput] = useState('');
  const [timeRange, setTimeRange] = useState('first_7d');
  const [pumpTimeframe, setPumpTimeframe] = useState('5m');
  const [expandedSnaTimeframe, setExpandedSnaTimeframe] = useState('7d');
  const [expandedSnaData, setExpandedSnaData] = useState(null);
  const [loadingExpandedSna, setLoadingExpandedSna] = useState(false);
  const [batchData, setBatchData] = useState(null);
  const [loadingBatch, setLoadingBatch] = useState(false);
  const [csvFile, setCsvFile] = useState(null);
  const [showNetworkGraph, setShowNetworkGraph] = useState(false);
  const [watchlistData, setWatchlistData] = useState(null);
  const [loadingWatchlist, setLoadingWatchlist] = useState(false);
  const [userId, setUserId] = useState('demo_user');
  const [walletAddress, setWalletAddress] = useState(null);
  const [subscriptionTier, setSubscriptionTier] = useState('free');
  const [showWalletMenu, setShowWalletMenu] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisData, setAnalysisData] = useState(null);
  const [activeTab, setActiveTab] = useState('input');

  const timeRanges = [
    { value: 'first_5m', label: 'First 5 Minutes After Launch' },
    { value: 'first_24h', label: 'First 24 Hours After Launch' },
    { value: 'first_7d', label: 'First 7 Days After Launch' },
    { value: 'first_30d', label: 'First 30 Days After Launch' },
    { value: 'last_1h', label: 'Last 1 Hour' },
    { value: 'last_5h', label: 'Last 5 Hours' },
    { value: 'last_24h', label: 'Last 24 Hours' },
    { value: 'last_3d', label: 'Last 3 Days' },
    { value: 'last_7d', label: 'Last 7 Days' },
    { value: 'last_30d', label: 'Last 30 Days' },
    { value: 'all', label: 'All Time' }
  ];

  const pumpTimeframes = [
    { value: '5m', label: '5 Min' },
    { value: '15m', label: '15 Min' }
  ];

  const expandedSnaTimeframes = [
    { value: '3d', label: '3 Days' },
    { value: '7d', label: '7 Days' },
    { value: '30d', label: '30 Days' },
    { value: 'all', label: 'All Time (1 year)' }
  ];

  const handleSaveKeys = () => {
    if (!apiKeys.twitter) {
      alert('Please enter your Twitter Bearer Token');
      return;
    }
    // Store in browser localStorage only - never sent to backend
    localStorage.setItem('sifter_twitter_key', apiKeys.twitter);
    localStorage.setItem('sifter_birdeye_key', apiKeys.birdeye);
    setIsKeysSet(true);
  };

  const handleAnalyze = async () => {
    if (!tokenInput) {
      alert('Please enter a token contract address');
      return;
    }

    setIsAnalyzing(true);
    setActiveTab('results');

    // Real API call to Flask backend
    const API_URL = 'http://localhost:5000';  // Change to your deployed URL
    
    try {
      const response = await fetch(`${API_URL}/api/analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          token_address: tokenInput.trim(),
          time_range: timeRange,
          pump_timeframe: pumpTimeframe,
          twitter_token: localStorage.getItem('sifter_twitter_key'),
          birdeye_key: localStorage.getItem('sifter_birdeye_key')
        })
      });

      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.message || 'Analysis failed');
      }

      setAnalysisData(data);
    } catch (error) {
      console.error('Analysis error:', error);
      alert(`Analysis failed: ${error.message}`);
      setActiveTab('input');
    }

    setIsAnalyzing(false);
  };

  const handleExpandedSna = async () => {
    if (!analysisData || !analysisData.accounts) {
      alert('Please run token analysis first');
      return;
    }

    setLoadingExpandedSna(true);

    const API_URL = 'http://localhost:5000';

    try {
      const accountIds = analysisData.accounts.map(acc => acc.author_id.toString());
      const accountUsernames = analysisData.accounts.map(acc => acc.username);

      const response = await fetch(`${API_URL}/api/expanded-sna`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          account_ids: accountIds,
          account_usernames: accountUsernames,
          twitter_token: localStorage.getItem('sifter_twitter_key'),
          timeframe: expandedSnaTimeframe
        })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || 'Expanded SNA failed');
      }

      setExpandedSnaData(data.results);
    } catch (error) {
      console.error('Expanded SNA error:', error);
      alert(`Expanded SNA failed: ${error.message}`);
    }

    setLoadingExpandedSna(false);
  };

  const handleBatchAnalysis = async () => {
    if (!csvFile && !tokenInput) {
      alert('Please upload a CSV file or paste token addresses');
      return;
    }

    setLoadingBatch(true);
    setActiveTab('batch');

    const API_URL = 'http://localhost:5000';

    try {
      let requestBody = {
        twitter_token: localStorage.getItem('sifter_twitter_key'),
        birdeye_key: localStorage.getItem('sifter_birdeye_key'),
        time_range: timeRange
      };

      if (csvFile) {
        // Read CSV file
        const csvText = await csvFile.text();
        requestBody.csv_data = csvText;
      } else {
        // Parse pasted addresses
        const addresses = tokenInput.split('\n').filter(addr => addr.trim());
        requestBody.tokens = addresses.map(addr => ({
          address: addr.trim(),
          ticker: 'UNKNOWN',
          name: ''
        }));
      }

      const response = await fetch(`${API_URL}/api/batch-analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody)
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || 'Batch analysis failed');
      }

      setBatchData(data);
    } catch (error) {
      console.error('Batch analysis error:', error);
      alert(`Batch analysis failed: ${error.message}`);
      setActiveTab('input');
    }

    setLoadingBatch(false);
  };

  const handleExportCsv = async () => {
    if (!batchData) return;

    const API_URL = 'http://localhost:5000';

    try {
      const response = await fetch(`${API_URL}/api/export-batch-csv`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          cross_token_accounts: batchData.top_accounts,
          filename: 'cross_token_analysis.csv'
        })
      });

      const data = await response.json();

      if (response.ok) {
        // Download CSV
        const blob = new Blob([data.csv_data], { type: 'text/csv' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = data.filename;
        a.click();
        window.URL.revokeObjectURL(url);
      }
    } catch (error) {
      console.error('CSV export error:', error);
      alert('Failed to export CSV');
    }
  };

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (file && file.type === 'text/csv') {
      setCsvFile(file);
    } else {
      alert('Please upload a valid CSV file');
    }
  };

  const loadWatchlist = async () => {
    setLoadingWatchlist(true);
    const API_URL = 'http://localhost:5000';

    try {
      const response = await fetch(`${API_URL}/api/watchlist?user_id=${userId}`);
      const data = await response.json();

      if (response.ok) {
        setWatchlistData(data);
      }
    } catch (error) {
      console.error('Watchlist error:', error);
    }

    setLoadingWatchlist(false);
  };

  const addToWatchlist = async (account) => {
    const API_URL = 'http://localhost:5000';

    try {
      const response = await fetch(`${API_URL}/api/watchlist/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          account: {
            author_id: account.author_id.toString(),
            username: account.username,
            name: account.name,
            followers: account.followers,
            verified: account.verified,
            influence_score: account.influence_score,
            avg_timing: account.avg_timing,
            pumps_called: account.pumps_called,
            tags: [],
            notes: ''
          }
        })
      });

      if (response.ok) {
        alert(`Added @${account.username} to watchlist!`);
        loadWatchlist();
      }
    } catch (error) {
      console.error('Add to watchlist error:', error);
      alert('Failed to add to watchlist');
    }
  };

  const removeFromWatchlist = async (authorId) => {
    const API_URL = 'http://localhost:5000';

    try {
      const response = await fetch(`${API_URL}/api/watchlist/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          author_id: authorId
        })
      });

      if (response.ok) {
        alert('Removed from watchlist');
        loadWatchlist();
      }
    } catch (error) {
      console.error('Remove error:', error);
    }
  };

  useEffect(() => {
    if (activeTab === 'watchlist') {
      loadWatchlist();
    }
  }, [activeTab]);

  // Wallet Connect
  const connectWallet = async (chain = 'solana') => {
    try {
      if (chain === 'solana') {
        if (window.solana && window.solana.isPhantom) {
          const response = await window.solana.connect();
          const address = response.publicKey.toString();
          setWalletAddress(address);
          setUserId(address);
          localStorage.setItem('sifter_wallet', address);
          await checkUserAccess(address);
        } else {
          alert('Please install Phantom wallet');
          window.open('https://phantom.app/', '_blank');
        }
      }
    } catch (error) {
      console.error('Wallet error:', error);
      alert('Failed to connect wallet');
    }
  };

  const disconnectWallet = () => {
    setWalletAddress(null);
    setUserId('demo_user');
    localStorage.removeItem('sifter_wallet');
  };

  const checkUserAccess = async (address) => {
    const API_URL = 'http://localhost:5000';
    try {
      const response = await fetch(`${API_URL}/api/check-access`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wallet_address: address })
      });
      const data = await response.json();
      if (data.authorized) {
        setSubscriptionTier(data.tier);
      }
    } catch (error) {
      console.error('Access check error:', error);
    }
  };

  useEffect(() => {
    const savedWallet = localStorage.getItem('sifter_wallet');
    if (savedWallet) {
      setWalletAddress(savedWallet);
      setUserId(savedWallet);
      checkUserAccess(savedWallet);
    }
  }, []);

  return (
    <div className="min-h-screen bg-black text-gray-100">
      {/* Navigation */}
      <nav className="fixed top-0 w-full z-50 bg-black/80 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 py-4 flex justify-between items-center">
          <div className="text-xl font-bold">
            SIFTER <span className="text-purple-500">KYS</span>
          </div>
          <div className="flex gap-4 items-center">
            {walletAddress ? (
              <div className="relative">
                <button
                  onClick={() => setShowWalletMenu(!showWalletMenu)}
                  className="px-4 py-2 bg-green-600 rounded-lg hover:bg-green-700 transition text-sm flex items-center gap-2"
                >
                  <div className="w-2 h-2 bg-white rounded-full animate-pulse" />
                  {walletAddress.slice(0, 6)}...{walletAddress.slice(-4)}
                </button>

                {showWalletMenu && (
                  <div className="absolute right-0 top-12 bg-black border border-white/10 rounded-lg p-4 w-64 shadow-xl z-50">
                    <div className="text-sm mb-3">
                      <div className="text-gray-400">Subscription Tier</div>
                      <div className="text-lg font-semibold capitalize text-purple-400">
                        {subscriptionTier}
                      </div>
                    </div>
                    <div className="space-y-2">
                      {subscriptionTier === 'free' && (
                        <a
                          href="https://whop.com/your-product-link"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded text-center text-sm"
                        >
                          Upgrade to Pro
                        </a>
                      )}
                      <button
                        onClick={() => {
                          disconnectWallet();
                          setShowWalletMenu(false);
                        }}
                        className="w-full px-4 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 rounded text-sm"
                      >
                        Disconnect
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <button
                onClick={() => connectWallet('solana')}
                className="px-4 py-2 bg-white/5 rounded-lg hover:bg-white/10 transition text-sm"
              >
                Connect Wallet
              </button>
            )}

            <a
              href="https://whop.com/your-product-link"
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 bg-purple-600 rounded-lg hover:bg-purple-700 transition text-sm"
            >
              {subscriptionTier === 'free' ? 'Upgrade' : 'Manage Subscription'}
            </a>

            <button 
              onClick={() => setActiveTab('settings')}
              className="p-2 bg-white/5 rounded-lg hover:bg-white/10 transition"
            >
              <Settings size={20} />
            </button>
          </div>
        </div>
      </nav>

      <div className="pt-20 max-w-7xl mx-auto px-6 py-8">
        {/* API Setup Section */}
        {!isKeysSet && (
          <div className="mb-8 bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-8">
            <h2 className="text-2xl font-bold mb-2">Setup API Credentials</h2>
            <p className="text-gray-400 mb-6 text-sm">
              🔒 Your keys are stored locally in your browser only. They're never sent to our servers.
            </p>
            
            <div className="grid grid-cols-1 gap-6 mb-6">
              <div>
                <label className="block text-sm font-medium mb-2 text-gray-300">
                  Twitter Bearer Token *
                </label>
                <input
                  type="password"
                  value={apiKeys.twitter}
                  onChange={(e) => setApiKeys({...apiKeys, twitter: e.target.value})}
                  placeholder="AAAAAAAAAAAAAAAAAAAAAA..."
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500 font-mono text-sm"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Get yours at <a href="https://developer.twitter.com" target="_blank" className="text-purple-400 hover:underline">developer.twitter.com</a>
                </p>
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-2 text-gray-300">
                  Birdeye API Key (Optional - using shared key)
                </label>
                <input
                  type="password"
                  value={apiKeys.birdeye}
                  onChange={(e) => setApiKeys({...apiKeys, birdeye: e.target.value})}
                  placeholder="Your Birdeye API key"
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500 font-mono text-sm"
                />
              </div>
            </div>

            <button
              onClick={handleSaveKeys}
              className="px-6 py-3 bg-purple-600 hover:bg-purple-700 rounded-lg font-semibold transition"
            >
              Save & Continue
            </button>
          </div>
        )}

        {/* Main Content */}
        {isKeysSet && (
          <>
            {/* Tabs */}
            <div className="flex gap-4 mb-8 border-b border-white/10">
              {[
                { id: 'input', label: 'Analyze', icon: Search },
                { id: 'results', label: 'Results', icon: BarChart3 },
                { id: 'batch', label: 'Batch Analysis', icon: Upload },
                { id: 'watchlist', label: 'Watchlist', icon: Save },
                { id: 'settings', label: 'Settings', icon: Settings }
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 px-4 py-3 border-b-2 transition ${
                    activeTab === tab.id
                      ? 'border-purple-500 text-white'
                      : 'border-transparent text-gray-400 hover:text-white'
                  }`}
                >
                  <tab.icon size={18} />
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Input Tab */}
            {activeTab === 'input' && (
              <div className="space-y-6">
                <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                  <h3 className="text-lg font-semibold mb-4">Token Analysis</h3>
                  
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium mb-2 text-gray-300">
                        Token Contract Address
                      </label>
                      <textarea
                        value={tokenInput}
                        onChange={(e) => setTokenInput(e.target.value)}
                        placeholder="Paste one or multiple contract addresses (one per line)"
                        rows={4}
                        className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500 font-mono text-sm"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium mb-2 text-gray-300">
                          Analysis Timeframe
                        </label>
                        <select
                          value={timeRange}
                          onChange={(e) => setTimeRange(e.target.value)}
                          className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500"
                        >
                          {timeRanges.map((range) => (
                            <option key={range.value} value={range.value}>
                              {range.label}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="block text-sm font-medium mb-2 text-gray-300">
                          Pump Detection Timeframe
                        </label>
                        <select
                          value={pumpTimeframe}
                          onChange={(e) => setPumpTimeframe(e.target.value)}
                          className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500"
                        >
                          {pumpTimeframes.map((tf) => (
                            <option key={tf.value} value={tf.value}>
                              {tf.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <button
                      onClick={handleAnalyze}
                      disabled={isAnalyzing || !tokenInput}
                      className="w-full px-6 py-4 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/30 disabled:cursor-not-allowed rounded-lg font-semibold transition flex items-center justify-center gap-2"
                    >
                      {isAnalyzing ? (
                        <>
                          <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                          Analyzing...
                        </>
                      ) : (
                        <>
                          <Search size={20} />
                          Start Analysis
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {/* Info Cards */}
                <div className="grid grid-cols-3 gap-4">
                  <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                    <div className="flex items-center gap-3 mb-2">
                      <TrendingUp className="text-purple-400" size={20} />
                      <h4 className="font-semibold">Pump Detection</h4>
                    </div>
                    <p className="text-sm text-gray-400">
                      Identifies major volume spikes using precision candle analysis
                    </p>
                  </div>

                  <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                    <div className="flex items-center gap-3 mb-2">
                      <Clock className="text-purple-400" size={20} />
                      <h4 className="font-semibold">T-35 Window</h4>
                    </div>
                    <p className="text-sm text-gray-400">
                      Finds tweets 35 mins before to 10 mins after each pump
                    </p>
                  </div>

                  <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                    <div className="flex items-center gap-3 mb-2">
                      <Network className="text-purple-400" size={20} />
                      <h4 className="font-semibold">Network Analysis</h4>
                    </div>
                    <p className="text-sm text-gray-400">
                      Detects coordinated groups vs organic alpha callers from those tweets
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Batch Analysis Tab */}
            {activeTab === 'batch' && (
              <div className="space-y-6">
                {!batchData ? (
                  <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                    <h3 className="text-lg font-semibold mb-4">Batch Token Analysis</h3>
                    <p className="text-sm text-gray-400 mb-6">
                      Analyze multiple tokens at once and find accounts that consistently call pumps across different tokens.
                    </p>

                    {/* CSV Upload */}
                    <div className="mb-6">
                      <label className="block text-sm font-medium mb-2 text-gray-300">
                        Option 1: Upload CSV File
                      </label>
                      <div className="border-2 border-dashed border-white/10 rounded-lg p-6 text-center hover:border-purple-500/30 transition">
                        <Upload className="mx-auto mb-3 text-gray-400" size={40} />
                        <input
                          type="file"
                          accept=".csv"
                          onChange={handleFileUpload}
                          className="hidden"
                          id="csv-upload"
                        />
                        <label
                          htmlFor="csv-upload"
                          className="cursor-pointer text-purple-400 hover:text-purple-300"
                        >
                          {csvFile ? csvFile.name : 'Click to upload CSV'}
                        </label>
                        <p className="text-xs text-gray-500 mt-2">
                          CSV format: address,ticker,name (one token per line)
                        </p>
                      </div>
                    </div>

                    <div className="text-center text-gray-500 mb-6">- OR -</div>

                    {/* Manual Input */}
                    <div className="mb-6">
                      <label className="block text-sm font-medium mb-2 text-gray-300">
                        Option 2: Paste Token Addresses
                      </label>
                      <textarea
                        value={tokenInput}
                        onChange={(e) => setTokenInput(e.target.value)}
                        placeholder="Paste token contract addresses (one per line)"
                        rows={6}
                        className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500 font-mono text-sm"
                      />
                    </div>

                    {/* Timeframe Selection */}
                    <div className="mb-6">
                      <label className="block text-sm font-medium mb-2 text-gray-300">
                        Analysis Timeframe
                      </label>
                      <select
                        value={timeRange}
                        onChange={(e) => setTimeRange(e.target.value)}
                        className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500"
                      >
                        {timeRanges.map((range) => (
                          <option key={range.value} value={range.value}>
                            {range.label}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Start Button */}
                    <button
                      onClick={handleBatchAnalysis}
                      disabled={loadingBatch || (!csvFile && !tokenInput)}
                      className="w-full px-6 py-4 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/30 disabled:cursor-not-allowed rounded-lg font-semibold transition flex items-center justify-center gap-2"
                    >
                      {loadingBatch ? (
                        <>
                          <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                          Analyzing Tokens...
                        </>
                      ) : (
                        <>
                          <Upload size={20} />
                          Start Batch Analysis
                        </>
                      )}
                    </button>

                    <p className="text-xs text-gray-500 mt-4 text-center">
                      ⚠️ Batch analysis uses significant Twitter API quota. Maximum 50 tokens per batch.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-6">
                    {/* Batch Summary */}
                    <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-6">
                      <div className="flex justify-between items-start mb-4">
                        <div>
                          <h2 className="text-3xl font-bold">Batch Analysis Complete</h2>
                          <p className="text-gray-400">Cross-token comparison results</p>
                        </div>
                        <button
                          onClick={() => setBatchData(null)}
                          className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-sm"
                        >
                          New Analysis
                        </button>
                      </div>

                      <div className="grid grid-cols-4 gap-4">
                        <div className="bg-black/30 rounded-lg p-4 text-center">
                          <div className="text-2xl font-bold text-purple-400">
                            {batchData.summary.total_tokens}
                          </div>
                          <div className="text-sm text-gray-400">Tokens Analyzed</div>
                        </div>
                        <div className="bg-black/30 rounded-lg p-4 text-center">
                          <div className="text-2xl font-bold text-green-400">
                            {batchData.summary.successful_analyses}
                          </div>
                          <div className="text-sm text-gray-400">Successful</div>
                        </div>
                        <div className="bg-black/30 rounded-lg p-4 text-center">
                          <div className="text-2xl font-bold text-purple-400">
                            {batchData.summary.multi_token_accounts}
                          </div>
                          <div className="text-sm text-gray-400">Multi-Token Callers</div>
                        </div>
                        <div className="bg-black/30 rounded-lg p-4 text-center">
                          <div className="text-2xl font-bold text-yellow-400">
                            {batchData.summary.coordinated_pairs}
                          </div>
                          <div className="text-sm text-gray-400">Coordinated Pairs</div>
                        </div>
                      </div>
                    </div>

                    {/* Top Cross-Token Accounts */}
                    <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                      <div className="flex justify-between items-center mb-4">
                        <h3 className="text-xl font-semibold flex items-center gap-2">
                          <Users size={20} className="text-purple-400" />
                          Top Cross-Token Callers
                        </h3>
                        <button
                          onClick={handleExportCsv}
                          className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm flex items-center gap-2"
                        >
                          <Download size={16} />
                          Export CSV
                        </button>
                      </div>

                      <div className="space-y-2">
                        {batchData.top_accounts.slice(0, 20).map((account, idx) => (
                          <div
                            key={account.author_id}
                            className="bg-black/50 border border-white/10 rounded-lg p-4 hover:border-purple-500/30 transition"
                          >
                            <div className="flex justify-between items-start">
                              <div className="flex items-center gap-4 flex-1">
                                <div className="text-2xl font-bold text-purple-400">
                                  #{idx + 1}
                                </div>
                                <div className="flex-1">
                                  <div className="font-semibold text-lg">
                                    @{account.username || `user_${account.author_id}`}
                                  </div>
                                  <div className="text-sm text-gray-400">
                                    {account.name || 'Unknown User'}
                                  </div>
                                  <div className="text-xs text-gray-500 mt-2">
                                    Called {account.tokens_count} tokens • 
                                    {account.total_pumps} total pumps • 
                                    Avg timing: T{account.avg_timing_overall?.toFixed(1)}m
                                  </div>
                                  <div className="text-xs text-gray-400 mt-1">
                                    Tokens: {account.tokens_called?.map(t => t.ticker).join(', ')}
                                  </div>
                                </div>
                              </div>
                              <div className="text-right">
                                <div className="text-sm text-gray-400">Influence Score</div>
                                <div className="text-2xl font-bold text-purple-400">
                                  {Math.round(account.cross_token_influence || 0)}
                                </div>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Coordination Analysis */}
                    {batchData.coordination && batchData.coordination.coordinated_pairs?.length > 0 && (
                      <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                        <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
                          <Network size={20} className="text-red-400" />
                          Coordinated Pairs Detected
                        </h3>
                        <p className="text-sm text-gray-400 mb-4">
                          These accounts appeared together in multiple tokens, suggesting possible coordination.
                        </p>

                        <div className="space-y-2">
                          {batchData.coordination.coordinated_pairs.slice(0, 10).map((pair, idx) => (
                            <div
                              key={idx}
                              className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 flex justify-between items-center"
                            >
                              <div className="text-sm">
                                <span className="font-semibold">User {pair.account_1}</span>
                                {' ↔ '}
                                <span className="font-semibold">User {pair.account_2}</span>
                              </div>
                              <div className="text-sm text-gray-400">
                                Appeared together in <span className="text-red-400 font-semibold">{pair.tokens_together}</span> tokens
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Token Results Table */}
                    <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                      <h3 className="text-xl font-semibold mb-4">Individual Token Results</h3>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-white/10">
                              <th className="text-left py-3 px-4">Token</th>
                              <th className="text-left py-3 px-4">Status</th>
                              <th className="text-right py-3 px-4">Pumps Found</th>
                              <th className="text-left py-3 px-4">Error</th>
                            </tr>
                          </thead>
                          <tbody>
                            {batchData.token_results.map((result, idx) => (
                              <tr key={idx} className="border-b border-white/5 hover:bg-white/5">
                                <td className="py-3 px-4">
                                  <div className="font-semibold">{result.token.ticker}</div>
                                  <div className="text-xs text-gray-500">{result.token.address.slice(0, 8)}...</div>
                                </td>
                                <td className="py-3 px-4">
                                  <span className={`px-2 py-1 rounded text-xs ${
                                    result.success 
                                      ? 'bg-green-500/20 text-green-400' 
                                      : 'bg-red-500/20 text-red-400'
                                  }`}>
                                    {result.success ? '✓ Success' : '✗ Failed'}
                                  </span>
                                </td>
                                <td className="py-3 px-4 text-right">{result.pumps_found}</td>
                                <td className="py-3 px-4 text-gray-400 text-xs">
                                  {result.error || '-'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Results Tab */}
            {activeTab === 'results' && analysisData && (
              <div className="space-y-6">
                {/* Token Summary */}
                <div className="bg-gradient-to-br from-purple-900/20 to-purple-800/10 border border-purple-500/20 rounded-xl p-6">
                  <div className="flex justify-between items-start mb-4">
                    <div>
                      <h2 className="text-3xl font-bold">{analysisData.token.ticker}</h2>
                      <p className="text-gray-400">{analysisData.token.name}</p>
                      <p className="text-xs text-gray-500 font-mono mt-1">{analysisData.token.contract}</p>
                    </div>
                    <div className="text-right">
                      <div className="text-2xl font-bold text-purple-400">
                        {analysisData.summary.total_pumps} Pumps
                      </div>
                      <p className="text-sm text-gray-400">
                        {analysisData.summary.total_tweets} tweets • {analysisData.summary.unique_accounts} accounts
                      </p>
                      <p className="text-xs text-gray-500 mt-1">
                        API Quota: {analysisData.quota_used}/100
                      </p>
                    </div>
                  </div>
                </div>

                {/* Pump Timeline */}
                <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                  <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
                    <TrendingUp size={20} className="text-purple-400" />
                    Pump Timeline
                  </h3>
                  <div className="space-y-3">
                    {analysisData.pumps.map((pump, idx) => (
                      <div
                        key={pump.id}
                        className="bg-black/50 border border-white/10 rounded-lg p-4 hover:border-purple-500/30 transition cursor-pointer"
                      >
                        <div className="flex justify-between items-start mb-3">
                          <div>
                            <div className="font-semibold text-lg">Pump #{idx + 1}</div>
                            <div className="text-sm text-gray-400">{pump.start_time}</div>
                            <div className="text-xs text-gray-500 mt-1">
                              Type: <span className="text-purple-400">{pump.type}</span> • 
                              Duration: {pump.length * 5}min ({pump.length} candles)
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="text-2xl font-bold text-green-400">
                              +{pump.gain}%
                            </div>
                            <div className="text-sm text-gray-400">
                              Peak: +{pump.peak_gain}%
                            </div>
                          </div>
                        </div>
                        <div className="flex gap-4 text-sm">
                          <div>
                            <span className="text-gray-500">Tweets:</span>{' '}
                            <span className="text-white">{pump.tweets_found}</span>
                            <span className="text-gray-500"> ({pump.high_confidence_tweets} high conf)</span>
                          </div>
                          <div>
                            <span className="text-gray-500">Green:</span>{' '}
                            <span className="text-green-400">{pump.green_ratio}%</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Top Accounts */}
                <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                  <div className="flex justify-between items-center mb-4">
                    <h3 className="text-xl font-semibold flex items-center gap-2">
                      <Users size={20} className="text-purple-400" />
                      Top Early Callers
                    </h3>
                    <div className="flex gap-2">
                      <button 
                        onClick={() => {
                          analysisData.accounts.slice(0, 10).forEach(acc => addToWatchlist(acc));
                        }}
                        className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm flex items-center gap-2"
                      >
                        <Save size={16} />
                        Save Top 10 to Watchlist
                      </button>
                    </div>
                  </div>

                  <div className="space-y-2">
                    {analysisData.accounts.map((account, idx) => (
                      <div
                        key={account.author_id}
                        className="bg-black/50 border border-white/10 rounded-lg p-4 hover:border-purple-500/30 transition"
                      >
                        <div className="flex justify-between items-start">
                          <div className="flex items-center gap-4 flex-1">
                            <div className="text-2xl font-bold text-purple-400">
                              #{idx + 1}
                            </div>
                            <div className="flex-1">
                              <div className="font-semibold text-lg flex items-center gap-2">
                                @{account.username || `user_${account.author_id}`}
                                {account.verified && <span className="text-blue-400">✓</span>}
                                {analysisData.network.bridges?.includes(account.author_id) && (
                                  <span className="px-2 py-0.5 bg-yellow-500/20 border border-yellow-500/30 rounded text-xs text-yellow-400">
                                    BRIDGE
                                  </span>
                                )}
                              </div>
                              <div className="text-sm text-gray-400">
                                {account.name || 'Unknown'} • {account.followers?.toLocaleString() || 0} followers
                              </div>
                              <div className="text-xs text-gray-500 mt-1">
                                {account.pumps_called} pumps called • 
                                Avg timing: T{account.avg_timing}m • 
                                Earliest: T{account.earliest_call}m
                              </div>
                              
                              {/* SNA Metrics */}
                              {account.sna_metrics && (
                                <div className="mt-2 pt-2 border-t border-white/5">
                                  <div className="grid grid-cols-3 gap-3 text-xs">
                                    <div>
                                      <span className="text-gray-500">Betweenness:</span>{' '}
                                      <span className="text-purple-400 font-semibold">
                                        {account.sna_metrics.betweenness_centrality}
                                      </span>
                                    </div>
                                    <div>
                                      <span className="text-gray-500">Eigenvector:</span>{' '}
                                      <span className="text-purple-400 font-semibold">
                                        {account.sna_metrics.eigenvector_centrality}
                                      </span>
                                    </div>
                                    <div>
                                      <span className="text-gray-500">Degree:</span>{' '}
                                      <span className="text-purple-400 font-semibold">
                                        {account.sna_metrics.degree_centrality}
                                      </span>
                                    </div>
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="text-sm text-gray-400">Influence Score</div>
                            <div className="text-2xl font-bold text-purple-400">
                              {Math.round(account.influence_score)}
                            </div>
                            <div className="text-xs text-gray-500 mt-1">
                              {account.high_confidence_count} high conf tweets
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Network Analysis */}
                <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                  <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
                    <Network size={20} className="text-purple-400" />
                    Social Network Analysis
                  </h3>
                  
                  {analysisData.network.message ? (
                    <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4 text-center">
                      <p className="text-yellow-400">{analysisData.network.message}</p>
                    </div>
                  ) : (
                    <>
                      {/* Overall Assessment */}
                      <div className={`mb-6 p-4 rounded-lg border-2 ${
                        analysisData.network.coordinated 
                          ? 'bg-red-500/10 border-red-500/30' 
                          : 'bg-green-500/10 border-green-500/30'
                      }`}>
                        <div className="text-center">
                          <div className="text-2xl font-bold mb-2">
                            {analysisData.network.coordinated ? '⚠️ LIKELY COORDINATED' : '✅ LIKELY ORGANIC'}
                          </div>
                          <div className="text-sm text-gray-400">
                            Coordination Indicators: {analysisData.network.coordination_indicators}/3
                          </div>
                        </div>
                      </div>

                      {/* Metrics Grid */}
                      <div className="grid grid-cols-4 gap-4 mb-6">
                        <div className="bg-black/50 border border-white/10 rounded-lg p-4 text-center">
                          <div className="text-sm text-gray-400 mb-1">Network Type</div>
                          <div className="text-xl font-bold capitalize">{analysisData.network.topology}</div>
                        </div>
                        
                        <div className="bg-black/50 border border-white/10 rounded-lg p-4 text-center">
                          <div className="text-sm text-gray-400 mb-1">Reciprocity</div>
                          <div className="text-xl font-bold">
                            {analysisData.network.reciprocity.toFixed(2)}
                          </div>
                          <div className="text-xs text-gray-500 mt-1">
                            {analysisData.network.reciprocity > 0.7 ? 'High' : 
                             analysisData.network.reciprocity > 0.3 ? 'Medium' : 'Low'}
                          </div>
                        </div>
                        
                        <div className="bg-black/50 border border-white/10 rounded-lg p-4 text-center">
                          <div className="text-sm text-gray-400 mb-1">Network Density</div>
                          <div className="text-xl font-bold">
                            {(analysisData.network.density * 100).toFixed(1)}%
                          </div>
                        </div>
                        
                        <div className="bg-black/50 border border-white/10 rounded-lg p-4 text-center">
                          <div className="text-sm text-gray-400 mb-1">Communities</div>
                          <div className="text-xl font-bold">{analysisData.network.communities}</div>
                        </div>
                      </div>

                      {/* Topology Details */}
                      {analysisData.network.topology_details && (
                        <div className="bg-black/50 border border-white/10 rounded-lg p-4 mb-6">
                          <h4 className="font-semibold mb-3">Topology Analysis</h4>
                          <p className="text-sm text-gray-400 mb-3">
                            {analysisData.network.topology_details.description}
                          </p>
                          <div className="grid grid-cols-2 gap-4 text-sm">
                            <div>
                              <span className="text-gray-500">Centralization:</span>{' '}
                              <span className="text-white">
                                {analysisData.network.topology_details.centralization}
                              </span>
                            </div>
                            <div>
                              <span className="text-gray-500">Clustering:</span>{' '}
                              <span className="text-white">
                                {analysisData.network.topology_details.clustering}
                              </span>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Temporal Coordination */}
                      {analysisData.network.temporal_coordination && (
                        <div className="bg-black/50 border border-white/10 rounded-lg p-4 mb-6">
                          <h4 className="font-semibold mb-3">Temporal Coordination</h4>
                          <div className="flex justify-between items-center mb-3">
                            <span className="text-sm text-gray-400">Coordination Score</span>
                            <span className={`text-lg font-bold ${
                              analysisData.network.temporal_coordination.coordinated 
                                ? 'text-red-400' 
                                : 'text-green-400'
                            }`}>
                              {analysisData.network.temporal_coordination.coordination_score}%
                            </span>
                          </div>
                          <div className="text-sm text-gray-400">
                            Found {analysisData.network.temporal_coordination.clusters_found} clusters 
                            where 3+ accounts tweeted within 5 minutes
                          </div>
                        </div>
                      )}

                      {/* Bridge Accounts */}
                      {analysisData.network.bridges && analysisData.network.bridges.length > 0 && (
                        <div className="bg-black/50 border border-white/10 rounded-lg p-4 mb-6">
                          <h4 className="font-semibold mb-3">🌉 Bridge Accounts (High Value)</h4>
                          <p className="text-sm text-gray-400 mb-2">
                            These accounts connect different groups - removing them fragments the network
                          </p>
                          <div className="flex flex-wrap gap-2">
                            {analysisData.network.bridges.slice(0, 5).map((bridgeId) => (
                              <span 
                                key={bridgeId} 
                                className="px-3 py-1 bg-purple-500/20 border border-purple-500/30 rounded-full text-sm"
                              >
                                User {bridgeId}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Network Graph Placeholder */}
                      <div className="bg-black/50 border border-white/10 rounded-lg p-6">
                        <div className="flex justify-between items-center mb-4">
                          <h4 className="font-semibold">Interactive Network Graph</h4>
                          <button
                            onClick={() => setShowNetworkGraph(!showNetworkGraph)}
                            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm"
                          >
                            {showNetworkGraph ? 'Hide Graph' : 'View Full Graph'}
                          </button>
                        </div>

                        {showNetworkGraph && analysisData.network.visualization_data ? (
                          <NetworkGraph
                            data={analysisData.network.visualization_data}
                            onNodeClick={(node) => console.log('Clicked node:', node)}
                          />
                        ) : (
                          <div className="h-96 flex items-center justify-center text-center text-gray-400">
                            <div>
                              <Network size={48} className="mx-auto mb-3 opacity-50" />
                              <p>Interactive Network Graph</p>
                              <p className="text-sm mt-1">
                                {analysisData.network.total_nodes} nodes • {analysisData.network.total_edges} connections
                              </p>
                              <button
                                onClick={() => setShowNetworkGraph(true)}
                                className="mt-4 px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm"
                              >
                                View Full Graph
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>

                {/* Expanded SNA Section */}
                <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                  <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
                    <Network size={20} className="text-purple-400" />
                    Expanded Interaction Analysis
                  </h3>
                  <p className="text-sm text-gray-400 mb-4">
                    Analyze how the top accounts interact with each other (mentions, replies, retweets) over a longer timeframe
                  </p>

                  <div className="flex gap-4 mb-4">
                    <select
                      value={expandedSnaTimeframe}
                      onChange={(e) => setExpandedSnaTimeframe(e.target.value)}
                      className="flex-1 bg-black/50 border border-white/10 rounded-lg px-4 py-3 focus:outline-none focus:border-purple-500"
                    >
                      {expandedSnaTimeframes.map((tf) => (
                        <option key={tf.value} value={tf.value}>
                          {tf.label}
                        </option>
                      ))}
                    </select>

                    <button
                      onClick={handleExpandedSna}
                      disabled={loadingExpandedSna}
                      className="px-6 py-3 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/30 disabled:cursor-not-allowed rounded-lg font-semibold transition flex items-center gap-2"
                    >
                      {loadingExpandedSna ? (
                        <>
                          <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                          Analyzing...
                        </>
                      ) : (
                        'Analyze Interactions'
                      )}
                    </button>
                  </div>

                  {expandedSnaData && (
                    <div className="space-y-4">
                      {/* Summary */}
                      <div className={`p-4 rounded-lg border-2 ${
                        expandedSnaData.coordination.likely_coordinated 
                          ? 'bg-red-500/10 border-red-500/30' 
                          : 'bg-green-500/10 border-green-500/30'
                      }`}>
                        <div className="text-center">
                          <div className="text-xl font-bold mb-1">
                            {expandedSnaData.coordination.likely_coordinated 
                              ? '⚠️ COORDINATED INTERACTIONS DETECTED' 
                              : '✅ ORGANIC INTERACTION PATTERNS'}
                          </div>
                          <div className="text-sm text-gray-400">
                            Found {expandedSnaData.summary.total_interactions} interactions 
                            between {analysisData.accounts.length} accounts 
                            over {expandedSnaData.summary.timeframe_days} days
                          </div>
                        </div>
                      </div>

                      {/* Interaction Stats */}
                      <div className="grid grid-cols-4 gap-3">
                        <div className="bg-black/50 border border-white/10 rounded-lg p-3 text-center">
                          <div className="text-sm text-gray-400 mb-1">Mentions</div>
                          <div className="text-xl font-bold">{expandedSnaData.interactions.mentions.length}</div>
                        </div>
                        <div className="bg-black/50 border border-white/10 rounded-lg p-3 text-center">
                          <div className="text-sm text-gray-400 mb-1">Replies</div>
                          <div className="text-xl font-bold">{expandedSnaData.interactions.replies.length}</div>
                        </div>
                        <div className="bg-black/50 border border-white/10 rounded-lg p-3 text-center">
                          <div className="text-sm text-gray-400 mb-1">Retweets</div>
                          <div className="text-xl font-bold">{expandedSnaData.interactions.retweets.length}</div>
                        </div>
                        <div className="bg-black/50 border border-white/10 rounded-lg p-3 text-center">
                          <div className="text-sm text-gray-400 mb-1">Reciprocity</div>
                          <div className="text-xl font-bold">{expandedSnaData.metrics.reciprocity}</div>
                        </div>
                      </div>

                      {/* Metrics */}
                      <div className="bg-black/50 border border-white/10 rounded-lg p-4">
                        <h4 className="font-semibold mb-3">Network Metrics</h4>
                        <div className="grid grid-cols-3 gap-4 text-sm">
                          <div>
                            <span className="text-gray-500">Density:</span>{' '}
                            <span className="text-white">{expandedSnaData.metrics.density}</span>
                          </div>
                          <div>
                            <span className="text-gray-500">Clustering:</span>{' '}
                            <span className="text-white">{expandedSnaData.metrics.clustering}</span>
                          </div>
                          <div>
                            <span className="text-gray-500">Strong Components:</span>{' '}
                            <span className="text-white">{expandedSnaData.metrics.strong_components}</span>
                          </div>
                        </div>
                      </div>

                      {/* Coordination Indicators */}
                      <div className="bg-black/50 border border-white/10 rounded-lg p-4">
                        <h4 className="font-semibold mb-3">Coordination Indicators</h4>
                        <div className="space-y-2 text-sm">
                          <div className="flex justify-between">
                            <span>High Reciprocity (&gt;0.7)</span>
                            <span className={expandedSnaData.coordination.indicators.high_reciprocity ? 'text-red-400' : 'text-green-400'}>
                              {expandedSnaData.coordination.indicators.high_reciprocity ? '✗ YES' : '✓ NO'}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span>High Clustering (&gt;0.6)</span>
                            <span className={expandedSnaData.coordination.indicators.high_clustering ? 'text-red-400' : 'text-green-400'}>
                              {expandedSnaData.coordination.indicators.high_clustering ? '✗ YES' : '✓ NO'}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span>Tight Core Component</span>
                            <span className={expandedSnaData.coordination.indicators.tight_component ? 'text-red-400' : 'text-green-400'}>
                              {expandedSnaData.coordination.indicators.tight_component ? '✗ YES' : '✓ NO'}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Export Options */}
                <div className="flex gap-4">
                  <button className="flex-1 px-6 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg font-semibold transition flex items-center justify-center gap-2">
                    <Download size={20} />
                    Export CSV
                  </button>
                  <button className="flex-1 px-6 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg font-semibold transition flex items-center justify-center gap-2">
                    <Download size={20} />
                    Export JSON
                  </button>
                </div>
              </div>
            )}

            {/* Watchlist Tab */}
            {activeTab === 'watchlist' && (
              <div className="space-y-6">
                {loadingWatchlist ? (
                  <div className="flex justify-center items-center h-64">
                    <div className="w-8 h-8 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  </div>
                ) : watchlistData && watchlistData.accounts.length > 0 ? (
                  <>
                    {/* Watchlist Stats */}
                    <div className="grid grid-cols-4 gap-4">
                      <div className="bg-white/5 border border-white/10 rounded-lg p-4 text-center">
                        <div className="text-2xl font-bold text-purple-400">
                          {watchlistData.stats.total_accounts}
                        </div>
                        <div className="text-sm text-gray-400">Total Accounts</div>
                      </div>
                      <div className="bg-white/5 border border-white/10 rounded-lg p-4 text-center">
                        <div className="text-2xl font-bold text-purple-400">
                          {watchlistData.stats.avg_influence.toFixed(1)}
                        </div>
                        <div className="text-sm text-gray-400">Avg Influence</div>
                      </div>
                      <div className="bg-white/5 border border-white/10 rounded-lg p-4 text-center">
                        <div className="text-2xl font-bold text-purple-400">
                          {watchlistData.stats.total_pumps_tracked}
                        </div>
                        <div className="text-sm text-gray-400">Pumps Tracked</div>
                      </div>
                      <div className="bg-white/5 border border-white/10 rounded-lg p-4 text-center">
                        <div className="text-sm text-gray-400 mb-1">Best Performer</div>
                        <div className="font-semibold">
                          @{watchlistData.stats.best_performer.username || 'N/A'}
                        </div>
                      </div>
                    </div>

                    {/* Watchlist Accounts */}
                    <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                      <h3 className="text-xl font-semibold mb-4">Your Watchlist</h3>
                      <div className="space-y-2">
                        {watchlistData.accounts.map((account, idx) => (
                          <div
                            key={account.id}
                            className="bg-black/50 border border-white/10 rounded-lg p-4 hover:border-purple-500/30 transition"
                          >
                            <div className="flex justify-between items-start">
                              <div className="flex-1">
                                <div className="font-semibold text-lg flex items-center gap-2">
                                  @{account.username}
                                  {account.verified && <span className="text-blue-400">✓</span>}
                                </div>
                                <div className="text-sm text-gray-400">{account.name}</div>
                                <div className="text-xs text-gray-500 mt-2">
                                  {account.pumps_called} pumps • Avg timing: T{account.avg_timing?.toFixed(1)}m
                                </div>
                                {account.tags && account.tags.length > 0 && (
                                  <div className="flex gap-2 mt-2">
                                    {account.tags.map((tag, i) => (
                                      <span
                                        key={i}
                                        className="px-2 py-1 bg-purple-500/20 border border-purple-500/30 rounded text-xs"
                                      >
                                        {tag}
                                      </span>
                                    ))}
                                  </div>
                                )}
                                {account.notes && (
                                  <div className="text-sm text-gray-400 mt-2 italic">
                                    "{account.notes}"
                                  </div>
                                )}
                              </div>
                              <div className="flex flex-col items-end gap-2">
                                <div className="text-right">
                                  <div className="text-sm text-gray-400">Influence</div>
                                  <div className="text-xl font-bold text-purple-400">
                                    {account.influence_score?.toFixed(1)}
                                  </div>
                                </div>
                                <button
                                  onClick={() => removeFromWatchlist(account.author_id)}
                                  className="px-3 py-1 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 rounded text-sm"
                                >
                                  Remove
                                </button>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                    <div className="text-center py-12 text-gray-400">
                      <Users size={48} className="mx-auto mb-3 opacity-50" />
                      <p>No accounts in watchlist yet</p>
                      <p className="text-sm mt-1">Analyze tokens to discover alpha callers</p>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Settings Tab */}
            {activeTab === 'settings' && (
              <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                <h3 className="text-xl font-semibold mb-4">Settings</h3>
                <button
                  onClick={() => {
                    localStorage.removeItem('sifter_twitter_key');
                    localStorage.removeItem('sifter_birdeye_key');
                    setIsKeysSet(false);
                    setActiveTab('input');
                  }}
                  className="px-6 py-3 bg-red-600 hover:bg-red-700 rounded-lg font-semibold transition"
                >
                  Reset API Keys
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}