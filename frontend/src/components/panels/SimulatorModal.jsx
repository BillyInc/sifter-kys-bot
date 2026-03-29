// SimulatorModal.jsx
// Wallet simulation wizard — 3 modes: Copy Simulator, Skill vs Luck, Exit Strategy
// Matches existing ResultsPanel design language exactly

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, ChevronRight, Zap, Brain, TrendingUp,
  Clock, Target, Filter, BarChart2, ArrowRight,
  AlertTriangle, CheckCircle, Loader, RotateCcw,
} from 'lucide-react';

// ── Formatters (mirrors ResultsPanel) ────────────────────────────────────────
const fmtX   = (v) => (v != null && !isNaN(v) ? `${Number(v).toFixed(2)}x` : '—');
const fmtPct = (v) => (v != null && !isNaN(v) ? `${v > 0 ? '+' : ''}${Number(v).toFixed(1)}%` : '—');
const fmtUsd = (v) => {
  if (v == null || v === 0) return '$0';
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${Number(v).toFixed(2)}`;
};

// ── Palette (matches app exactly) ────────────────────────────────────────────
const C = {
  bg0:      '#070b12',
  bg1:      '#0b0f17',
  bg2:      '#111827',
  bg3:      '#1a2232',
  bg4:      '#28303f',
  border:   '#1e2a3a',
  border2:  '#28303f',
  purple:   '#a855f7',
  purpleD:  '#7c3aed',
  green:    '#22c55e',
  yellow:   '#eab308',
  blue:     '#3b82f6',
  red:      '#ef4444',
  gray:     '#7c879c',
  grayL:    '#9aa4b8',
  grayD:    '#5d6a81',
  white:    '#f1f5f9',
  text:     '#e2e8f0',
};

// ── Shared sub-components ─────────────────────────────────────────────────────

const Mono = ({ children, style = {} }) => (
  <span style={{ fontFamily: 'monospace', ...style }}>{children}</span>
);

const Label = ({ children }) => (
  <div style={{
    fontFamily: 'monospace', fontSize: 9, color: C.grayL,
    textTransform: 'uppercase', letterSpacing: '0.10em',
    fontWeight: 700, marginBottom: 8,
  }}>
    {children}
  </div>
);

const MiniLabel = ({ children }) => (
  <div style={{
    fontFamily: 'monospace', fontSize: 7, color: C.grayD,
    textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 3,
  }}>
    {children}
  </div>
);

const Divider = () => (
  <div style={{ height: 1, background: C.border, margin: '16px 0' }} />
);

const StatCell = ({ label, value, color = C.white, sub }) => (
  <div style={{
    padding: '8px 10px', borderRadius: 4,
    background: C.bg3, border: `1px solid ${C.border2}`,
  }}>
    <MiniLabel>{label}</MiniLabel>
    <div style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color }}>{value}</div>
    {sub && <div style={{ fontFamily: 'monospace', fontSize: 9, color: C.grayD, marginTop: 2 }}>{sub}</div>}
  </div>
);

const ProbBar = ({ label, pct, color, value }) => (
  <div style={{ marginBottom: 10 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
      <Mono style={{ fontSize: 10, color: C.grayL }}>{label}</Mono>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Mono style={{ fontSize: 10, color }}>{value}</Mono>
        <Mono style={{ fontSize: 10, color: C.grayD }}>{pct}%</Mono>
      </div>
    </div>
    <div style={{ height: 6, background: C.bg4, borderRadius: 3, overflow: 'hidden' }}>
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
        style={{ height: '100%', background: `linear-gradient(90deg, ${color}88, ${color})`, borderRadius: 3 }}
      />
    </div>
  </div>
);

const RadioOption = ({ label, sub, selected, onClick }) => (
  <button
    onClick={onClick}
    style={{
      width: '100%', textAlign: 'left', padding: '8px 12px', borderRadius: 4,
      background: selected ? 'rgba(168,85,247,0.12)' : C.bg3,
      border: `1px solid ${selected ? 'rgba(168,85,247,0.4)' : C.border2}`,
      cursor: 'pointer', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 8,
      transition: 'all 0.15s',
    }}
  >
    <div style={{
      width: 14, height: 14, borderRadius: '50%', flexShrink: 0,
      border: `2px solid ${selected ? C.purple : C.grayD}`,
      background: selected ? C.purple : 'transparent',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {selected && <div style={{ width: 5, height: 5, borderRadius: '50%', background: '#fff' }} />}
    </div>
    <div>
      <Mono style={{ fontSize: 11, color: selected ? C.white : C.grayL }}>{label}</Mono>
      {sub && <div style={{ fontFamily: 'monospace', fontSize: 8, color: C.grayD, marginTop: 1 }}>{sub}</div>}
    </div>
  </button>
);

const SkillBar = ({ label, sub, value, score, color }) => (
  <div style={{ marginBottom: 12 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
      <div>
        <Mono style={{ fontSize: 10, color: C.grayL, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {label}
        </Mono>
        {sub && <div style={{ fontFamily: 'monospace', fontSize: 8, color: C.grayD, marginTop: 1 }}>{sub}</div>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Mono style={{ fontSize: 10, color: C.grayD }}>{value}</Mono>
        <Mono style={{ fontSize: 13, fontWeight: 700, color }}>{score}/100</Mono>
      </div>
    </div>
    <div style={{ height: 3, background: C.bg4, borderRadius: 2, overflow: 'hidden' }}>
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${score}%` }}
        transition={{ duration: 0.7, ease: 'easeOut' }}
        style={{ height: '100%', background: `linear-gradient(90deg, ${color}66, ${color})`, borderRadius: 2 }}
      />
    </div>
  </div>
);

