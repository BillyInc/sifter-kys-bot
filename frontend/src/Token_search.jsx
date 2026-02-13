import React, { useState, useEffect, useRef } from 'react';
import { Search, CheckSquare, Square, ExternalLink } from 'lucide-react';

export default function TokenSearch({ onTokensSelected }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedTokens, setSelectedTokens] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const searchRef = useRef(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event) {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setShowResults(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
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
        const formattedResults = data.pairs.map(pair => ({
          address: pair.baseToken.address,
          ticker: pair.baseToken.symbol,
          name: pair.baseToken.name,
          chain: pair.chainId,
          dex: pair.dexId,
          price: pair.priceUsd,
          liquidity: pair.liquidity?.usd || 0,
          volume24h: pair.volume?.h24 || 0,
          priceChange24h: pair.priceChange?.h24 || 0,
          pairAddress: pair.pairAddress,
          url: pair.url
        }));

        formattedResults.sort((a, b) => b.liquidity - a.liquidity);
        setSearchResults(formattedResults.slice(0, 20));
      } else {
        setSearchResults([]);
      }
    } catch (error) {
      console.error('Search error:', error);
      setSearchResults([]);
    }

    setIsSearching(false);
  };

  // FIXED: Debounced search - Clear old results IMMEDIATELY
  useEffect(() => {
    // Clear results immediately when query changes
    setSearchResults([]);
    setShowResults(false);
    
    const timer = setTimeout(() => {
      if (searchQuery.trim()) {
        searchTokens(searchQuery.trim());
        setShowResults(true);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  // FIXED: Prevent duplicate selections by checking address AND chain
  const toggleTokenSelection = (token) => {
    // Check if this exact token (by address AND chain) is already selected
    const isSelected = selectedTokens.some(
      t => t.address.toLowerCase() === token.address.toLowerCase() && 
           t.chain === token.chain
    );
    
    if (isSelected) {
      // Remove the token
      setSelectedTokens(selectedTokens.filter(
        t => !(t.address.toLowerCase() === token.address.toLowerCase() && t.chain === token.chain)
      ));
    } else {
      // Add the token
      setSelectedTokens([...selectedTokens, token]);
    }
    
    // FIXED: Don't close dropdown or clear search - let user keep selecting
    // setShowResults(false);
    // setSearchQuery('');
  };

  const removeToken = (address, chain) => {
    setSelectedTokens(selectedTokens.filter(
      t => !(t.address.toLowerCase() === address.toLowerCase() && t.chain === chain)
    ));
  };

  const clearAll = () => {
    setSelectedTokens([]);
  };

  // Notify parent component of selection changes
  useEffect(() => {
    if (onTokensSelected) {
      onTokensSelected(selectedTokens);
    }
  }, [selectedTokens, onTokensSelected]);

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
    <div className="space-y-3">
      {/* Search Input - Auto-search only */}
      <div className="relative" ref={searchRef}>
        <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onFocus={() => searchResults.length > 0 && setShowResults(true)}
          placeholder="Search tokens by name, ticker, or contract address..."
          className="w-full bg-black/50 border border-white/10 rounded-lg pl-12 pr-4 py-3 text-sm focus:outline-none focus:border-purple-500 text-white"
        />
        {isSearching && (
          <div className="absolute right-4 top-1/2 transform -translate-y-1/2">
            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          </div>
        )}

        {/* Search Results Dropdown */}
        {showResults && searchResults.length > 0 && (
          <div className="absolute top-full mt-2 w-full bg-black border border-white/10 rounded-lg shadow-xl max-h-96 overflow-y-auto z-50">
            {searchResults.map((token, idx) => {
              const isSelected = selectedTokens.some(
                t => t.address.toLowerCase() === token.address.toLowerCase() && 
                     t.chain === token.chain
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

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-white text-sm">{token.ticker}</span>
                        <span className="text-xs px-2 py-0.5 bg-white/10 rounded text-gray-300">
                          {token.chain.toUpperCase()}
                        </span>
                        <span className="text-xs text-gray-500">{token.dex}</span>
                      </div>
                      
                      <div className="text-xs text-gray-400 mb-1">{token.name}</div>
                      
                      <div className="flex items-center gap-3 text-xs">
                        <div>
                          <span className="text-gray-500">Price: </span>
                          <span className="text-white">{formatPrice(token.price)}</span>
                        </div>
                        <div>
                          <span className="text-gray-500">Liq: </span>
                          <span className="text-white">{formatNumber(token.liquidity)}</span>
                        </div>
                        <div>
                          <span className="text-gray-500">24h: </span>
                          <span className={token.priceChange24h >= 0 ? 'text-green-400' : 'text-red-400'}>
                            {token.priceChange24h >= 0 ? '+' : ''}{token.priceChange24h?.toFixed(2)}%
                          </span>
                        </div>
                      </div>
                      
                      <div className="text-xs text-gray-500 mt-1 font-mono truncate">
                        CA: {token.address}
                      </div>
                    </div>

                    <a
                      href={token.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="text-gray-400 hover:text-purple-400 transition mt-1"
                    >
                      <ExternalLink size={14} />
                    </a>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* No Results */}
        {showResults && searchQuery && !isSearching && searchResults.length === 0 && (
          <div className="absolute top-full mt-2 w-full bg-black border border-white/10 rounded-lg shadow-xl p-4 text-center z-50">
            <p className="text-gray-400 text-sm">No tokens found for "{searchQuery}"</p>
            <p className="text-xs text-gray-500 mt-1">Try a different search term</p>
          </div>
        )}
      </div>

      {/* Selected Tokens Panel */}
      {selectedTokens.length > 0 && (
        <div className="bg-purple-900/20 border border-purple-500/30 rounded-lg p-3">
          <div className="flex justify-between items-center mb-2">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <CheckSquare className="text-purple-400" size={16} />
              Selected: {selectedTokens.length} {selectedTokens.length === 1 ? 'token' : 'tokens'}
            </h3>
            <button
              onClick={clearAll}
              className="text-xs text-gray-400 hover:text-white transition"
            >
              Clear All
            </button>
          </div>

          <div className="space-y-2">
            {selectedTokens.map((token) => (
              <div
                key={`${token.chain}-${token.address}`}
                className="bg-black/50 border border-white/10 rounded-lg p-2 flex items-center justify-between"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold text-white text-sm">{token.ticker}</span>
                    <span className="text-xs px-2 py-0.5 bg-white/10 rounded text-gray-300">
                      {token.chain.toUpperCase()}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500 font-mono truncate">
                    {token.address}
                  </div>
                </div>
                
                <button
                  onClick={() => removeToken(token.address, token.chain)}
                  className="text-red-400 hover:text-red-300 transition text-xs ml-2"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Helper Text */}
      <div className="text-xs text-gray-500">
        💡 Tip: Select multiple tokens to compare top callers across different launches
      </div>
    </div>
  );
}