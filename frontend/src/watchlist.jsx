import React, { useState, useEffect } from 'react';
import { BookmarkPlus, Trash2, Tag, StickyNote, TrendingUp, Users, Search } from 'lucide-react';

export default function Watchlist({ userId, apiUrl }) {
  const [watchlist, setWatchlist] = useState([]);
  const [groups, setGroups] = useState([]);
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [editingNotes, setEditingNotes] = useState(null);
  const [editingTags, setEditingTags] = useState(null);
  const [newNote, setNewNote] = useState('');
  const [newTags, setNewTags] = useState('');
  const [stats, setStats] = useState(null);

  useEffect(() => {
    loadWatchlist();
    loadGroups();
    loadStats();
  }, [userId]);

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
        body: JSON.stringify({
          user_id: userId,
          author_id: authorId,
          notes: notes
        })
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
        body: JSON.stringify({
          user_id: userId,
          author_id: authorId,
          tags: tagsArray
        })
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
      {/* Stats */}
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

      {/* Watchlist */}
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
                      onClick={() => removeAccount(account.author_id)}
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
                      <button
                        onClick={() => updateTags(account.author_id, newTags)}
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
                        <button
                          onClick={() => updateNotes(account.author_id, newNote)}
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
  );
}