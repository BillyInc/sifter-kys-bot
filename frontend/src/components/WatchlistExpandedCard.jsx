import React, { useState, useRef, useEffect } from 'react';
import {
  RefreshCw, ChevronDown, ChevronUp, BookOpen, Plus, Pencil,
  X, Save, Tag, Clock, Lightbulb, ListTodo, StickyNote, TrendingUp,
  WifiOff, Lock,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useDiary } from './useDiary';
import DiaryUnlock from './DiaryUnlock';

// ─── Note type config ─────────────────────────────────────────────────────────
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
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' · ' +
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ─── Single entry ─────────────────────────────────────────────────────────────
function DiaryEntry({ entry, onEdit, onDelete }) {
  const meta = getNoteTypeMeta(entry.type);
  const Icon = meta.icon;
  const [conf, setConf] = useState(false);
  return (
    <motion.div layout initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }}
      className={`group relative rounded-lg border p-3 ${meta.bg} ${meta.border}`}>
      <div className="flex items-start gap-2">
        <Icon size={13} className={`${meta.color} mt-0.5 shrink-0`} />
        <div className="flex-1 min-w-0">
          <p className="text-xs text-gray-200 leading-relaxed whitespace-pre-wrap break-words">{entry.text}</p>
          {entry.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {entry.tags.map((t, i) => <span key={i} className="text-[10px] px-1.5 py-0.5 bg-white/10 text-gray-400 rounded">{t}</span>)}
            </div>
          )}
          <div className="flex items-center gap-1 mt-1.5">
            <Clock size={9} className="text-gray-700" />
            <span className="text-[10px] text-gray-600">{formatNoteTs(entry.createdAt)}</span>
            {entry.editedAt && <span className="text-[10px] text-gray-700 ml-1">(edited)</span>}
          </div>
        </div>
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition shrink-0">
          <button onClick={() => onEdit(entry)} className="p-1 hover:bg-white/10 rounded text-gray-600 hover:text-gray-300 transition"><Pencil size={11} /></button>
          {conf
            ? <button onClick={() => onDelete(entry.id)} className="p-1 bg-red-500/20 rounded text-red-400 text-[10px] font-bold">rm</button>
            : <button onClick={() => { setConf(true); setTimeout(() => setConf(false), 2500); }} className="p-1 hover:bg-white/10 rounded text-gray-600 hover:text-red-400 transition"><X size={11} /></button>
          }
        </div>
      </div>
    </motion.div>
  );
}

