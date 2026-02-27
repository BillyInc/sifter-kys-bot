import React, { useState, useEffect, useRef } from 'react';
import {
  RefreshCw, TrendingUp, Activity, Bell, Zap, BookOpen, Plus, Pencil,
  X, Save, Tag, Clock, Lightbulb, ListTodo, StickyNote, Search, Trash2,
  Lock, WifiOff,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import WatchlistExpandedCard from '../WatchlistExpandedCard';
import DiaryUnlock from './DiaryUnlock';
import { useGlobalDiary } from './useDiary';

// ─── Note type config ──────────────────────────────────────────────────────────
const NOTE_TYPES = [
  { value: 'thought',  label: 'Thought',  icon: Lightbulb,  color: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/20' },
  { value: 'strategy', label: 'Strategy', icon: TrendingUp, color: 'text-blue-400',   bg: 'bg-blue-500/10',   border: 'border-blue-500/20'   },
  { value: 'todo',     label: 'To-Do',    icon: ListTodo,   color: 'text-green-400',  bg: 'bg-green-500/10',  border: 'border-green-500/20'  },
  { value: 'note',     label: 'Note',     icon: StickyNote, color: 'text-purple-400', bg: 'bg-purple-500/10', border: 'border-purple-500/20' },
];

function getNoteTypeMeta(v) { return NOTE_TYPES.find(t => t.value === v) || NOTE_TYPES[3]; }

function formatNoteTs(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) + ' · ' +
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function timeAgo(ts) {
  const diff = Date.now() - new Date(ts).getTime();
  if (isNaN(diff) || diff < 0) return 'just now';
  const m = Math.floor(diff / 60_000);
  const h = Math.floor(diff / 3_600_000);
  const d = Math.floor(diff / 86_400_000);
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  if (h < 24) return `${h}h ago`;
  return `${d}d ago`;
}

// ─── Composer ─────────────────────────────────────────────────────────────────
function NoteComposer({ onSave, onCancel, editingEntry = null, saving = false }) {
  const [text, setText]           = useState(editingEntry?.text || '');
  const [type, setType]           = useState(editingEntry?.type || 'thought');
  const [tagInput, setTagInput]   = useState(editingEntry?.tags?.join(', ') || '');
  const [walletRef, setWalletRef] = useState(editingEntry?.walletRef || '');
  const textRef = useRef(null);
  useEffect(() => { textRef.current?.focus(); }, []);

  const handleSave = () => {
    if (!text.trim()) return;
    onSave({ text: text.trim(), type, tags: tagInput.split(',').map(t => t.trim()).filter(Boolean), walletRef: walletRef.trim() || null });
  };

  return (
    <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
      className="bg-black/40 border border-white/15 rounded-xl p-4 space-y-3">
      <div className="flex gap-1.5 flex-wrap">
        {NOTE_TYPES.map(t => {
          const TIcon = t.icon;
          return (
            <button key={t.value} onClick={() => setType(t.value)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold border transition ${type === t.value ? `${t.bg} ${t.border} ${t.color}` : 'bg-white/5 border-white/10 text-gray-500 hover:text-gray-300'}`}>
              <TIcon size={11} />{t.label}
            </button>
          );
        })}
      </div>
      <textarea ref={textRef} value={text} onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSave(); if (e.key === 'Escape') onCancel(); }}
        placeholder="Write your note, strategy, or to-do here…" rows={4}
        className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50 resize-none" />
      <div className="grid grid-cols-2 gap-2">
        <div className="flex items-center gap-2 bg-black/40 border border-white/10 rounded-lg px-2.5 py-1.5">
          <Tag size={11} className="text-gray-600 shrink-0" />
          <input type="text" value={tagInput} onChange={e => setTagInput(e.target.value)} placeholder="Tags (comma separated)"
            className="flex-1 bg-transparent text-xs text-gray-300 placeholder-gray-600 focus:outline-none" />
        </div>
        <div className="flex items-center gap-2 bg-black/40 border border-white/10 rounded-lg px-2.5 py-1.5">
          <span className="text-gray-600 text-[10px] shrink-0 font-mono">WALLET</span>
          <input type="text" value={walletRef} onChange={e => setWalletRef(e.target.value)} placeholder="Link to wallet (optional)"
            className="flex-1 bg-transparent text-xs text-gray-300 placeholder-gray-600 focus:outline-none font-mono" />
        </div>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-gray-700">⌘↵ to save · Esc to cancel</span>
        <div className="flex gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs text-gray-400 transition">Cancel</button>
          <button onClick={handleSave} disabled={!text.trim() || saving}
            className="flex items-center gap-1.5 px-4 py-1.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 rounded-lg text-xs font-semibold text-white transition">
            <Save size={11} /> {saving ? 'Saving…' : editingEntry ? 'Update' : 'Save note'}
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Global diary entry ────────────────────────────────────────────────────────
function GlobalDiaryEntry({ entry, onEdit, onDelete }) {
  const meta = getNoteTypeMeta(entry.type);
  const Icon = meta.icon;
  const [conf, setConf] = useState(false);

  return (
    <motion.div layout initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }}
      className={`group relative rounded-xl border p-4 ${meta.bg} ${meta.border}`}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 p-1.5 rounded-lg bg-black/30"><Icon size={13} className={meta.color} /></div>
        <div className="flex-1 min-w-0">
          {entry.walletRef && (
            <div className="mb-1.5">
              <span className="text-[10px] font-mono bg-white/10 text-gray-400 px-2 py-0.5 rounded">
                {entry.walletRef.length > 12 ? `${entry.walletRef.slice(0, 8)}…${entry.walletRef.slice(-4)}` : entry.walletRef}
              </span>
            </div>
          )}
          <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap break-words">{entry.text}</p>
          {entry.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {entry.tags.map((t, i) => <span key={i} className="text-[10px] px-1.5 py-0.5 bg-white/10 text-gray-400 rounded">{t}</span>)}
            </div>
          )}
          <div className="flex items-center gap-2 mt-2">
            <span className={`text-[10px] font-semibold ${meta.color}`}>{meta.label}</span>
            <span className="text-gray-700">·</span>
            <Clock size={9} className="text-gray-700" />
            <span className="text-[10px] text-gray-600">{formatNoteTs(entry.createdAt)}</span>
            {entry.editedAt && <span className="text-[10px] text-gray-700">(edited {timeAgo(entry.editedAt)})</span>}
          </div>
        </div>
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition shrink-0">
          <button onClick={() => onEdit(entry)} className="p-1.5 hover:bg-white/10 rounded-lg text-gray-600 hover:text-gray-300 transition"><Pencil size={12} /></button>
          {conf
            ? <button onClick={() => onDelete(entry.id)} className="p-1.5 bg-red-500/20 rounded-lg text-red-400 text-[10px] font-bold">rm</button>
            : <button onClick={() => { setConf(true); setTimeout(() => setConf(false), 2500); }} className="p-1.5 hover:bg-white/10 rounded-lg text-gray-600 hover:text-red-400 transition"><Trash2 size={12} /></button>
          }
        </div>
      </div>
    </motion.div>
  );
}

// ─── Global diary panel ────────────────────────────────────────────────────────
function GlobalDiary({ userId, apiUrl }) {
  const diary = useGlobalDiary({ userId, apiUrl });
  const [composing, setComposing] = useState(false);
  const [editing, setEditing]     = useState(null);
  const [saving, setSaving]       = useState(false);
  const [filter, setFilter]       = useState('all');
  const [search, setSearch]       = useState('');

  const handleSave = async (data) => {
    setSaving(true);
    if (editing) { await diary.updateNote(editing.id, data); setEditing(null); }
    else         { await diary.addNote(data); }
    setSaving(false);
    setComposing(false);
  };

  // ── Show unlock screen if locked ─────────────────────────────────────────
  if (diary.locked) {
    return (
      <DiaryUnlock
        userId={userId}
        apiUrl={apiUrl}
        isNew={diary.isNew}
        saltB64={diary.saltB64}
        verificationToken={diary.verificationToken}
        onUnlocked={diary.onUnlocked}
      />
    );
  }

  let visible = filter === 'all' ? diary.notes : diary.notes.filter(n => n.type === filter);
  if (search.trim()) {
    const q = search.toLowerCase();
    visible = visible.filter(n =>
      n.text?.toLowerCase().includes(q) ||
      n.tags?.some(t => t.toLowerCase().includes(q)) ||
      n.walletRef?.toLowerCase().includes(q)
    );
  }

  const typeCounts = NOTE_TYPES.reduce((acc, t) => {
    acc[t.value] = diary.notes.filter(n => n.type === t.value).length;
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-bold text-base flex items-center gap-2">
            <BookOpen size={18} className="text-purple-400" /> Watchlist Diary
          </h3>
          <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-1.5">
            <Lock size={10} className="text-gray-600" />
            End-to-end encrypted · passphrase-protected
            {diary.offline && <span className="flex items-center gap-1 text-yellow-600 ml-1"><WifiOff size={9} /> offline</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={diary.lock} className="text-xs text-gray-600 hover:text-gray-400 transition flex items-center gap-1">
            <Lock size={11} /> Lock
          </button>
          {!composing && (
            <button onClick={() => setComposing(true)}
              className="flex items-center gap-2 px-4 py-2 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 rounded-xl text-sm font-semibold text-purple-400 transition">
              <Plus size={14} /> New Note
            </button>
          )}
        </div>
      </div>

      {/* Stats tiles */}
      <div className="grid grid-cols-4 gap-2">
        {NOTE_TYPES.map(t => {
          const TIcon = t.icon;
          return (
            <button key={t.value} onClick={() => setFilter(f => f === t.value ? 'all' : t.value)}
              className={`flex items-center gap-2 px-3 py-2.5 rounded-xl border text-left transition ${filter === t.value ? `${t.bg} ${t.border}` : 'bg-white/5 border-white/10 hover:bg-white/8'}`}>
              <TIcon size={13} className={t.color} />
              <div>
                <div className={`text-sm font-bold ${filter === t.value ? t.color : 'text-white'}`}>{typeCounts[t.value] || 0}</div>
                <div className="text-[10px] text-gray-500">{t.label}s</div>
              </div>
            </button>
          );
        })}
      </div>

      <AnimatePresence>
        {composing && (
          <NoteComposer onSave={handleSave} onCancel={() => { setComposing(false); setEditing(null); }} editingEntry={editing} saving={saving} />
        )}
      </AnimatePresence>

      {diary.error && <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{diary.error}</p>}

      {diary.notes.length > 3 && (
        <div className="flex items-center gap-2 bg-white/5 border border-white/10 rounded-lg px-3 py-2">
          <Search size={13} className="text-gray-600 shrink-0" />
          <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search notes, tags, wallets…"
            className="flex-1 bg-transparent text-sm text-gray-300 placeholder-gray-600 focus:outline-none" />
          {search && <button onClick={() => setSearch('')} className="text-gray-600 hover:text-gray-400"><X size={12} /></button>}
        </div>
      )}

      {diary.loading && [...Array(3)].map((_, i) => <div key={i} className="animate-pulse bg-white/5 rounded-xl h-20 border border-white/10" />)}

      {!diary.loading && visible.length === 0 && (
        <div className="text-center py-14 text-gray-700">
          <BookOpen size={36} className="mx-auto mb-3 opacity-20" />
          <p className="text-sm text-gray-500">
            {diary.notes.length === 0 ? 'Your diary is empty. Add a note, strategy, or to-do.' : 'No notes match your filter or search.'}
          </p>
        </div>
      )}

      {!diary.loading && (
        <div className="space-y-3">
          <AnimatePresence mode="popLayout">
            {visible.map(entry => (
              <GlobalDiaryEntry key={entry.id} entry={entry}
                onEdit={e => { setEditing(e); setComposing(true); }}
                onDelete={diary.deleteNote} />
            ))}
          </AnimatePresence>
        </div>
      )}

      {diary.notes.length > 0 && !diary.loading && (
        <p className="text-[10px] text-gray-700 text-center">
          {diary.notes.length} entr{diary.notes.length === 1 ? 'y' : 'ies'} · decrypted in your browser · never sent in plaintext
        </p>
      )}
    </div>
  );
}

// ─── Main export ──────────────────────────────────────────────────────────────
export default function WatchlistPanel({ userId, apiUrl }) {
  const [wallets, setWallets]           = useState([]);
  const [lastUpdate, setLastUpdate]     = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeTab, setActiveTab]       = useState('wallets');

  useEffect(() => { loadWatchlist(); }, [userId]); // eslint-disable-line

  const loadWatchlist = async () => {
    setIsRefreshing(true);
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/watchlist/table?user_id=${userId}`);
      const data = await res.json();
      if (data.success) { setWallets(data.wallets || []); setLastUpdate(new Date()); }
    } catch (err) { console.error('Error loading watchlist:', err); }
    setIsRefreshing(false);
  };

  const handleRefreshWallet = async (addr) => {
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/watchlist/${addr}/refresh`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId }),
      });
      const data = await res.json();
      if (data.success) await loadWatchlist();
    } catch (err) { console.error('Error refreshing wallet:', err); }
  };

  const handleDeleteWallet = async (addr) => {
    try {
      const res  = await fetch(`${apiUrl}/api/wallets/watchlist/remove`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, wallet_address: addr }),
      });
      const data = await res.json();
      if (data.success) setWallets(prev => prev.filter(w => w.wallet_address !== addr));
    } catch (err) { console.error('Error deleting wallet:', err); }
  };

  const healthyCount  = wallets.filter(w => !w.degradation_alerts?.length).length;
  const warningCount  = wallets.filter(w => w.degradation_alerts?.some(a => a.severity === 'yellow')).length;
  const criticalCount = wallets.filter(w => w.degradation_alerts?.some(a => a.severity === 'red')).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-bold text-lg">🏆 Your Watchlist</h3>
          <p className="text-xs text-gray-400">Last updated: {lastUpdate ? new Date(lastUpdate).toLocaleTimeString() : 'Never'}</p>
        </div>
        <button onClick={loadWatchlist} disabled={isRefreshing} className="p-2 hover:bg-white/10 rounded-lg transition disabled:opacity-50">
          <RefreshCw size={16} className={isRefreshing ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Tab switcher */}
      <div className="flex border-b border-white/10">
        <button onClick={() => setActiveTab('wallets')}
          className={`flex items-center gap-2 px-4 py-2.5 border-b-2 text-sm font-semibold transition ${activeTab === 'wallets' ? 'border-purple-500 text-white' : 'border-transparent text-gray-500 hover:text-gray-300'}`}>
          🏆 Wallets
          {wallets.length > 0 && <span className="text-xs bg-white/10 px-1.5 py-0.5 rounded-full">{wallets.length}</span>}
        </button>
        <button onClick={() => setActiveTab('diary')}
          className={`flex items-center gap-2 px-4 py-2.5 border-b-2 text-sm font-semibold transition ${activeTab === 'diary' ? 'border-purple-500 text-white' : 'border-transparent text-gray-500 hover:text-gray-300'}`}>
          <BookOpen size={14} /> Diary <Lock size={10} className="text-gray-600" />
        </button>
      </div>

      {/* Wallets tab */}
      {activeTab === 'wallets' && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <motion.div whileHover={{ scale: 1.02 }} className="bg-gradient-to-br from-green-900/30 to-green-800/20 border border-green-500/30 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2"><Activity className="text-green-400" size={18} /><span className="text-2xl font-bold text-green-400">{healthyCount}</span></div>
              <div className="text-xs text-gray-400">Healthy</div>
            </motion.div>
            <motion.div whileHover={{ scale: 1.02 }} className="bg-gradient-to-br from-yellow-900/30 to-yellow-800/20 border border-yellow-500/30 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2"><Bell className="text-yellow-400" size={18} /><span className="text-2xl font-bold text-yellow-400">{warningCount}</span></div>
              <div className="text-xs text-gray-400">Monitoring</div>
            </motion.div>
            <motion.div whileHover={{ scale: 1.02 }} className="bg-gradient-to-br from-red-900/30 to-red-800/20 border border-red-500/30 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2"><Zap className="text-red-400" size={18} /><span className="text-2xl font-bold text-red-400">{criticalCount}</span></div>
              <div className="text-xs text-gray-400">Action Needed</div>
            </motion.div>
          </div>

          <div style={{ background: '#070d14', border: '1px solid #1a2640', borderRadius: 8, overflow: 'hidden' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '36px 140px 44px 52px 76px 68px 60px 60px 1fr', gap: 8, padding: '9px 16px', background: '#0a1220', borderBottom: '1px solid #1a2640', fontFamily: 'monospace', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#3a5a8a' }}>
              <div style={{ textAlign: 'center' }}>#</div>
              <div>ADDRESS</div>
              <div style={{ textAlign: 'center' }}>TIER</div>
              <div style={{ textAlign: 'right' }}>SCORE</div>
              <div style={{ textAlign: 'right' }}>ATH DIST</div>
              <div style={{ textAlign: 'right' }}>ROI 30D</div>
              <div style={{ textAlign: 'right' }}>RUNNERS</div>
              <div style={{ textAlign: 'center' }}>FORM</div>
              <div style={{ textAlign: 'right' }}>ACTIONS</div>
            </div>
            {wallets.length === 0 ? (
              <div style={{ padding: '48px 24px', textAlign: 'center' }}>
                <TrendingUp size={36} style={{ color: '#1a2640', margin: '0 auto 12px', display: 'block' }} />
                <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#334155' }}>No wallets in watchlist</div>
              </div>
            ) : wallets.map((wallet, idx) => (
              <WatchlistExpandedCard
                key={wallet.wallet_address}
                wallet={wallet}
                rank={idx + 1}
                onRefresh={handleRefreshWallet}
                onDelete={handleDeleteWallet}
                userId={userId}
                apiUrl={apiUrl}
              />
            ))}
          </div>
        </>
      )}

      {/* Diary tab */}
      {activeTab === 'diary' && <GlobalDiary userId={userId} apiUrl={apiUrl} />}
    </div>
  );
}