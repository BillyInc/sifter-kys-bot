import React, { useState, useEffect } from 'react';
import { BookmarkPlus, Trash2, Tag, StickyNote, TrendingUp, Users, Search, Wallet, Settings, Bell, BellOff } from 'lucide-react';
import WalletAlertSettings from './WalletAlertSettings'; // NEW IMPORT

export default function Watchlist({ userId, apiUrl }) {
  // Tab state
  const [activeWatchlistTab, setActiveWatchlistTab] = useState('accounts');
  
  // Twitter watchlist state
  const [watchlist, setWatchlist] = useState([]);
  const [groups, setGroups] = useState([]);
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [editingNotes, setEditingNotes] = useState(null);
  const [editingTags, setEditingTags] = useState(null);
  const [newNote, setNewNote] = useState('');
  const [newTags, setNewTags] = useState('');
  const [stats, setStats] = useState(null);

  // Wallet watchlist state
  const [walletWatchlist, setWalletWatchlist] = useState([]);
  const [walletStats, setWalletStats] = useState(null);

  // NEW: Alert settings modal state
  const [alertSettingsWallet, setAlertSettingsWallet] = useState(null);

  useEffect(() => {
    if (activeWatchlistTab === 'accounts') {
      loadWatchlist();
      loadStats();
    } else {
      loadWalletWatchlist();
      loadWalletStats();
    }
    loadGroups();
  }, [userId, activeWatchlistTab]);

  // [Previous Twitter watchlist functions remain the same...]
  const loadWatchlist = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`${apiUrl}/api/watchlist/get?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setWatchlist(data.accounts);
      }
    } catch (error) {
      console.error('Error loading watchlist:', error);
    }
    setIsLoading(false);
  };

  const loadGroups = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/watchlist/groups?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setGroups(data.groups);
      }
    } catch (error) {
      console.error('Error loading groups:', error);
    }
  };

  const loadStats = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/watchlist/stats?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setStats(data.stats);
      }
    } catch (error) {
      console.error('Error loading stats:', error);
    }
  };

  const removeAccount = async (authorId) => {
    if (!confirm('Remove this account from watchlist?')) return;
    try {
      const response = await fetch(`${apiUrl}/api/watchlist/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, author_id: authorId })
      });
      const data = await response.json();
      if (data.success) {
        loadWatchlist();
        loadStats();
      }
    } catch (error) {
      console.error('Error removing account:', error);
    }
  };

  const updateNotes = async (authorId, notes) => {
    try {
      const response = await fetch(`${apiUrl}/api/watchlist/update`, {
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

  const updateTags = async (authorId, tags) => {
    try {
      const tagsArray = tags.split(',').map(t => t.trim()).filter(t => t);
      const response = await fetch(`${apiUrl}/api/watchlist/update`, {
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

  // Wallet watchlist functions
  const loadWalletWatchlist = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/get?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setWalletWatchlist(data.wallets);
      }
    } catch (error) {
      console.error('Error loading wallet watchlist:', error);
    }
    setIsLoading(false);
  };

  const loadWalletStats = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/stats?user_id=${userId}`);
      const data = await response.json();
      if (data.success) {
        setWalletStats(data.stats);
      }
    } catch (error) {
      console.error('Error loading wallet stats:', error);
    }
  };

  const removeWallet = async (walletAddress) => {
    if (!confirm('Remove this wallet from watchlist?')) return;
    try {
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, wallet_address: walletAddress })
      });
      const data = await response.json();
      if (data.success) {
        loadWalletWatchlist();
        loadWalletStats();
      }
    } catch (error) {
      console.error('Error removing wallet:', error);
    }
  };

  const updateWalletNotes = async (walletAddress, notes) => {
    try {
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/update`, {
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

  const updateWalletTags = async (walletAddress, tags) => {
    try {
      const tagsArray = tags.split(',').map(t => t.trim()).filter(t => t);
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/update`, {
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

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="w-12 h-12 border-4 border-purple-600/30 border-t-purple-600 rounded-full animate-spin mx-auto mb-4" />
        <p className="text-gray-400">Loading watchlist...</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Tab Switcher */}
      <div className="flex gap-3 border-b border-white/10">
        <button
          onClick={() => setActiveWatchlistTab('accounts')}
          className={`flex items-center gap-2 px-4 py-2 border-b-2 transition ${
            activeWatchlistTab === 'accounts'
              ? 'border-purple-500 text-white'
              : 'border-transparent text-gray-400 hover:text-white'
          }`}
        >
          <Users size={16} />
          Twitter Accounts
        </button>
        <button
          onClick={() => setActiveWatchlistTab('wallets')}
          className={`flex items-center gap-2 px-4 py-2 border-b-2 transition ${
            activeWatchlistTab === 'wallets'
              ? 'border-purple-500 text-white'
              : 'border-transparent text-gray-400 hover:text-white'
          }`}
        >
          <Wallet size={16} />
          Smart Money Wallets
        </button>
      </div>

      {/* Twitter Accounts Tab */}
      {activeWatchlistTab === 'accounts' && (
        <>
          {stats && (
            <div className="grid grid-cols-4 gap-4">
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-purple-400">{stats.total_accounts}</div>
                <div className="text-xs text-gray-400">Total Accounts</div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-green-400">{stats.avg_influence}</div>
                <div className="text-xs text-gray-400">Avg Influence</div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-blue-400">{stats.total_pumps_tracked}</div>
                <div className="text-xs text-gray-400">Total Pumps</div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-sm font-bold text-yellow-400">@{stats.best_performer?.username || 'N/A'}</div>
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
                    {/* [Previous Twitter account display code - unchanged] */}
                    <div className="flex justify-between items-start mb-3">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-semibold text-lg">@{account.username || account.author_id}</span>
                          {account.verified && <span className="text-blue-400">✓</span>}
                        </div>
                        {account.name && <div className="text-sm text-gray-400">{account.name}</div>}
                      </div>
                      <div className="flex gap-2 items-center">
                        <div className="text-right">
                          <div className="text-xl font-bold text-purple-400">{account.influence_score}</div>
                          <div className="text-xs text-gray-400">Influence</div>
                        </div>
                        <button
                          onClick={() => removeAccount(account.author_id)}
                          className="p-2 hover:bg-red-500/20 rounded text-red-400"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>
                    {/* ... rest of Twitter account card ... */}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Wallet Watchlist Tab - ENHANCED WITH ALERT SETTINGS */}
      {activeWatchlistTab === 'wallets' && (
        <>
          {walletStats && (
            <div className="grid grid-cols-4 gap-4">
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-purple-400">{walletStats.total_wallets || 0}</div>
                <div className="text-xs text-gray-400">Total Wallets</div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-yellow-400">{walletStats.s_tier_count || 0}</div>
                <div className="text-xs text-gray-400">S-Tier Wallets</div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-green-400">{walletStats.avg_distance?.toFixed(1) || 0}%</div>
                <div className="text-xs text-gray-400">Avg Distance</div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-blue-400">{walletStats.total_pumps || 0}</div>
                <div className="text-xs text-gray-400">Total Pumps</div>
              </div>
            </div>
          )}

          {walletWatchlist.length === 0 ? (
            <div className="bg-white/5 border border-white/10 rounded-lg p-12 text-center">
              <Wallet className="mx-auto mb-4 text-gray-400" size={48} />
              <h3 className="text-lg font-semibold mb-2">No Wallets in Watchlist</h3>
              <p className="text-sm text-gray-400">
                Run wallet analysis and add high-performing wallets here
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
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`px-2 py-1 rounded text-sm font-bold ${
                            wallet.tier === 'S' ? 'bg-yellow-500/20 text-yellow-400' :
                            wallet.tier === 'A' ? 'bg-green-500/20 text-green-400' :
                            wallet.tier === 'B' ? 'bg-blue-500/20 text-blue-400' :
                            'bg-gray-500/20 text-gray-400'
                          }`}>
                            Tier {wallet.tier}
                          </span>

                          {/* NEW: Alert Status Indicator */}
                          {wallet.alert_enabled ? (
                            <span className="flex items-center gap-1 px-2 py-1 bg-green-500/20 text-green-400 rounded text-xs">
                              <Bell size={12} />
                              Alerts ON
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 px-2 py-1 bg-gray-500/20 text-gray-400 rounded text-xs">
                              <BellOff size={12} />
                              Alerts OFF
                            </span>
                          )}
                        </div>
                        <div className="text-xs font-mono text-gray-400 mb-2">
                          {wallet.wallet_address}
                        </div>
                        {wallet.tokens_hit && (
                          <div className="text-xs text-gray-500">
                            <strong>Tokens:</strong> {wallet.tokens_hit}
                          </div>
                        )}
                      </div>

                      {/* NEW: Alert Settings + Remove Buttons */}
                      <div className="flex gap-2">
                        <button
                          onClick={() => setAlertSettingsWallet(wallet.wallet_address)}
                          className="p-2 hover:bg-purple-500/20 rounded text-purple-400"
                          title="Configure alerts"
                        >
                          <Settings size={16} />
                        </button>
                        <button
                          onClick={() => removeWallet(wallet.wallet_address)}
                          className="p-2 hover:bg-red-500/20 rounded text-red-400"
                          title="Remove wallet"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>

                    {/* Performance Stats */}
                    <div className="grid grid-cols-4 gap-3 mb-3 text-sm">
                      <div className="bg-white/5 rounded p-2 text-center">
                        <div className="font-bold text-green-400">{wallet.pump_count}</div>
                        <div className="text-xs text-gray-400">Pumps</div>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <div className="font-bold text-yellow-400">{wallet.avg_distance_to_peak?.toFixed(1)}%</div>
                        <div className="text-xs text-gray-400">Distance</div>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <div className="font-bold text-blue-400">{wallet.avg_roi_to_peak?.toFixed(1)}%</div>
                        <div className="text-xs text-gray-400">Avg ROI</div>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <div className="font-bold text-purple-400">{wallet.consistency_score?.toFixed(1)}</div>
                        <div className="text-xs text-gray-400">Consistency</div>
                      </div>
                    </div>

                    {/* NEW: Alert Settings Summary */}
                    {wallet.alert_enabled && (
                      <div className="mb-3 p-2 bg-purple-500/10 border border-purple-500/30 rounded text-xs">
                        <span className="text-purple-400 font-semibold">Alert Config:</span>
                        <span className="text-gray-300 ml-2">
                          {wallet.alert_on_buy && 'Buys'}
                          {wallet.alert_on_buy && wallet.alert_on_sell && ' + '}
                          {wallet.alert_on_sell && 'Sells'}
                          {' '}≥ ${wallet.min_trade_usd || 100}
                        </span>
                      </div>
                    )}

                    {/* Tags - unchanged */}
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
                            onClick={() => updateWalletTags(wallet.wallet_address, newTags)}
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

                    {/* Notes - unchanged */}
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
                              onClick={() => updateWalletNotes(wallet.wallet_address, newNote)}
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
        </>
      )}

      {/* NEW: Alert Settings Modal */}
      {alertSettingsWallet && (
        <WalletAlertSettings
          walletAddress={alertSettingsWallet}
          onClose={() => setAlertSettingsWallet(null)}
          onSave={(settings) => {
            console.log('Alert settings saved:', settings);
            loadWalletWatchlist(); // Refresh to show new settings
          }}
        />
      )}
    </div>
  );
}