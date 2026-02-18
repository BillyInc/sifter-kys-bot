import React, { useState, useEffect } from 'react';
import { BookmarkPlus, Trash2, Tag, StickyNote, Users, Wallet, Settings, Bell, BellOff, AlertCircle, CheckCircle, X } from 'lucide-react';
import WalletAlertSettings from './WalletAlertSettings';
import { supabase } from './lib/supabase';

// ─── Toast Notification ───────────────────────────────────────────────────────
function Toast({ message, type = 'error', onDismiss }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 4000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  const styles = {
    error:   'bg-red-900/90 border-red-500/50 text-red-200',
    success: 'bg-green-900/90 border-green-500/50 text-green-200',
  };
  const Icon = type === 'error' ? AlertCircle : CheckCircle;

  return (
    <div className={`fixed bottom-4 right-4 z-50 flex items-center gap-2 px-4 py-3 rounded-lg border text-sm shadow-xl ${styles[type]}`}>
      <Icon size={16} />
      <span>{message}</span>
      <button onClick={onDismiss} className="ml-2 opacity-60 hover:opacity-100">
        <X size={14} />
      </button>
    </div>
  );
}

// ─── Inline Confirmation Dialog ───────────────────────────────────────────────
function ConfirmDelete({ onConfirm, onCancel, isDeleting }) {
  return (
    <div className="flex items-center gap-2 mt-2 p-2 bg-red-950/50 border border-red-500/30 rounded-lg">
      <span className="text-xs text-red-300 flex-1">Remove from watchlist?</span>
      <button
        onClick={onConfirm}
        disabled={isDeleting}
        className="px-2 py-1 bg-red-600 hover:bg-red-700 disabled:opacity-50 rounded text-xs font-semibold transition"
      >
        {isDeleting ? 'Removing…' : 'Yes, remove'}
      </button>
      <button
        onClick={onCancel}
        disabled={isDeleting}
        className="px-2 py-1 bg-white/10 hover:bg-white/20 disabled:opacity-50 rounded text-xs transition"
      >
        Cancel
      </button>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function Watchlist({ userId, apiUrl }) {
  const [activeWatchlistTab, setActiveWatchlistTab] = useState('accounts');

  // Twitter watchlist state
  const [watchlist, setWatchlist] = useState([]);
  const [groups, setGroups] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [editingNotes, setEditingNotes] = useState(null);
  const [editingTags, setEditingTags] = useState(null);
  const [newNote, setNewNote] = useState('');
  const [newTags, setNewTags] = useState('');
  const [stats, setStats] = useState(null);

  // Wallet watchlist state
  const [walletWatchlist, setWalletWatchlist] = useState([]);
  const [walletStats, setWalletStats] = useState(null);

  // Delete confirmation state — tracks which item is pending delete
  const [pendingDeleteAccount, setPendingDeleteAccount] = useState(null);
  const [pendingDeleteWallet, setPendingDeleteWallet] = useState(null);
  const [isDeletingAccount, setIsDeletingAccount] = useState(false);
  const [isDeletingWallet, setIsDeletingWallet] = useState(false);

  // Toast notification state
  const [toast, setToast] = useState(null); // { message, type }

  // Alert settings modal state
  const [alertSettingsWallet, setAlertSettingsWallet] = useState(null);

  const showToast = (message, type = 'error') => setToast({ message, type });
  const dismissToast = () => setToast(null);

  const getHeaders = async () => {
    const { data: { session } } = await supabase.auth.getSession();
    return {
      'Content-Type': 'application/json',
      ...(session?.access_token ? { 'Authorization': `Bearer ${session.access_token}` } : {})
    };
  };

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

  // ─── Twitter watchlist functions ──────────────────────────────────────────

  const loadWatchlist = async () => {
    setIsLoading(true);
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/watchlist/get?user_id=${userId}`, { headers });
      if (!response.ok) throw new Error(`Server error: ${response.status}`);
      const data = await response.json();
      if (data.success) setWatchlist(data.accounts);
    } catch (error) {
      console.error('Error loading watchlist:', error);
      showToast('Failed to load watchlist. Please try again.');
    }
    setIsLoading(false);
  };

  const loadGroups = async () => {
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/watchlist/groups?user_id=${userId}`, { headers });
      if (!response.ok) return;
      const data = await response.json();
      if (data.success) setGroups(data.groups);
    } catch (error) {
      console.error('Error loading groups:', error);
    }
  };

  const loadStats = async () => {
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/watchlist/stats?user_id=${userId}`, { headers });
      if (!response.ok) return;
      const data = await response.json();
      if (data.success) setStats(data.stats);
    } catch (error) {
      console.error('Error loading stats:', error);
    }
  };

  const removeAccount = async (authorId) => {
    setIsDeletingAccount(true);
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/watchlist/remove`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, author_id: authorId })
      });

      if (!response.ok) throw new Error(`Server error: ${response.status}`);
      const data = await response.json();

      if (data.success) {
        // ✅ Optimistic: remove from local state immediately
        setWatchlist(prev => prev.filter(a => a.author_id !== authorId));
        setStats(prev => prev ? { ...prev, total_accounts: (prev.total_accounts || 1) - 1 } : prev);
        showToast('Account removed from watchlist.', 'success');
      } else {
        throw new Error(data.error || 'Failed to remove account');
      }
    } catch (error) {
      console.error('Error removing account:', error);
      showToast(error.message || 'Failed to remove account. Please try again.');
      // Re-fetch to ensure UI is in sync after failure
      loadWatchlist();
    } finally {
      setIsDeletingAccount(false);
      setPendingDeleteAccount(null);
    }
  };

  const updateNotes = async (authorId, notes) => {
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/watchlist/update`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, author_id: authorId, notes })
      });
      if (!response.ok) throw new Error(`Server error: ${response.status}`);
      const data = await response.json();
      if (data.success) {
        setWatchlist(prev => prev.map(a => a.author_id === authorId ? { ...a, notes } : a));
        setEditingNotes(null);
        setNewNote('');
      } else {
        throw new Error(data.error || 'Failed to update notes');
      }
    } catch (error) {
      console.error('Error updating notes:', error);
      showToast('Failed to save notes. Please try again.');
    }
  };

  const updateTags = async (authorId, tags) => {
    try {
      const tagsArray = tags.split(',').map(t => t.trim()).filter(t => t);
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/watchlist/update`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, author_id: authorId, tags: tagsArray })
      });
      if (!response.ok) throw new Error(`Server error: ${response.status}`);
      const data = await response.json();
      if (data.success) {
        setWatchlist(prev => prev.map(a => a.author_id === authorId ? { ...a, tags: tagsArray } : a));
        setEditingTags(null);
        setNewTags('');
      } else {
        throw new Error(data.error || 'Failed to update tags');
      }
    } catch (error) {
      console.error('Error updating tags:', error);
      showToast('Failed to save tags. Please try again.');
    }
  };

  // ─── Wallet watchlist functions ───────────────────────────────────────────

  const loadWalletWatchlist = async () => {
    setIsLoading(true);
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/get?user_id=${userId}`, { headers });
      if (!response.ok) throw new Error(`Server error: ${response.status}`);
      const data = await response.json();
      if (data.success) setWalletWatchlist(data.wallets);
    } catch (error) {
      console.error('Error loading wallet watchlist:', error);
      showToast('Failed to load wallet watchlist. Please try again.');
    }
    setIsLoading(false);
  };

  const loadWalletStats = async () => {
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/stats?user_id=${userId}`, { headers });
      if (!response.ok) return;
      const data = await response.json();
      if (data.success) setWalletStats(data.stats);
    } catch (error) {
      console.error('Error loading wallet stats:', error);
    }
  };

  const removeWallet = async (walletAddress) => {
    setIsDeletingWallet(true);
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/remove`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, wallet_address: walletAddress })
      });

      if (!response.ok) throw new Error(`Server error: ${response.status}`);
      const data = await response.json();

      if (data.success) {
        // ✅ Optimistic: remove from local state immediately
        setWalletWatchlist(prev => prev.filter(w => w.wallet_address !== walletAddress));
        setWalletStats(prev => prev ? { ...prev, total_wallets: (prev.total_wallets || 1) - 1 } : prev);
        showToast('Wallet removed from watchlist.', 'success');
      } else {
        throw new Error(data.error || 'Failed to remove wallet');
      }
    } catch (error) {
      console.error('Error removing wallet:', error);
      showToast(error.message || 'Failed to remove wallet. Please try again.');
      // Re-fetch to ensure UI is in sync after failure
      loadWalletWatchlist();
    } finally {
      setIsDeletingWallet(false);
      setPendingDeleteWallet(null);
    }
  };

  const updateWalletNotes = async (walletAddress, notes) => {
    try {
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/update`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, wallet_address: walletAddress, notes })
      });
      if (!response.ok) throw new Error(`Server error: ${response.status}`);
      const data = await response.json();
      if (data.success) {
        setWalletWatchlist(prev => prev.map(w => w.wallet_address === walletAddress ? { ...w, notes } : w));
        setEditingNotes(null);
        setNewNote('');
      } else {
        throw new Error(data.error || 'Failed to update notes');
      }
    } catch (error) {
      console.error('Error updating wallet notes:', error);
      showToast('Failed to save notes. Please try again.');
    }
  };

  const updateWalletTags = async (walletAddress, tags) => {
    try {
      const tagsArray = tags.split(',').map(t => t.trim()).filter(t => t);
      const headers = await getHeaders();
      const response = await fetch(`${apiUrl}/api/wallets/watchlist/update`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, wallet_address: walletAddress, tags: tagsArray })
      });
      if (!response.ok) throw new Error(`Server error: ${response.status}`);
      const data = await response.json();
      if (data.success) {
        setWalletWatchlist(prev => prev.map(w => w.wallet_address === walletAddress ? { ...w, tags: tagsArray } : w));
        setEditingTags(null);
        setNewTags('');
      } else {
        throw new Error(data.error || 'Failed to update tags');
      }
    } catch (error) {
      console.error('Error updating wallet tags:', error);
      showToast('Failed to save tags. Please try again.');
    }
  };

  // ─── Render ───────────────────────────────────────────────────────────────

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
      {/* Toast */}
      {toast && <Toast message={toast.message} type={toast.type} onDismiss={dismissToast} />}

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

      {/* ── Twitter Accounts Tab ─────────────────────────────────────────── */}
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
                        {/* ✅ Delete button — opens inline confirmation instead of confirm() */}
                        <button
                          onClick={() => setPendingDeleteAccount(
                            pendingDeleteAccount === account.author_id ? null : account.author_id
                          )}
                          disabled={isDeletingAccount && pendingDeleteAccount === account.author_id}
                          className="p-2 hover:bg-red-500/20 rounded text-red-400 disabled:opacity-50 transition"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>

                    {/* Inline delete confirmation */}
                    {pendingDeleteAccount === account.author_id && (
                      <ConfirmDelete
                        onConfirm={() => removeAccount(account.author_id)}
                        onCancel={() => setPendingDeleteAccount(null)}
                        isDeleting={isDeletingAccount}
                      />
                    )}

                    {/* Tags */}
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
                          <button onClick={() => updateTags(account.author_id, newTags)} className="px-3 py-1 bg-purple-600 rounded text-sm">Save</button>
                          <button onClick={() => { setEditingTags(null); setNewTags(''); }} className="px-3 py-1 bg-white/10 rounded text-sm">Cancel</button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 flex-wrap">
                          <Tag size={14} className="text-gray-400" />
                          {account.tags && account.tags.length > 0 ? (
                            account.tags.map((tag, idx) => (
                              <span key={idx} className="px-2 py-0.5 bg-purple-600/20 border border-purple-500/30 rounded text-xs">{tag}</span>
                            ))
                          ) : (
                            <span className="text-xs text-gray-500">No tags</span>
                          )}
                          <button onClick={() => { setEditingTags(account.author_id); setNewTags(account.tags ? account.tags.join(', ') : ''); }} className="text-xs text-purple-400 hover:text-purple-300">Edit</button>
                        </div>
                      )}
                    </div>

                    {/* Notes */}
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
                            <button onClick={() => updateNotes(account.author_id, newNote)} className="px-3 py-1 bg-purple-600 rounded text-sm">Save</button>
                            <button onClick={() => { setEditingNotes(null); setNewNote(''); }} className="px-3 py-1 bg-white/10 rounded text-sm">Cancel</button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-2">
                          <StickyNote size={14} className="text-gray-400 mt-0.5" />
                          <div className="flex-1">
                            {account.notes ? <p className="text-sm text-gray-300">{account.notes}</p> : <span className="text-xs text-gray-500">No notes</span>}
                          </div>
                          <button onClick={() => { setEditingNotes(account.author_id); setNewNote(account.notes || ''); }} className="text-xs text-purple-400 hover:text-purple-300">
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
        </>
      )}

      {/* ── Wallet Watchlist Tab ──────────────────────────────────────────── */}
      {activeWatchlistTab === 'wallets' && (
        <>
          {walletStats && (
            <div className="grid grid-cols-4 gap-4">
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-purple-400">{walletStats.total_wallets || 0}</div>
                <div className="text-xs text-gray-400">Total Wallets</div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-yellow-400">{walletStats.s_tier || 0}</div>
                <div className="text-xs text-gray-400">S-Tier Wallets</div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-green-400">{walletStats.avg_pump_count?.toFixed(1) || 0}</div>
                <div className="text-xs text-gray-400">Avg Pumps</div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-2xl font-bold text-blue-400">{walletStats.total_pumps_tracked || 0}</div>
                <div className="text-xs text-gray-400">Total Pumps</div>
              </div>
            </div>
          )}

          {walletWatchlist.length === 0 ? (
            <div className="bg-white/5 border border-white/10 rounded-lg p-12 text-center">
              <Wallet className="mx-auto mb-4 text-gray-400" size={48} />
              <h3 className="text-lg font-semibold mb-2">No Wallets in Watchlist</h3>
              <p className="text-sm text-gray-400">Run wallet analysis and add high-performing wallets here</p>
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
                          {wallet.alert_enabled ? (
                            <span className="flex items-center gap-1 px-2 py-1 bg-green-500/20 text-green-400 rounded text-xs">
                              <Bell size={12} /> Alerts ON
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 px-2 py-1 bg-gray-500/20 text-gray-400 rounded text-xs">
                              <BellOff size={12} /> Alerts OFF
                            </span>
                          )}
                        </div>
                        <div className="text-xs font-mono text-gray-400 mb-2">{wallet.wallet_address}</div>
                        {wallet.tokens_hit && wallet.tokens_hit.length > 0 && (
                          <div className="text-xs text-gray-500">
                            <strong>Tokens:</strong> {wallet.tokens_hit.join(', ')}
                          </div>
                        )}
                      </div>

                      {/* Action Buttons */}
                      <div className="flex gap-2">
                        <button
                          onClick={() => setAlertSettingsWallet(wallet.wallet_address)}
                          className="p-2 hover:bg-purple-500/20 rounded text-purple-400"
                          title="Configure alerts"
                        >
                          <Settings size={16} />
                        </button>
                        {/* ✅ Delete button — opens inline confirmation */}
                        <button
                          onClick={() => setPendingDeleteWallet(
                            pendingDeleteWallet === wallet.wallet_address ? null : wallet.wallet_address
                          )}
                          disabled={isDeletingWallet && pendingDeleteWallet === wallet.wallet_address}
                          className="p-2 hover:bg-red-500/20 rounded text-red-400 disabled:opacity-50 transition"
                          title="Remove wallet"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>

                    {/* Inline delete confirmation */}
                    {pendingDeleteWallet === wallet.wallet_address && (
                      <ConfirmDelete
                        onConfirm={() => removeWallet(wallet.wallet_address)}
                        onCancel={() => setPendingDeleteWallet(null)}
                        isDeleting={isDeletingWallet}
                      />
                    )}

                    {/* Performance Stats */}
                    <div className="grid grid-cols-4 gap-3 mb-3 text-sm">
                      <div className="bg-white/5 rounded p-2 text-center">
                        <div className="font-bold text-green-400">{wallet.pump_count || 0}</div>
                        <div className="text-xs text-gray-400">Pumps</div>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <div className="font-bold text-yellow-400">{wallet.avg_distance_to_peak?.toFixed(1) || 0}%</div>
                        <div className="text-xs text-gray-400">Distance</div>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <div className="font-bold text-blue-400">{wallet.avg_roi_to_peak?.toFixed(1) || 0}%</div>
                        <div className="text-xs text-gray-400">Avg ROI</div>
                      </div>
                      <div className="bg-white/5 rounded p-2 text-center">
                        <div className="font-bold text-purple-400">{wallet.consistency_score?.toFixed(1) || 0}</div>
                        <div className="text-xs text-gray-400">Consistency</div>
                      </div>
                    </div>

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

                    {/* Tags */}
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
                          <button onClick={() => updateWalletTags(wallet.wallet_address, newTags)} className="px-3 py-1 bg-purple-600 rounded text-sm">Save</button>
                          <button onClick={() => { setEditingTags(null); setNewTags(''); }} className="px-3 py-1 bg-white/10 rounded text-sm">Cancel</button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 flex-wrap">
                          <Tag size={14} className="text-gray-400" />
                          {wallet.tags && wallet.tags.length > 0 ? (
                            wallet.tags.map((tag, idx) => (
                              <span key={idx} className="px-2 py-0.5 bg-purple-600/20 border border-purple-500/30 rounded text-xs">{tag}</span>
                            ))
                          ) : (
                            <span className="text-xs text-gray-500">No tags</span>
                          )}
                          <button onClick={() => { setEditingTags(wallet.wallet_address); setNewTags(wallet.tags ? wallet.tags.join(', ') : ''); }} className="text-xs text-purple-400 hover:text-purple-300">Edit</button>
                        </div>
                      )}
                    </div>

                    {/* Notes */}
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
                            <button onClick={() => updateWalletNotes(wallet.wallet_address, newNote)} className="px-3 py-1 bg-purple-600 rounded text-sm">Save</button>
                            <button onClick={() => { setEditingNotes(null); setNewNote(''); }} className="px-3 py-1 bg-white/10 rounded text-sm">Cancel</button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-2">
                          <StickyNote size={14} className="text-gray-400 mt-0.5" />
                          <div className="flex-1">
                            {wallet.notes ? <p className="text-sm text-gray-300">{wallet.notes}</p> : <span className="text-xs text-gray-500">No notes</span>}
                          </div>
                          <button onClick={() => { setEditingNotes(wallet.wallet_address); setNewNote(wallet.notes || ''); }} className="text-xs text-purple-400 hover:text-purple-300">
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

      {/* Alert Settings Modal */}
      {alertSettingsWallet && (
        <WalletAlertSettings
          walletAddress={alertSettingsWallet}
          onClose={() => setAlertSettingsWallet(null)}
          onSave={() => loadWalletWatchlist()}
        />
      )}
    </div>
  );
}