// ─── Composer ─────────────────────────────────────────────────────────────────
function NoteComposer({ onSave, onCancel, editingEntry = null, saving = false }) {
  const [text, setText]         = useState(editingEntry?.text || '');
  const [type, setType]         = useState(editingEntry?.type || 'thought');
  const [tagInput, setTagInput] = useState(editingEntry?.tags?.join(', ') || '');
  const textRef = useRef(null);
  useEffect(() => { textRef.current?.focus(); }, []);

  const handleSave = () => {
    if (!text.trim()) return;
    onSave({ text: text.trim(), type, tags: tagInput.split(',').map(t => t.trim()).filter(Boolean) });
  };

  return (
    <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
      className="bg-black/40 border border-white/15 rounded-xl p-3 space-y-3">
      <div className="flex gap-1.5 flex-wrap">
        {NOTE_TYPES.map(t => {
          const TIcon = t.icon;
          return (
            <button key={t.value} onClick={() => setType(t.value)}
              className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-semibold border transition ${type === t.value ? `${t.bg} ${t.border} ${t.color}` : 'bg-white/5 border-white/10 text-gray-500 hover:text-gray-300'}`}>
              <TIcon size={10} />{t.label}
            </button>
          );
        })}
      </div>
      <textarea ref={textRef} value={text} onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSave(); if (e.key === 'Escape') onCancel(); }}
        placeholder="Write your note, strategy, or to-do…" rows={3}
        className="w-full bg-black/50 border border-white/10 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50 resize-none" />
      <div className="flex items-center gap-2 bg-black/40 border border-white/10 rounded-lg px-2.5 py-1.5">
        <Tag size={11} className="text-gray-600 shrink-0" />
        <input type="text" value={tagInput} onChange={e => setTagInput(e.target.value)} placeholder="Tags (comma separated)"
          className="flex-1 bg-transparent text-xs text-gray-300 placeholder-gray-600 focus:outline-none" />
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-gray-700">⌘↵ save · Esc cancel</span>
        <div className="flex gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs text-gray-400 transition">Cancel</button>
          <button onClick={handleSave} disabled={!text.trim() || saving}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 rounded-lg text-xs font-semibold text-white transition">
            <Save size={11} /> {saving ? 'Saving…' : editingEntry ? 'Update' : 'Save'}
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Wallet diary (shown inside expanded row) ──────────────────────────────────
function WalletDiary({ userId, apiUrl, walletAddress }) {
  const diary = useDiary({ userId, apiUrl, walletAddress });
  const [composing, setComposing]       = useState(false);
  const [editingEntry, setEditingEntry] = useState(null);
  const [saving, setSaving]             = useState(false);
  const [filter, setFilter]             = useState('all');

  const handleSave = async (data) => {
    setSaving(true);
    if (editingEntry) {
      await diary.updateNote(editingEntry.id, data);
      setEditingEntry(null);
    } else {
      await diary.addNote({ ...data, walletRef: walletAddress });
    }
    setSaving(false);
    setComposing(false);
  };

  // Show unlock screen if locked
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

  const filtered = filter === 'all' ? diary.notes : diary.notes.filter(n => n.type === filter);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen size={13} className="text-purple-400" />
          <span className="text-xs font-semibold text-gray-300 uppercase tracking-wide">Wallet Diary</span>
          {diary.notes.length > 0 && (
            <span className="text-[10px] bg-purple-500/20 text-purple-400 px-1.5 py-0.5 rounded-full">{diary.notes.length}</span>
          )}
          <span className="flex items-center gap-1 text-[10px] text-gray-600" title="End-to-end encrypted">
            <Lock size={9} /> E2E
          </span>
          {diary.offline && <span className="flex items-center gap-1 text-[10px] text-yellow-600"><WifiOff size={9} /> local</span>}
          <button onClick={diary.lock} className="text-[10px] text-gray-700 hover:text-gray-500 transition ml-1">lock</button>
        </div>
        {!composing && (
          <button onClick={() => setComposing(true)}
            className="flex items-center gap-1 px-2.5 py-1.5 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 rounded-lg text-xs font-semibold text-purple-400 transition">
            <Plus size={11} /> Add Note
          </button>
        )}
      </div>

      <AnimatePresence>
        {composing && <NoteComposer onSave={handleSave} onCancel={() => { setComposing(false); setEditingEntry(null); }} editingEntry={editingEntry} saving={saving} />}
      </AnimatePresence>

      {diary.error && <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{diary.error}</p>}

      {diary.notes.length > 1 && (
        <div className="flex gap-1 flex-wrap">
          <button onClick={() => setFilter('all')} className={`px-2 py-0.5 rounded text-[10px] font-semibold transition ${filter === 'all' ? 'bg-white/15 text-white' : 'text-gray-600 hover:text-gray-400'}`}>All ({diary.notes.length})</button>
          {NOTE_TYPES.map(t => {
            const count = diary.notes.filter(n => n.type === t.value).length;
            if (!count) return null;
            return (
              <button key={t.value} onClick={() => setFilter(t.value)}
                className={`px-2 py-0.5 rounded text-[10px] font-semibold transition ${filter === t.value ? `${t.bg} ${t.color}` : 'text-gray-600 hover:text-gray-400'}`}>
                {t.label} ({count})
              </button>
            );
          })}
        </div>
      )}

      {diary.loading && [...Array(2)].map((_, i) => <div key={i} className="animate-pulse bg-white/5 rounded-lg h-14 border border-white/10" />)}

      {!diary.loading && filtered.length === 0 && !composing && (
        <div className="text-center py-6 text-gray-700">
          <BookOpen size={24} className="mx-auto mb-2 opacity-30" />
          <p className="text-xs">{diary.notes.length === 0 ? 'No notes yet.' : 'No entries match this filter.'}</p>
        </div>
      )}

      <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
        <AnimatePresence mode="popLayout">
          {!diary.loading && filtered.map(entry => (
            <DiaryEntry key={entry.id} entry={entry}
              onEdit={e => { setEditingEntry(e); setComposing(true); }}
              onDelete={diary.deleteNote} />
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

// ─── Main export ──────────────────────────────────────────────────────────────
export default function WatchlistExpandedCard({ wallet, rank, onRefresh, onDelete, userId, apiUrl }) {
  const [isExpanded, setIsExpanded]       = useState(false);
  const [isRefreshing, setIsRefreshing]   = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [isDeleting, setIsDeleting]       = useState(false);
  const [activeTab, setActiveTab]         = useState('performance');
  const [noteCount, setNoteCount]         = useState(0);

  useEffect(() => {
    if (!userId || !apiUrl) return;
    fetch(`${apiUrl}/api/diary/notes?user_id=${userId}&wallet_address=${wallet.wallet_address}`)
      .then(r => r.json())
      .then(d => { if (d.success) setNoteCount(d.count || 0); })
      .catch(() => {});
  }, [userId, apiUrl, wallet.wallet_address]);

  const handleRefresh = async (e) => {
    e.stopPropagation();
    setIsRefreshing(true);
    await onRefresh(wallet.wallet_address);
    setIsRefreshing(false);
  };

  const handleDelete = async (e) => {
    e.stopPropagation();
    if (!confirmDelete) { setConfirmDelete(true); setTimeout(() => setConfirmDelete(false), 3000); return; }
    setIsDeleting(true);
    await onDelete(wallet.wallet_address);
    setIsDeleting(false);
  };

  const distanceToATH = wallet.avg_distance_to_ath_multiplier ?? wallet.distance_to_ath_pct ?? 0;
  const entryQuality  = wallet.avg_entry_quality_multiplier ?? wallet.entry_to_ath_multiplier ?? 0;
  const consistency   = wallet.consistency_score ?? 0;
  const winRate7d     = wallet.win_rate_7d ?? 0;
  const winRate30d    = wallet.win_rate_30d ?? 0;
  const roi30dMult    = wallet.roi_30d_multiplier ?? (wallet.roi_percent != null ? 1 + wallet.roi_percent / 100 : 1);
  const score         = wallet.professional_score ?? wallet.avg_professional_score ?? 0;
  const runners30d    = wallet.runners_30d ?? wallet.runner_hits_30d ?? 0;
  const topRunners    = (wallet.tokens_hit || wallet.runners_hit || []).slice(0, 4);
  const form          = wallet.form || Array(5).fill({ result: 'neutral' });
  const alerts        = wallet.degradation_alerts || [];
  const roiDisplay    = roi30dMult >= 1 ? `+${((roi30dMult - 1) * 100).toFixed(0)}%` : `${((roi30dMult - 1) * 100).toFixed(0)}%`;
  const rankDisplay   = rank <= 3 ? ['🥇', '🥈', '🥉'][rank - 1] : `#${rank}`;

  const tierColors = {
    S: { text: '#f5c842', bg: 'rgba(245,200,66,0.12)', border: 'rgba(245,200,66,0.25)' },
    A: { text: '#22c55e', bg: 'rgba(34,197,94,0.12)',  border: 'rgba(34,197,94,0.25)'  },
    B: { text: '#60a5fa', bg: 'rgba(59,130,246,0.12)', border: 'rgba(59,130,246,0.25)' },
    C: { text: '#6b7280', bg: 'rgba(107,114,128,0.1)', border: 'rgba(107,114,128,0.2)' },
  };
  const tc          = tierColors[wallet.tier] || tierColors.C;
  const topAlert    = alerts[0]?.severity;
  const alertAccent = topAlert === 'red' ? '#ef4444' : topAlert === 'orange' ? '#f97316' : topAlert === 'yellow' ? '#eab308' : null;

  const StatBar = ({ label, val, pct, color = '#3b82f6' }) => (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 10, color: '#3a5a8a', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</span>
        <span style={{ fontSize: 11, color, fontFamily: 'monospace', fontWeight: 700 }}>{val}</span>
      </div>
      <div style={{ height: 2, background: '#1a2640', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, pct))}%`, background: `linear-gradient(90deg, ${color}88, ${color})`, borderRadius: 2, transition: 'width 0.5s ease' }} />
      </div>
    </div>
  );

  return (
    <div style={{ borderBottom: '1px solid rgba(26,38,64,0.6)', borderLeft: alertAccent ? `2px solid ${alertAccent}` : '2px solid transparent' }}>

      {/* Collapsed row */}
      <div onClick={() => setIsExpanded(!isExpanded)}
        style={{ display: 'grid', gridTemplateColumns: '36px 140px 44px 52px 76px 68px 60px 60px 1fr', gap: 8, alignItems: 'center', padding: '11px 16px', cursor: 'pointer', background: isExpanded ? 'rgba(59,130,246,0.04)' : 'transparent' }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(59,130,246,0.04)'}
        onMouseLeave={e => e.currentTarget.style.background = isExpanded ? 'rgba(59,130,246,0.04)' : 'transparent'}>
        <div style={{ fontFamily: 'monospace', fontSize: rank <= 3 ? 15 : 12, color: '#3a5a8a', textAlign: 'center' }}>{rankDisplay}</div>
        <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {wallet.wallet_address?.slice(0, 8)}...{wallet.wallet_address?.slice(-4)}
        </div>
        <div style={{ textAlign: 'center' }}>
          <span style={{ display: 'inline-block', padding: '1px 7px', borderRadius: 3, fontSize: 11, fontWeight: 700, fontFamily: 'monospace', color: tc.text, background: tc.bg, border: `1px solid ${tc.border}` }}>{wallet.tier || 'C'}</span>
        </div>
        <div style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: '#e2e8f0', textAlign: 'right' }}>{score}</div>
        <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#22c55e', textAlign: 'right', fontWeight: 600 }}>{Number(distanceToATH).toFixed(1)}x</div>
        <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, textAlign: 'right', color: roi30dMult >= 1 ? '#22c55e' : '#ef4444' }}>{roiDisplay}</div>
        <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#f5c842', textAlign: 'right', fontWeight: 600 }}>{runners30d}</div>
        <div style={{ display: 'flex', gap: 3, justifyContent: 'center' }}>
          {form.slice(0, 5).map((f, i) => (
            <div key={i} style={{ width: 6, height: 6, borderRadius: 1, background: f.result === 'win' ? '#22c55e' : f.result === 'loss' ? '#ef4444' : '#334155' }} />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 5, justifyContent: 'flex-end', alignItems: 'center' }}>
          {noteCount > 0 && (
            <span style={{ fontSize: 9, fontFamily: 'monospace', background: 'rgba(139,92,246,0.2)', color: '#a78bfa', padding: '1px 5px', borderRadius: 4 }}>📓 {noteCount}</span>
          )}
          <button onClick={handleRefresh} disabled={isRefreshing}
            style={{ padding: '3px 8px', borderRadius: 4, border: 'none', background: 'rgba(59,130,246,0.15)', color: '#60a5fa', fontSize: 11, fontFamily: 'monospace', fontWeight: 700, cursor: 'pointer', opacity: isRefreshing ? 0.5 : 1 }}>
            <RefreshCw size={10} style={{ display: 'inline', animation: isRefreshing ? 'spin 1s linear infinite' : 'none' }} />
          </button>
          <button onClick={handleDelete} disabled={isDeleting}
            style={{ padding: '3px 8px', borderRadius: 4, border: 'none', background: confirmDelete ? 'rgba(239,68,68,0.3)' : 'rgba(239,68,68,0.12)', color: confirmDelete ? '#fca5a5' : '#ef4444', fontSize: 11, fontFamily: 'monospace', fontWeight: 700, cursor: 'pointer', opacity: isDeleting ? 0.5 : 1, transition: 'all 0.15s' }}>
            {confirmDelete ? '?' : '✕'}
          </button>
          <div style={{ color: '#3a5a8a' }}>{isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}</div>
        </div>
      </div>

      {/* Expanded */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.18 }} style={{ overflow: 'hidden' }}>
            <div style={{ background: '#060c14', borderTop: '1px solid #1a2640' }}>

              <div style={{ display: 'flex', borderBottom: '1px solid #1a2640' }}>
                {[
                  { key: 'performance', label: '📊 Performance' },
                  { key: 'diary',       label: `📓 Diary${noteCount > 0 ? ` (${noteCount})` : ''}` },
                ].map(tab => (
                  <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                    style={{ padding: '8px 16px', fontFamily: 'monospace', fontSize: 11, fontWeight: 700, background: 'none', border: 'none', cursor: 'pointer', color: activeTab === tab.key ? '#e2e8f0' : '#3a5a8a', borderBottom: activeTab === tab.key ? '2px solid #8b5cf6' : '2px solid transparent', transition: 'all 0.15s' }}>
                    {tab.label}
                  </button>
                ))}
              </div>

              {activeTab === 'performance' && (
                <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20 }}>
                  <div>
                    <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', color: '#3a5a8a', marginBottom: 12 }}>● Performance Metrics</div>
                    <StatBar label="ATH Distance"   val={`${Number(distanceToATH).toFixed(1)}x`}  pct={Math.min((distanceToATH / 100) * 100, 100)} color="#22c55e" />
                    <StatBar label="Entry Quality"  val={`${Number(entryQuality).toFixed(1)}x`}   pct={Math.max(100 - (entryQuality / 50) * 100, 0)} color="#f5c842" />
                    <StatBar label="Consistency"    val={Number(consistency).toFixed(2)}           pct={(1 - Math.min(consistency, 1)) * 100} color="#a855f7" />
                    <StatBar label="Win Rate 7d/30d" val={`${Number(winRate7d).toFixed(0)}% / ${Number(winRate30d).toFixed(0)}%`} pct={Math.min(winRate7d, 100)} color="#3b82f6" />
                    <StatBar label="ROI 30d"        val={`${roi30dMult.toFixed(2)}x`}             pct={Math.min(roi30dMult * 50, 100)} color={roi30dMult >= 1 ? '#22c55e' : '#ef4444'} />
                  </div>
                  <div>
                    <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', color: '#3a5a8a', marginBottom: 12 }}>● Recent Runners</div>
                    {topRunners.length === 0
                      ? <div style={{ fontSize: 11, color: '#334155', fontFamily: 'monospace' }}>No runners in last 30d</div>
                      : topRunners.map((runner, i) => {
                          const sym  = runner.symbol || runner.token || runner;
                          const mult = runner.entry_to_ath_multiplier || 0;
                          return (
                            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, padding: '4px 8px', borderRadius: 4, background: 'rgba(245,200,66,0.06)', border: '1px solid rgba(245,200,66,0.15)' }}>
                              <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#f5c842', fontWeight: 700 }}>${sym}</span>
                              <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#64748b', marginLeft: 'auto' }}>{mult.toFixed(1)}x</span>
                            </div>
                          );
                        })
                    }
                    <div style={{ marginTop: 14 }}>
                      <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', color: '#3a5a8a', marginBottom: 8 }}>● Recent Form</div>
                      <div style={{ display: 'flex', gap: 3 }}>
                        {form.slice(0, 10).map((f, i) => (
                          <span key={i} style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 700, color: f.result === 'win' ? '#22c55e' : f.result === 'loss' ? '#ef4444' : '#475569' }}>
                            {f.result === 'win' ? 'W' : f.result === 'loss' ? 'L' : 'D'}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 9, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', color: '#3a5a8a', marginBottom: 12 }}>● Alerts</div>
                    {alerts.length === 0
                      ? <div style={{ fontSize: 11, color: '#22c55e', fontFamily: 'monospace' }}>✓ No active alerts</div>
                      : alerts.map((alert, i) => {
                          const aColors = {
                            red:    { bg: 'rgba(239,68,68,0.1)',  border: 'rgba(239,68,68,0.25)',  text: '#f87171', icon: '🔴' },
                            orange: { bg: 'rgba(249,115,22,0.1)', border: 'rgba(249,115,22,0.25)', text: '#fb923c', icon: '🟠' },
                            yellow: { bg: 'rgba(234,179,8,0.1)',  border: 'rgba(234,179,8,0.25)',  text: '#fbbf24', icon: '🟡' },
                          };
                          const ac = aColors[alert.severity] || aColors.yellow;
                          return (
                            <div key={i} style={{ display: 'flex', gap: 6, padding: '6px 8px', marginBottom: 6, borderRadius: 4, background: ac.bg, border: `1px solid ${ac.border}`, fontSize: 11, color: ac.text, fontFamily: 'monospace' }}>
                              <span>{ac.icon}</span> {alert.message}
                            </div>
                          );
                        })
                    }
                    <div style={{ marginTop: 12, fontSize: 11, color: '#334155', fontFamily: 'monospace' }}>
                      Last refresh: {wallet.last_updated ? new Date(wallet.last_updated).toLocaleString() : 'Never'}
                    </div>
                    <button onClick={handleRefresh} disabled={isRefreshing}
                      style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', borderRadius: 4, background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.3)', color: '#a78bfa', fontSize: 11, fontFamily: 'monospace', fontWeight: 700, cursor: 'pointer', opacity: isRefreshing ? 0.5 : 1 }}>
                      <RefreshCw size={11} style={{ animation: isRefreshing ? 'spin 1s linear infinite' : 'none' }} />
                      {isRefreshing ? 'Refreshing...' : 'Refresh'}
                    </button>
                  </div>
                </div>
              )}

              {activeTab === 'diary' && (
                <div style={{ padding: '16px 20px' }}>
                  <WalletDiary userId={userId} apiUrl={apiUrl} walletAddress={wallet.wallet_address} />
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}