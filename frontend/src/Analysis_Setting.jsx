import React, { useState, useEffect } from 'react';
import { Settings, Target, Zap, Award, TrendingUp, Info, ChevronDown, ChevronUp, Check } from 'lucide-react';

export default function AnalysisSettings({ 
  selectedTokens, 
  onSettingsChange,
  analysisType
}) {
  const [settingsMode, setSettingsMode] = useState('global');
  const [globalSettings, setGlobalSettings] = useState({
    minRoiMultiplier: 3.0,
    daysBack: 7,
    candleSize: '5m',
    tweetWindow: { minus: 35, plus: 10 }
  });
  const [perTokenSettings, setPerTokenSettings] = useState({});
  const [expandedTokens, setExpandedTokens] = useState({});
  const [showInfo, setShowInfo] = useState(false);

  const roiPresets = [
    { value: 3,  label: '3x',  sublabel: 'Broad',   color: '#22c55e', bg: 'rgba(34,197,94,0.12)',  border: 'rgba(34,197,94,0.35)' },
    { value: 5,  label: '5x',  sublabel: 'Standard',color: '#3b82f6', bg: 'rgba(59,130,246,0.12)', border: 'rgba(59,130,246,0.35)' },
    { value: 10, label: '10x', sublabel: 'Sharp',   color: '#a855f7', bg: 'rgba(168,85,247,0.12)', border: 'rgba(168,85,247,0.35)' },
    { value: 20, label: '20x', sublabel: 'Elite',   color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.35)' },
  ];

  const candleSizes = ['1m','5m','15m','1h','4h','1d'];

  useEffect(() => {
    const updated = {};
    selectedTokens.forEach(t => {
      updated[t.address] = perTokenSettings[t.address] || { ...globalSettings };
    });
    setPerTokenSettings(updated);
  }, [selectedTokens]);

  useEffect(() => {
    if (onSettingsChange) {
      onSettingsChange({ mode: settingsMode, globalSettings, perTokenSettings });
    }
  }, [settingsMode, globalSettings, perTokenSettings]);

  const updateGlobal = (field, value) => setGlobalSettings(p => ({ ...p, [field]: value }));
  const updateGlobalTweet = (field, value) => setGlobalSettings(p => ({ ...p, tweetWindow: { ...p.tweetWindow, [field]: parseInt(value)||0 } }));
  const updatePerToken = (addr, field, value) => setPerTokenSettings(p => ({ ...p, [addr]: { ...p[addr], [field]: value } }));
  const updatePerTokenTweet = (addr, field, value) => setPerTokenSettings(p => ({ ...p, [addr]: { ...p[addr], tweetWindow: { ...p[addr].tweetWindow, [field]: parseInt(value)||0 } } }));
  const toggleToken = addr => setExpandedTokens(p => ({ ...p, [addr]: !p[addr] }));
  const applyGlobalToAll = () => {
    const u = {};
    selectedTokens.forEach(t => { u[t.address] = { ...globalSettings }; });
    setPerTokenSettings(u);
  };

  if (selectedTokens.length === 0) {
    return (
      <div style={{ padding: '48px 24px', textAlign: 'center' }}>
        <div style={{ 
          width: 64, height: 64, borderRadius: 16,
          background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 16px'
        }}>
          <Settings size={28} color="rgba(255,255,255,0.25)" />
        </div>
        <p style={{ color: 'rgba(255,255,255,0.35)', fontSize: 14 }}>Select tokens above to configure analysis</p>
      </div>
    );
  }

  const activePreset = roiPresets.find(p => p.value === globalSettings.minRoiMultiplier);

  // ── GENERAL MODE ─────────────────────────────────────────────────────────
  if (analysisType === 'general') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

        {/* Mode toggle - compact pill */}
        <div style={{ display: 'flex', gap: 4, background: 'rgba(255,255,255,0.04)', borderRadius: 10, padding: 4 }}>
          {['global','per-token'].map(m => (
            <button key={m} onClick={() => setSettingsMode(m)} style={{
              flex: 1, padding: '7px 12px', borderRadius: 7, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600, transition: 'all 0.2s',
              background: settingsMode === m ? 'rgba(168,85,247,0.9)' : 'transparent',
              color: settingsMode === m ? '#fff' : 'rgba(255,255,255,0.45)',
            }}>
              {m === 'global' ? 'Global' : 'Per-Token'}
            </button>
          ))}
        </div>

        {settingsMode === 'global' && (
          <>
            {/* ROI Presets - 2x2 grid to use width */}
            <div style={{ 
              background: 'rgba(255,255,255,0.03)', 
              border: '1px solid rgba(255,255,255,0.08)', 
              borderRadius: 12, padding: 16 
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', marginBottom: 12 }}>
                Min ROI Threshold
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 14 }}>
                {roiPresets.map(p => {
                  const active = globalSettings.minRoiMultiplier === p.value;
                  return (
                    <button key={p.value} onClick={() => updateGlobal('minRoiMultiplier', p.value)} style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '10px 14px', borderRadius: 9, border: `1px solid ${active ? p.border : 'rgba(255,255,255,0.08)'}`,
                      background: active ? p.bg : 'rgba(255,255,255,0.03)',
                      cursor: 'pointer', transition: 'all 0.18s',
                    }}>
                      <div style={{ textAlign: 'left' }}>
                        <div style={{ fontSize: 18, fontWeight: 800, color: active ? p.color : 'rgba(255,255,255,0.7)', lineHeight: 1 }}>{p.label}</div>
                        <div style={{ fontSize: 10, color: active ? p.color : 'rgba(255,255,255,0.3)', marginTop: 2 }}>{p.sublabel}</div>
                      </div>
                      {active && (
                        <div style={{ 
                          width: 18, height: 18, borderRadius: '50%', 
                          background: p.color, display: 'flex', alignItems: 'center', justifyContent: 'center' 
                        }}>
                          <Check size={11} color="#fff" strokeWidth={3} />
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>

              {/* Custom slider row */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', whiteSpace: 'nowrap' }}>Custom</span>
                <input type="range" min="1" max="50" step="0.5"
                  value={globalSettings.minRoiMultiplier}
                  onChange={e => updateGlobal('minRoiMultiplier', parseFloat(e.target.value))}
                  style={{ flex: 1, accentColor: '#a855f7', cursor: 'pointer' }}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <input type="number" min="1" max="50" step="0.5"
                    value={globalSettings.minRoiMultiplier}
                    onChange={e => updateGlobal('minRoiMultiplier', parseFloat(e.target.value)||1)}
                    style={{
                      width: 48, background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.12)',
                      borderRadius: 6, padding: '4px 6px', color: '#fff', fontSize: 13,
                      textAlign: 'center', outline: 'none'
                    }}
                  />
                  <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)' }}>x</span>
                </div>
              </div>
            </div>

            {/* Fixed criteria - horizontal 3-col */}
            <div style={{ 
              background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', 
              borderRadius: 12, overflow: 'hidden'
            }}>
              <button onClick={() => setShowInfo(!showInfo)} style={{
                width: '100%', padding: '12px 16px', background: 'transparent', border: 'none',
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Info size={14} color="rgba(96,165,250,0.8)" />
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'rgba(255,255,255,0.6)' }}>Fixed Criteria</span>
                </div>
                {showInfo 
                  ? <ChevronUp size={14} color="rgba(255,255,255,0.3)" />
                  : <ChevronDown size={14} color="rgba(255,255,255,0.3)" />
                }
              </button>

              {showInfo && (
                <div style={{ padding: '0 16px 16px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                  {/* 3-col stats */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 12, marginTop: 12 }}>
                    <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
                      <div style={{ fontSize: 18, fontWeight: 800, color: '#22c55e' }}>$100</div>
                      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>Min Invest</div>
                    </div>
                    <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
                      <div style={{ fontSize: 18, fontWeight: 800, color: '#a855f7' }}>6</div>
                      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>Steps</div>
                    </div>
                    <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
                      <div style={{ fontSize: 18, fontWeight: 800, color: '#f59e0b' }}>30d</div>
                      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>History</div>
                    </div>
                  </div>

                  <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.45)', lineHeight: 1.7 }}>
                    ✓ Score: 60% timing · 30% profit · 10% overall<br/>
                    ✓ Entry-to-ATH multipliers<br/>
                    ✓ 30d runner history (5x+ tokens)<br/>
                    ✓ Consistency grades A+ to F
                  </div>
                </div>
              )}
            </div>

            {/* Live summary bar */}
            <div style={{
              padding: '10px 14px', borderRadius: 9,
              background: activePreset ? activePreset.bg : 'rgba(168,85,247,0.08)',
              border: `1px solid ${activePreset ? activePreset.border : 'rgba(168,85,247,0.2)'}`,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between'
            }}>
              <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.55)' }}>Active threshold</span>
              <span style={{ 
                fontSize: 14, fontWeight: 800, 
                color: activePreset ? activePreset.color : '#a855f7'
              }}>
                {globalSettings.minRoiMultiplier}x ROI minimum
              </span>
            </div>
          </>
        )}

        {settingsMode === 'per-token' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button onClick={applyGlobalToAll} style={{
                fontSize: 11, padding: '5px 10px', borderRadius: 6,
                background: 'rgba(168,85,247,0.12)', border: '1px solid rgba(168,85,247,0.25)',
                color: 'rgba(168,85,247,0.9)', cursor: 'pointer'
              }}>
                Apply global to all
              </button>
            </div>

            {selectedTokens.map((token, i) => {
              const s = perTokenSettings[token.address] || globalSettings;
              const expanded = expandedTokens[token.address];
              const preset = roiPresets.find(p => p.value === s.minRoiMultiplier);

              return (
                <div key={token.address} style={{
                  background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 10, overflow: 'hidden'
                }}>
                  <button onClick={() => toggleToken(token.address)} style={{
                    width: '100%', padding: '11px 14px', background: 'transparent', border: 'none',
                    cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10
                  }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#a855f7' }}>#{i+1}</span>
                    <span style={{ fontSize: 13, fontWeight: 700, color: '#fff', flex: 1, textAlign: 'left' }}>{token.ticker}</span>
                    <span style={{
                      fontSize: 11, padding: '2px 8px', borderRadius: 5,
                      background: preset ? preset.bg : 'rgba(255,255,255,0.06)',
                      color: preset ? preset.color : 'rgba(255,255,255,0.5)',
                      border: `1px solid ${preset ? preset.border : 'transparent'}`
                    }}>{s.minRoiMultiplier}x</span>
                    {expanded ? <ChevronUp size={14} color="rgba(255,255,255,0.3)" /> : <ChevronDown size={14} color="rgba(255,255,255,0.3)" />}
                  </button>

                  {expanded && (
                    <div style={{ padding: '0 14px 14px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 12, marginBottom: 10 }}>
                        {roiPresets.map(p => (
                          <button key={p.value} onClick={() => updatePerToken(token.address, 'minRoiMultiplier', p.value)} style={{
                            padding: '8px 10px', borderRadius: 7, border: `1px solid ${s.minRoiMultiplier === p.value ? p.border : 'rgba(255,255,255,0.08)'}`,
                            background: s.minRoiMultiplier === p.value ? p.bg : 'rgba(255,255,255,0.03)',
                            cursor: 'pointer', color: s.minRoiMultiplier === p.value ? p.color : 'rgba(255,255,255,0.5)',
                            fontSize: 13, fontWeight: 700
                          }}>{p.label}</button>
                        ))}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input type="range" min="1" max="50" step="0.5"
                          value={s.minRoiMultiplier}
                          onChange={e => updatePerToken(token.address, 'minRoiMultiplier', parseFloat(e.target.value))}
                          style={{ flex: 1, accentColor: '#a855f7' }}
                        />
                        <input type="number" min="1" max="50" step="0.5"
                          value={s.minRoiMultiplier}
                          onChange={e => updatePerToken(token.address, 'minRoiMultiplier', parseFloat(e.target.value)||1)}
                          style={{
                            width: 46, background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.12)',
                            borderRadius: 6, padding: '4px 6px', color: '#fff', fontSize: 12, textAlign: 'center', outline: 'none'
                          }}
                        />
                        <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>x</span>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  // ── PUMP WINDOW MODE ──────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Mode toggle */}
      <div style={{ display: 'flex', gap: 4, background: 'rgba(255,255,255,0.04)', borderRadius: 10, padding: 4 }}>
        {['global','per-token'].map(m => (
          <button key={m} onClick={() => setSettingsMode(m)} style={{
            flex: 1, padding: '7px 12px', borderRadius: 7, border: 'none', cursor: 'pointer',
            fontSize: 12, fontWeight: 600, transition: 'all 0.2s',
            background: settingsMode === m ? 'rgba(168,85,247,0.9)' : 'transparent',
            color: settingsMode === m ? '#fff' : 'rgba(255,255,255,0.45)',
          }}>
            {m === 'global' ? 'Global' : 'Per-Token'}
          </button>
        ))}
      </div>

      {settingsMode === 'global' && (
        <div style={{ 
          background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', 
          borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', gap: 14 
        }}>
          {/* Days Back + Candle Side by side */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,0.4)', display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                Days Back
              </label>
              <input type="number" value={globalSettings.daysBack}
                onChange={e => updateGlobal('daysBack', Math.max(1, Math.min(90, parseInt(e.target.value)||7)))}
                min="1" max="90"
                style={{
                  width: '100%', background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 8, padding: '9px 12px', color: '#fff', fontSize: 14, outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
            </div>
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,0.4)', display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                Candle Size
              </label>
              <select value={globalSettings.candleSize} onChange={e => updateGlobal('candleSize', e.target.value)}
                style={{
                  width: '100%', background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 8, padding: '9px 12px', color: '#fff', fontSize: 14, outline: 'none',
                  boxSizing: 'border-box'
                }}>
                {candleSizes.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>

          {/* Tweet window */}
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,0.4)', display: 'block', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
              Tweet Window (minutes)
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginBottom: 5 }}>T-minus (before)</div>
                <input type="number" value={globalSettings.tweetWindow.minus}
                  onChange={e => updateGlobalTweet('minus', e.target.value)}
                  min="0" max="120"
                  style={{
                    width: '100%', background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 8, padding: '9px 12px', color: '#fff', fontSize: 14, outline: 'none',
                    boxSizing: 'border-box'
                  }}
                />
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginBottom: 5 }}>T-plus (after)</div>
                <input type="number" value={globalSettings.tweetWindow.plus}
                  onChange={e => updateGlobalTweet('plus', e.target.value)}
                  min="0" max="60"
                  style={{
                    width: '100%', background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 8, padding: '9px 12px', color: '#fff', fontSize: 14, outline: 'none',
                    boxSizing: 'border-box'
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {settingsMode === 'per-token' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button onClick={applyGlobalToAll} style={{
              fontSize: 11, padding: '5px 10px', borderRadius: 6,
              background: 'rgba(168,85,247,0.12)', border: '1px solid rgba(168,85,247,0.25)',
              color: 'rgba(168,85,247,0.9)', cursor: 'pointer'
            }}>Apply global to all</button>
          </div>

          {selectedTokens.map((token, i) => {
            const s = perTokenSettings[token.address] || globalSettings;
            const expanded = expandedTokens[token.address];

            return (
              <div key={token.address} style={{
                background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 10, overflow: 'hidden'
              }}>
                <button onClick={() => toggleToken(token.address)} style={{
                  width: '100%', padding: '11px 14px', background: 'transparent', border: 'none',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10
                }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#a855f7' }}>#{i+1}</span>
                  <span style={{ flex: 1, fontSize: 13, fontWeight: 700, color: '#fff', textAlign: 'left' }}>{token.ticker}</span>
                  <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>{s.daysBack}d · {s.candleSize}</span>
                  {expanded ? <ChevronUp size={14} color="rgba(255,255,255,0.3)" /> : <ChevronDown size={14} color="rgba(255,255,255,0.3)" />}
                </button>

                {expanded && (
                  <div style={{ padding: '12px 14px 14px', borderTop: '1px solid rgba(255,255,255,0.06)', display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                      <div>
                        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginBottom: 5 }}>Days Back</div>
                        <input type="number" value={s.daysBack}
                          onChange={e => updatePerToken(token.address, 'daysBack', Math.max(1, Math.min(90, parseInt(e.target.value)||7)))}
                          min="1" max="90"
                          style={{ width: '100%', background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 7, padding: '7px 10px', color: '#fff', fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
                        />
                      </div>
                      <div>
                        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginBottom: 5 }}>Candle Size</div>
                        <select value={s.candleSize} onChange={e => updatePerToken(token.address, 'candleSize', e.target.value)}
                          style={{ width: '100%', background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 7, padding: '7px 10px', color: '#fff', fontSize: 13, outline: 'none', boxSizing: 'border-box' }}>
                          {candleSizes.map(cs => <option key={cs} value={cs}>{cs}</option>)}
                        </select>
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginBottom: 6 }}>Tweet Window</div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                        <input type="number" value={s.tweetWindow.minus}
                          onChange={e => updatePerTokenTweet(token.address, 'minus', e.target.value)}
                          placeholder="T-minus" min="0" max="120"
                          style={{ width: '100%', background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 7, padding: '7px 10px', color: '#fff', fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
                        />
                        <input type="number" value={s.tweetWindow.plus}
                          onChange={e => updatePerTokenTweet(token.address, 'plus', e.target.value)}
                          placeholder="T-plus" min="0" max="60"
                          style={{ width: '100%', background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 7, padding: '7px 10px', color: '#fff', fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}