// ── Tab definitions ───────────────────────────────────────────────────────────
const TABS = [
  { id: 'copy',  icon: Zap,       label: 'Copy Simulator',      sub: 'Your personalized return' },
  { id: 'skill', icon: Brain,     label: 'Skill vs Luck',       sub: 'Is this repeatable?' },
  { id: 'exit',  icon: TrendingUp, label: 'Exit Strategy',      sub: 'Best way to exit' },
];

const DELAY_OPTIONS = [
  { label: 'Ultra-fast bot',  sub: '~30 seconds',  minutes: 0.5  },
  { label: 'Fast manual',     sub: '~5 minutes',   minutes: 5    },
  { label: 'Average user',    sub: '~30 minutes',  minutes: 30   },
  { label: 'Slow user',       sub: '~4 hours',     minutes: 240  },
];

const EXIT_OPTIONS = [
  { id: 'copy',     label: 'Copy wallet exits',    sub: 'Sell when they sell'          },
  { id: 'ath',      label: 'Exit at ATH',          sub: 'Hold to peak, then sell'      },
  { id: 'trail20',  label: 'Trailing stop 20%',    sub: '20% drawdown from peak'       },
  { id: 'trail30',  label: 'Trailing stop 30%',    sub: '30% drawdown from peak'       },
  { id: 'tp3x',     label: 'Take profit at 3x',    sub: 'Exit at 3x and done'          },
  { id: 'hold',     label: 'Hold forever',         sub: 'Diamond hands — never sell'   },
];

// =============================================================================
// MAIN COMPONENT
// =============================================================================
export default function SimulatorModal({ walletData, onClose, apiUrl, getAccessToken }) {
  const [activeTab,    setActiveTab]    = useState('copy');
  const [delayIdx,     setDelayIdx]     = useState(2);          // default: average user
  const [exitId,       setExitId]       = useState('trail20');
  const [filterMin,    setFilterMin]    = useState('0');        // min buy size $ (string to allow empty while typing)
  const [ignoreSells,  setIgnoreSells]  = useState(false);
  const [loading,      setLoading]      = useState(false);
  const [results,      setResults]      = useState(null);       // null = not run yet
  const [error,        setError]        = useState(null);

  const addr       = walletData?.wallet || walletData?.wallet_address || '';
  const shortAddr  = addr ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : '—';
  const roiDetails = walletData?.roi_details || [];

  // ── Clear results ─────────────────────────────────────────────────────────
  const clearResults = () => {
    setResults(null);
    setError(null);
  };

  // ── Run simulation ────────────────────────────────────────────────────────
  const runSimulation = async () => {
    // Immediately wipe old results so the panel doesn't show stale data
    setResults(null);
    setError(null);
    setLoading(true);

    try {
      const authToken = getAccessToken?.();
      const endpoint = {
        copy:  '/api/simulator/copy',
        skill: '/api/simulator/skill',
        exit:  '/api/simulator/exit-strategies',
      }[activeTab];

      const body = {
        wallet_address:  addr,
        roi_details:     roiDetails,
        other_runners:   walletData?.other_runners || [],
        consistency_score: walletData?.consistency_score ?? 50,
        score_breakdown: walletData?.score_breakdown || {},
        // copy-specific
        delay_minutes:   DELAY_OPTIONS[delayIdx].minutes,
        exit_strategy:   exitId,
        filter_min_usd:  Number(filterMin) || 0,
        ignore_sells:    ignoreSells,
      };

      const res  = await fetch(`${apiUrl}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || 'Simulation failed');
      setResults(data.results);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // ── Close on Escape ───────────────────────────────────────────────────────
  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);

  // Reset results when tab changes (but NOT on every settings tweak — user
  // can change settings and re-run without the panel blanking unexpectedly)
  useEffect(() => { setResults(null); setError(null); }, [activeTab]);

  const hasResults = !loading && results;

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 300,
        background: 'rgba(0,0,0,0.85)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.97, y: 12 }}
        animate={{ opacity: 1, scale: 1,    y: 0  }}
        exit={{ opacity: 0, scale: 0.97, y: 12 }}
        transition={{ duration: 0.18 }}
        style={{
          width: '100%', maxWidth: 900,
          background: 'var(--bg-primary)', borderRadius: 12,
          border: '1px solid var(--border-color)',
          boxShadow: '0 32px 64px -12px rgba(0,0,0,0.9), 0 0 0 1px rgba(168,85,247,0.1)',
          display: 'flex', flexDirection: 'column',
          maxHeight: '92vh', overflow: 'hidden',
        }}
      >
        {/* ── Header ── */}
        <div style={{
          padding: '12px 20px', background: '#1a1429',
          borderBottom: '1px solid #2d2642',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <div>
            <div style={{ fontFamily: 'monospace', fontSize: 15, fontWeight: 700, color: C.white, letterSpacing: '0.02em' }}>
              ⚗️ Wallet Simulator
            </div>
            <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#a78bfa', marginTop: 2 }}>
              {shortAddr}
              {roiDetails.length > 0 && (
                <span style={{ color: C.grayD, marginLeft: 8 }}>
                  {roiDetails.length} trade{roiDetails.length !== 1 ? 's' : ''} available
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              width: 30, height: 30, borderRadius: 6,
              border: '1px solid #3d2d3a', background: 'rgba(239,68,68,0.15)', color: '#f87171',
              fontSize: 15, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >✕</button>
        </div>

        {/* ── Tab bar ── */}
        <div style={{
          display: 'flex', padding: '8px 20px 0', gap: 4,
          background: C.bg2, borderBottom: `1px solid ${C.border}`,
          flexShrink: 0,
        }}>
          {TABS.map(({ id, icon: Icon, label, sub }) => {
            const active = activeTab === id;
            return (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                style={{
                  padding: '8px 14px 9px', borderRadius: '6px 6px 0 0',
                  border: active ? `1px solid ${C.border}` : '1px solid transparent',
                  borderBottom: active ? `1px solid ${C.bg1}` : 'none',
                  background: active ? C.bg1 : 'transparent',
                  cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: 7,
                  transition: 'all 0.12s',
                  marginBottom: active ? -1 : 0,
                }}
              >
                <Icon size={13} color={active ? C.purple : C.grayD} />
                <div style={{ textAlign: 'left' }}>
                  <div style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: active ? 700 : 400, color: active ? C.white : C.gray }}>
                    {label}
                  </div>
                  <div style={{ fontFamily: 'monospace', fontSize: 8, color: C.grayD }}>{sub}</div>
                </div>
              </button>
            );
          })}
        </div>

        {/* ── Body ── */}
        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

          {/* ── Left: Config ── */}
          <div style={{
            width: 280, flexShrink: 0, padding: '16px 20px',
            background: C.bg2, borderRight: `1px solid ${C.border}`,
            overflowY: 'auto',
          }}>

            {/* COPY CONFIG */}
            {activeTab === 'copy' && (
              <>
                <Label>Entry Delay</Label>
                {DELAY_OPTIONS.map((opt, i) => (
                  <RadioOption
                    key={opt.label}
                    label={opt.label}
                    sub={opt.sub}
                    selected={delayIdx === i}
                    onClick={() => setDelayIdx(i)}
                  />
                ))}

                <Divider />
                <Label>Exit Strategy</Label>
                {EXIT_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.id}
                    label={opt.label}
                    sub={opt.sub}
                    selected={exitId === opt.id}
                    onClick={() => setExitId(opt.id)}
                  />
                ))}

                <Divider />
                <Label>Trade Filters</Label>
                <div style={{
                  padding: '8px 10px', borderRadius: 4,
                  background: C.bg3, border: `1px solid ${C.border2}`, marginBottom: 6,
                }}>
                  <div style={{ fontFamily: 'monospace', fontSize: 9, color: C.grayL, marginBottom: 6 }}>
                    MIN BUY SIZE
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <Mono style={{ fontSize: 10, color: C.grayD }}>$</Mono>
                    <input
                      type="number"
                      value={filterMin}
                      min={0}
                      onChange={(e) => setFilterMin(e.target.value)}
                      onBlur={(e) => {
                        const n = Number(e.target.value);
                        setFilterMin(String(isNaN(n) || n < 0 ? 0 : n));
                      }}
                      onKeyDown={(e) => { if (e.key === '-' || e.key === 'e') e.preventDefault(); }}
                      style={{
                        background: C.bg4, border: `1px solid ${C.border2}`,
                        borderRadius: 3, padding: '3px 6px',
                        color: C.white, fontFamily: 'monospace', fontSize: 11,
                        width: '80px', outline: 'none',
                      }}
                    />
                  </div>
                </div>
                <button
                  onClick={() => setIgnoreSells(!ignoreSells)}
                  style={{
                    width: '100%', textAlign: 'left', padding: '7px 10px', borderRadius: 4,
                    background: ignoreSells ? 'rgba(168,85,247,0.1)' : C.bg3,
                    border: `1px solid ${ignoreSells ? 'rgba(168,85,247,0.35)' : C.border2}`,
                    cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 7,
                  }}
                >
                  <div style={{
                    width: 12, height: 12, borderRadius: 2, flexShrink: 0,
                    border: `2px solid ${ignoreSells ? C.purple : C.grayD}`,
                    background: ignoreSells ? C.purple : 'transparent',
                  }} />
                  <Mono style={{ fontSize: 10, color: ignoreSells ? C.white : C.gray }}>
                    Ignore sells (hold)
                  </Mono>
                </button>
              </>
            )}

            {/* SKILL CONFIG */}
            {activeTab === 'skill' && (
              <>
                <Label>Analysis basis</Label>
                <div style={{
                  padding: '10px 12px', borderRadius: 4,
                  background: C.bg3, border: `1px solid ${C.border2}`,
                  marginBottom: 8,
                }}>
                  <Mono style={{ fontSize: 10, color: C.grayL, lineHeight: 1.6 }}>
                    Measures the wallet's own internal consistency across:
                  </Mono>
                  {['Entry timing variance', 'Profit distribution', 'Win rate stability', 'Risk management'].map((item) => (
                    <div key={item} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 }}>
                      <div style={{ width: 4, height: 4, borderRadius: '50%', background: C.purple, flexShrink: 0 }} />
                      <Mono style={{ fontSize: 10, color: C.grayL }}>{item}</Mono>
                    </div>
                  ))}
                </div>
                <div style={{
                  padding: '8px 10px', borderRadius: 4,
                  background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)',
                  marginTop: 8,
                }}>
                  <Mono style={{ fontSize: 9, color: '#f87171' }}>
                    NOT a comparison to other wallets. Purely internal.
                  </Mono>
                </div>
              </>
            )}

            {/* EXIT CONFIG */}
            {activeTab === 'exit' && (
              <>
                <Label>About this analysis</Label>
                <div style={{
                  padding: '10px 12px', borderRadius: 4,
                  background: C.bg3, border: `1px solid ${C.border2}`,
                  marginBottom: 8,
                }}>
                  <Mono style={{ fontSize: 10, color: C.grayL, lineHeight: 1.6 }}>
                    Tests all exit strategies against every historical trade this wallet made.
                  </Mono>
                </div>
                <div style={{
                  padding: '10px 12px', borderRadius: 4,
                  background: 'rgba(168,85,247,0.08)', border: '1px solid rgba(168,85,247,0.2)',
                }}>
                  <Mono style={{ fontSize: 9, color: '#c4b5fd' }}>
                    Strategies tested: ATH exit, copy wallet, trailing 20%, trailing 30%, take profit 3x, hold forever
                  </Mono>
                </div>
              </>
            )}

            {/* ── Run / Re-run + Clear buttons ── */}
            <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <button
                onClick={runSimulation}
                disabled={loading || roiDetails.length === 0}
                style={{
                  width: '100%', padding: '10px', borderRadius: 6, border: 'none',
                  background: loading || roiDetails.length === 0
                    ? C.bg4
                    : `linear-gradient(90deg, ${C.purpleD}, ${C.purple})`,
                  color: loading || roiDetails.length === 0 ? C.grayD : '#fff',
                  fontFamily: 'monospace', fontSize: 12, fontWeight: 700,
                  cursor: loading || roiDetails.length === 0 ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7,
                  transition: 'all 0.15s',
                }}
              >
                {loading ? (
                  <><Loader size={13} className="animate-spin" /> Running…</>
                ) : hasResults ? (
                  <><RotateCcw size={13} /> Re-run Simulation</>
                ) : (
                  <>Run Simulation <ArrowRight size={13} /></>
                )}
              </button>

              {/* Clear button — only visible when results are showing */}
              {hasResults && (
                <button
                  onClick={clearResults}
                  style={{
                    width: '100%', padding: '7px', borderRadius: 6,
                    border: `1px solid ${C.border2}`,
                    background: 'transparent',
                    color: C.grayD,
                    fontFamily: 'monospace', fontSize: 11, fontWeight: 600,
                    cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                    transition: 'all 0.15s',
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.borderColor = C.red + '66';
                    e.currentTarget.style.color = C.red;
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.borderColor = C.border2;
                    e.currentTarget.style.color = C.grayD;
                  }}
                >
                  <X size={11} /> Clear Results
                </button>
              )}

              {roiDetails.length === 0 && (
                <div style={{ fontFamily: 'monospace', fontSize: 9, color: C.grayD, marginTop: 2, textAlign: 'center' }}>
                  No trade history available for this wallet
                </div>
              )}
            </div>
          </div>

          {/* ── Right: Results ── */}
          <div style={{ flex: 1, padding: '16px 20px', overflowY: 'auto', background: C.bg1 }}>

            {/* Loading */}
            {loading && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 12 }}>
                <div style={{
                  width: 40, height: 40, borderRadius: '50%',
                  border: `3px solid ${C.bg4}`, borderTopColor: C.purple,
                  animation: 'spin 0.7s linear infinite',
                }} />
                <Mono style={{ fontSize: 12, color: C.grayL }}>
                  {activeTab === 'copy'  && 'Simulating your returns…'}
                  {activeTab === 'skill' && 'Analyzing behavioral consistency…'}
                  {activeTab === 'exit'  && 'Testing exit strategies…'}
                </Mono>
                <Mono style={{ fontSize: 9, color: C.grayD }}>Processing {roiDetails.length} trades</Mono>
              </div>
            )}

            {/* Error */}
            {error && !loading && (
              <div style={{
                padding: '12px 16px', borderRadius: 6,
                background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
                display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 12,
              }}>
                <AlertTriangle size={16} color={C.red} style={{ flexShrink: 0, marginTop: 1 }} />
                <div>
                  <Mono style={{ fontSize: 11, color: C.red, fontWeight: 700 }}>Simulation Error</Mono>
                  <Mono style={{ fontSize: 10, color: '#fca5a5', marginTop: 4 }}>{error}</Mono>
                </div>
              </div>
            )}

            {/* Empty state */}
            {!loading && !results && !error && (
              <div style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                justifyContent: 'center', height: '100%', gap: 10,
              }}>
                {activeTab === 'copy'  && <Zap      size={36} color={C.bg4} />}
                {activeTab === 'skill' && <Brain    size={36} color={C.bg4} />}
                {activeTab === 'exit'  && <TrendingUp size={36} color={C.bg4} />}
                <Mono style={{ fontSize: 12, color: C.gray }}>
                  {activeTab === 'copy'  && 'Configure your settings and run the simulation'}
                  {activeTab === 'skill' && 'Run analysis to check if this is skill or luck'}
                  {activeTab === 'exit'  && 'Run to compare all exit strategies'}
                </Mono>
                <Mono style={{ fontSize: 10, color: C.grayD }}>
                  {roiDetails.length} trade{roiDetails.length !== 1 ? 's' : ''} will be analyzed
                </Mono>
              </div>
            )}

            {/* ── COPY RESULTS ── */}
            {!loading && results && activeTab === 'copy' && (
              <CopyResults results={results} delayLabel={DELAY_OPTIONS[delayIdx].label} exitLabel={EXIT_OPTIONS.find(e => e.id === exitId)?.label} />
            )}

            {/* ── SKILL RESULTS ── */}
            {!loading && results && activeTab === 'skill' && (
              <SkillResults results={results} />
            )}

            {/* ── EXIT RESULTS ── */}
            {!loading && results && activeTab === 'exit' && (
              <ExitResults results={results} />
            )}
          </div>
        </div>
      </motion.div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

// =============================================================================
// COPY RESULTS
// =============================================================================
function CopyResults({ results, delayLabel, exitLabel }) {
  const past   = results.past_period  || {};
  const future = results.future_period || {};
  const risk   = results.risk          || {};

  return (
    <div>
      {/* Settings echo */}
      <div style={{
        display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap',
      }}>
        {[
          { icon: Clock,  label: delayLabel },
          { icon: Target, label: exitLabel  },
          { icon: Filter, label: `Min $${results.filter_min_usd || 0}` },
        ].map(({ icon: Icon, label }) => (
          <div key={label} style={{
            display: 'flex', alignItems: 'center', gap: 5,
            padding: '3px 8px', borderRadius: 20,
            background: C.bg3, border: `1px solid ${C.border2}`,
          }}>
            <Icon size={9} color={C.purple} />
            <Mono style={{ fontSize: 9, color: C.grayL }}>{label}</Mono>
          </div>
        ))}
      </div>

      {/* Past period */}
      <Label>● Past 30 Days — If You Had Copied</Label>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginBottom: 12 }}>
        <StatCell label="Wallet Return"   value={fmtPct(past.wallet_roi_pct)}  color={C.grayL} />
        <StatCell
          label="YOUR Return"
          value={fmtPct(past.your_roi_pct)}
          color={(past.your_roi_pct || 0) >= 0 ? C.green : C.red}
          sub={`with ${delayLabel}`}
        />
        <StatCell
          label="Gap (delay cost)"
          value={fmtPct((past.your_roi_pct || 0) - (past.wallet_roi_pct || 0))}
          color={C.red}
          sub="avg per trade"
        />
      </div>

      {past.biggest_miss && (
        <div style={{
          padding: '8px 12px', borderRadius: 4,
          background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.18)',
          marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <AlertTriangle size={12} color={C.red} />
          <Mono style={{ fontSize: 10, color: '#fca5a5' }}>
            Biggest miss: <span style={{ color: C.yellow }}>${past.biggest_miss.symbol}</span>
            {' — '}got {fmtX(past.biggest_miss.your_mult)} instead of {fmtX(past.biggest_miss.wallet_mult)}
          </Mono>
        </div>
      )}

      <Divider />

      {/* Future period */}
      <Label>● Next 30 Days — 10,000 Monte Carlo Simulations</Label>
      <div style={{ marginBottom: 14 }}>
        <ProbBar label="Most likely (70%)"  pct={70} color={C.blue}  value={`${fmtPct(future.likely_low)} → ${fmtPct(future.likely_high)}`} />
        <ProbBar label="Good scenario (20%)" pct={20} color={C.green} value={`${fmtPct(future.good_low)} → ${fmtPct(future.good_high)}`} />
        <ProbBar label="Bad scenario (10%)"  pct={10} color={C.red}   value={`${fmtPct(future.bad_low)} → ${fmtPct(future.bad_high)}`} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginBottom: 14 }}>
        <StatCell label="Prob of Profit"   value={`${future.prob_profit || 0}%`}   color={C.green} />
        <StatCell label="Prob of Loss"     value={`${future.prob_loss || 0}%`}     color={C.red}   />
        <StatCell label="Worst Case"       value={fmtPct(future.worst_case)}       color={C.red}   />
      </div>

      <Divider />

      {/* Risk */}
      <Label>● Risk Analysis</Label>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
        <StatCell label="Max Drawdown"     value={fmtPct(risk.max_drawdown)}         color={C.red}   />
        <StatCell label="Recovery Time"   value={risk.recovery_weeks ? `${risk.recovery_weeks}w` : '—'} color={C.yellow} />
        <StatCell label="Suggested Alloc" value={risk.suggested_allocation || '—'}   color={C.blue}  />
      </div>
    </div>
  );
}

// =============================================================================
// SKILL RESULTS
// =============================================================================
function SkillResults({ results }) {
  const score    = results.overall_skill_score   || 0;
  const verdict  = results.verdict               || 'UNKNOWN';
  const factors  = results.factors               || {};
  const outlook  = results.future_outlook_pct    || 0;
  const confidence = results.confidence_pct      || 0;

  const verdictColor = verdict.includes('SKILLED') ? C.green
    : verdict.includes('LUCKY') ? C.red
    : C.yellow;

  return (
    <div>
      {/* Verdict banner */}
      <div style={{
        padding: '16px 20px', borderRadius: 6, marginBottom: 16,
        background: verdict.includes('SKILLED') ? 'rgba(34,197,94,0.08)' : verdict.includes('LUCKY') ? 'rgba(239,68,68,0.08)' : 'rgba(234,179,8,0.08)',
        border: `1px solid ${verdictColor}40`,
        display: 'flex', alignItems: 'center', gap: 14,
      }}>
        <div style={{ textAlign: 'center', flexShrink: 0, minWidth: 64 }}>
          <div style={{ fontFamily: 'monospace', fontSize: 36, fontWeight: 900, color: verdictColor, lineHeight: 1 }}>
            {score}
          </div>
          <div style={{ fontFamily: 'monospace', fontSize: 8, color: verdictColor, textTransform: 'uppercase', letterSpacing: '0.1em', marginTop: 2 }}>
            / 100
          </div>
        </div>
        <div>
          <div style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: verdictColor }}>
            {verdict}
          </div>
          <div style={{ fontFamily: 'monospace', fontSize: 10, color: C.grayL, marginTop: 4, lineHeight: 1.5 }}>
            {verdict.includes('SKILLED') && 'Repeatable process. Performance likely to continue.'}
            {verdict.includes('LUCKY')   && 'Performance driven by one or two exceptional trades.'}
            {verdict.includes('MIXED')   && 'Some skill signals present. Mixed track record.'}
          </div>
        </div>
      </div>

      {/* Factor bars */}
      <Label>● Skill Factor Breakdown</Label>
      <div style={{ marginBottom: 16 }}>
        <SkillBar
          label="Entry Consistency"
          sub={factors.entry_consistency?.detail || 'How reliably early vs ATH'}
          value={factors.entry_consistency?.value_label || '—'}
          score={factors.entry_consistency?.score || 0}
          color={C.purple}
        />
        <SkillBar
          label="Profit Distribution"
          sub="Top trade as % of total profit"
          value={factors.profit_distribution?.value_label || '—'}
          score={factors.profit_distribution?.score || 0}
          color={C.yellow}
        />
        <SkillBar
          label="Win Rate Stability"
          sub="Variance across trades"
          value={factors.win_rate_stability?.value_label || '—'}
          score={factors.win_rate_stability?.score || 0}
          color={C.blue}
        />
        <SkillBar
          label="Risk Management"
          sub="Max loss controlled"
          value={factors.risk_management?.value_label || '—'}
          score={factors.risk_management?.score || 0}
          color={C.green}
        />
      </div>

      <Divider />

      {/* Forward outlook */}
      <Label>● Monte Carlo Forward Outlook</Label>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        <StatCell
          label="Future Perf Probability"
          value={`${outlook}%`}
          color={outlook >= 70 ? C.green : outlook >= 50 ? C.yellow : C.red}
          sub="probability of continued performance"
        />
        <StatCell
          label="Confidence"
          value={`${confidence}%`}
          color={C.blue}
          sub="based on trade sample size"
        />
      </div>

      {/* What this means */}
      {results.implications && results.implications.length > 0 && (
        <>
          <Divider />
          <Label>● What This Means</Label>
          {results.implications.map((imp, i) => (
            <div key={`implication-${i}`} style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
              <CheckCircle size={12} color={verdictColor} style={{ flexShrink: 0, marginTop: 2 }} />
              <Mono style={{ fontSize: 10, color: C.grayL, lineHeight: 1.5 }}>{imp}</Mono>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

// =============================================================================
// EXIT STRATEGY RESULTS
// =============================================================================
function ExitResults({ results }) {
  const strategies  = results.strategies || [];
  const recommended = results.recommended || null;
  const tradeCount  = results.trade_count  || 0;

  if (strategies.length === 0) {
    return (
      <div style={{ padding: '20px', fontFamily: 'monospace', fontSize: 11, color: C.gray }}>
        No exit strategy data returned. Ensure roi_details includes exit price history.
      </div>
    );
  }

  const maxAvgROI = Math.max(...strategies.map(s => s.avg_roi_mult || 0));

  return (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
        <Mono style={{ fontSize: 10, color: C.grayD }}>
          Based on {tradeCount} historical trade{tradeCount !== 1 ? 's' : ''}
        </Mono>
      </div>

      {/* Table header */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1.6fr 0.9fr 0.9fr 0.9fr 0.9fr',
        gap: 4, padding: '5px 10px',
        background: C.bg2, borderRadius: '4px 4px 0 0',
        border: `1px solid ${C.border2}`,
      }}>
        {['Strategy', 'Avg ROI', 'Win Rate', 'Best', 'Worst'].map(h => (
          <Mono key={h} style={{ fontSize: 8, color: C.grayD, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            {h}
          </Mono>
        ))}
      </div>

      {strategies.map((s, i) => {
        const isRec = s.id === recommended;
        const isBest = s.avg_roi_mult === maxAvgROI;
        return (
          <div
            key={s.id}
            style={{
              display: 'grid',
              gridTemplateColumns: '1.6fr 0.9fr 0.9fr 0.9fr 0.9fr',
              gap: 4, padding: '9px 10px',
              background: isRec ? 'rgba(168,85,247,0.08)' : i % 2 === 0 ? C.bg3 : C.bg1,
              border: `1px solid ${isRec ? 'rgba(168,85,247,0.3)' : C.border2}`,
              borderTop: i === 0 ? 'none' : `1px solid ${C.border2}`,
              borderRadius: i === strategies.length - 1 ? '0 0 4px 4px' : 0,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Mono style={{ fontSize: 11, color: isRec ? C.purple : C.white, fontWeight: isRec ? 700 : 400 }}>
                {s.label}
              </Mono>
              {isRec && (
                <span style={{
                  fontSize: 7, padding: '1px 4px', borderRadius: 2,
                  background: 'rgba(168,85,247,0.2)', border: '1px solid rgba(168,85,247,0.4)',
                  color: C.purple, fontFamily: 'monospace', fontWeight: 700,
                }}>
                  BEST FIT
                </span>
              )}
            </div>
            <Mono style={{ fontSize: 11, fontWeight: 700, color: isBest ? C.green : C.white }}>
              {fmtX(s.avg_roi_mult)}
            </Mono>
            <Mono style={{ fontSize: 11, color: (s.win_rate || 0) >= 70 ? C.green : (s.win_rate || 0) >= 50 ? C.yellow : C.red }}>
              {s.win_rate != null ? `${s.win_rate}%` : '—'}
            </Mono>
            <Mono style={{ fontSize: 11, color: C.green }}>{fmtX(s.best_mult)}</Mono>
            <Mono style={{ fontSize: 11, color: C.red }}>{fmtX(s.worst_mult)}</Mono>
          </div>
        );
      })}

      {/* Recommendation explanation */}
      {results.recommendation_reason && (
        <div style={{
          marginTop: 12, padding: '10px 12px', borderRadius: 4,
          background: 'rgba(168,85,247,0.07)', border: '1px solid rgba(168,85,247,0.2)',
        }}>
          <Label>● Why {strategies.find(s => s.id === recommended)?.label || 'This Strategy'}</Label>
          <Mono style={{ fontSize: 10, color: C.grayL, lineHeight: 1.6 }}>
            {results.recommendation_reason}
          </Mono>
        </div>
      )}

      {/* Per-strategy stat grid */}
      {strategies.length > 0 && (
        <>
          <Divider />
          <Label>● Win Rate Distribution</Label>
          {strategies.map((s) => (
            <ProbBar
              key={s.id}
              label={s.label}
              pct={s.win_rate || 0}
              color={s.id === recommended ? C.purple : C.blue}
              value={fmtX(s.avg_roi_mult)}
            />
          ))}
        </>
      )}
    </div>
  );
}