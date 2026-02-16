import React, { useState } from 'react';
import { 
  ChevronDown, 
  ChevronUp, 
  ArrowUp,
  ArrowDown,
  Minus,
  Settings,
  ExternalLink,
  Copy,
  CheckCircle,
  Bell,
  BellOff,
  Filter
} from 'lucide-react';

export default function WalletLeagueTable({ 
  wallets = [], 
  promotionQueue = [],
  stats = {},
  onReplace,
  onExpand,
  onConfigure,
  onToggleTelegramAlert
}) {
  const [expandedWallets, setExpandedWallets] = useState({});
  const [copied, setCopied] = useState(null);
  const [filterTier, setFilterTier] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [sortBy, setSortBy] = useState('position');
  const [timeRange, setTimeRange] = useState('30d');

  const toggleExpand = (walletAddress) => {
    setExpandedWallets(prev => ({
      ...prev,
      [walletAddress]: !prev[walletAddress]
    }));
    
    if (onExpand) {
      onExpand(wallets.find(w => w.wallet_address === walletAddress));
    }
  };

  const handleCopy = (text, label) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(false), 2000);
  };

  const getZoneLabel = (position) => {
    if (position <= 3) return '🏆 Elite';
    if (position <= 6) return '📊 Mid-Table';
    if (position <= 8) return '⚠️ Monitoring';
    return '🔴 Relegation';
  };

  const getMovementIcon = (movement) => {
    if (!movement || movement === 'stable') return <Minus className="text-gray-400" size={14} />;
    if (movement === 'up') return <ArrowUp className="text-green-400" size={14} />;
    if (movement === 'down') return <ArrowDown className="text-red-400" size={14} />;
    return null;
  };

  const getPositionBadge = (position) => {
    if (position === 1) return '🥇';
    if (position === 2) return '🥈';
    if (position === 3) return '🥉';
    return position;
  };

  const renderFormCircles = (form) => {
    if (!form || !Array.isArray(form)) return null;
    
    return (
      <div className="flex gap-1">
        {form.slice(0, 5).map((action, idx) => {
          let color = 'bg-gray-500';
          if (action.type === 'win' || action.result === 'win') color = 'bg-green-500';
          else if (action.type === 'draw' || action.result === 'draw') color = 'bg-gray-400';
          else if (action.type === 'loss' || action.result === 'loss') color = 'bg-red-500';
          
          return (
            <div 
              key={idx} 
              className={`w-2.5 h-2.5 rounded-full ${color}`}
              title={action.token || action.description || `Action ${idx + 1}`}
            />
          );
        })}
      </div>
    );
  };

  // Filter and sort wallets
  const getFilteredWallets = () => {
    let filtered = [...wallets];

    // Apply tier filter
    if (filterTier !== 'all') {
      filtered = filtered.filter(w => w.tier === filterTier);
    }

    // Apply status filter
    if (filterStatus !== 'all') {
      filtered = filtered.filter(w => {
        if (filterStatus === 'healthy') return w.status === 'healthy' || !w.degradation_alerts || w.degradation_alerts.length === 0;
        if (filterStatus === 'warning') return w.status === 'warning';
        if (filterStatus === 'critical') return w.status === 'critical';
        return true;
      });
    }

    // Apply sorting
    if (sortBy === 'roi') {
      filtered.sort((a, b) => (b.roi_30d || 0) - (a.roi_30d || 0));
    } else if (sortBy === 'score') {
      filtered.sort((a, b) => (b.professional_score || b.score || 0) - (a.professional_score || a.score || 0));
    } else if (sortBy === 'runners') {
      filtered.sort((a, b) => (b.runners_30d || 0) - (a.runners_30d || 0));
    }
    // Default is position (already sorted)

    return filtered;
  };

  const filteredWallets = getFilteredWallets();

  // Group wallets by zone
  const groupedWallets = {
    champions: filteredWallets.filter(w => w.position <= 3),
    midtable: filteredWallets.filter(w => w.position > 3 && w.position <= 6),
    monitoring: filteredWallets.filter(w => w.position > 6 && w.position <= 8),
    relegation: filteredWallets.filter(w => w.position > 8)
  };

  const renderWalletRow = (wallet) => {
    const isExpanded = expandedWallets[wallet.wallet_address];
    const walletAddr = wallet.wallet_address || wallet.wallet;

    return (
      <React.Fragment key={walletAddr}>
        {/* Main Row - COMPACT DESIGN */}
        <tr 
          className={`border-b border-white/5 hover:bg-white/5 transition-colors ${
            wallet.status === 'critical' ? 'bg-red-500/5' :
            wallet.status === 'warning' ? 'bg-yellow-500/5' :
            ''
          }`}
        >
          {/* Position */}
          <td className="px-3 py-3 text-center">
            <span className="text-base font-bold text-purple-400">
              {getPositionBadge(wallet.position)}
            </span>
          </td>

          {/* Wallet Address - Clickable to expand */}
          <td 
            className="px-3 py-3 cursor-pointer"
            onClick={() => toggleExpand(walletAddr)}
          >
            <div className="flex items-center gap-2">
              <code className="text-sm font-mono text-gray-300">
                {walletAddr?.slice(0, 6)}...
              </code>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleCopy(walletAddr, walletAddr);
                }}
                className="p-1 hover:bg-white/10 rounded transition-colors"
              >
                {copied === walletAddr ? (
                  <CheckCircle className="text-green-400" size={10} />
                ) : (
                  <Copy className="text-gray-400" size={10} />
                )}
              </button>
            </div>
            {!isExpanded && (
              <button 
                className="text-xs text-gray-500 hover:text-purple-400 transition-colors mt-0.5 flex items-center gap-1"
              >
                [EXPAND <ChevronDown size={10} />]
              </button>
            )}
          </td>

          {/* Tier */}
          <td className="px-3 py-3 text-center">
            <span className={`px-2 py-0.5 rounded text-xs font-bold ${
              wallet.tier === 'S' ? 'bg-yellow-500/20 text-yellow-400' :
              wallet.tier === 'A' ? 'bg-green-500/20 text-green-400' :
              wallet.tier === 'B' ? 'bg-blue-500/20 text-blue-400' :
              'bg-gray-500/20 text-gray-400'
            }`}>
              {wallet.tier}
            </span>
          </td>

          {/* Score */}
          <td className="px-3 py-3 text-center">
            <span className="text-sm font-bold text-white">
              {wallet.professional_score || wallet.score || 0}
            </span>
          </td>

          {/* Form */}
          <td className="px-3 py-3">
            <div className="flex justify-center">
              {renderFormCircles(wallet.form)}
            </div>
          </td>

          {/* Runners */}
          <td className="px-3 py-3 text-center">
            <span className="text-sm font-semibold text-white">
              {wallet.runners_30d || wallet.runner_hits_30d || 0}
            </span>
          </td>

          {/* 30d ROI */}
          <td className="px-3 py-3 text-right">
            <span className={`text-sm font-bold ${
              (wallet.roi_30d || 0) > 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              {(wallet.roi_30d || 0) > 0 ? '+' : ''}{wallet.roi_30d || 0}%
            </span>
          </td>

          {/* Change */}
          <td className="px-3 py-3">
            <div className="flex items-center justify-center gap-1">
              {getMovementIcon(wallet.movement)}
              {wallet.positions_changed > 0 && (
                <span className={`text-xs font-semibold ${
                  wallet.movement === 'up' ? 'text-green-400' :
                  wallet.movement === 'down' ? 'text-red-400' :
                  'text-gray-400'
                }`}>
                  {wallet.positions_changed}
                </span>
              )}
            </div>
          </td>
        </tr>

        {/* Expanded Details Row */}
        {isExpanded && (
          <tr className="bg-black/30 border-b border-white/5">
            <td colSpan="8" className="px-4 py-4">
              <div className="space-y-4">
                {/* Full Address */}
                <div>
                  <div className="text-xs font-semibold text-gray-400 mb-1">
                    Full Address:
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="text-xs text-gray-300 font-mono">
                      {walletAddr}
                    </code>
                    <button
                      onClick={() => handleCopy(walletAddr, 'full')}
                      className="p-1 hover:bg-white/10 rounded transition-colors"
                    >
                      {copied === 'full' ? (
                        <CheckCircle className="text-green-400" size={12} />
                      ) : (
                        <Copy className="text-gray-400" size={12} />
                      )}
                    </button>
                    <a 
                      href={`https://solscan.io/account/${walletAddr}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 px-2 py-1 bg-white/10 hover:bg-white/20 rounded text-xs transition-colors"
                    >
                      <ExternalLink size={10} />
                      View on Solscan
                    </a>
                  </div>
                </div>

                {/* Performance Stats Grid */}
                <div>
                  <div className="text-xs font-semibold text-gray-400 mb-2">
                    Performance Overview:
                  </div>
                  <div className="grid grid-cols-4 gap-3">
                    <div className="bg-white/5 rounded p-2 text-center">
                      <div className="text-sm font-bold text-white">
                        {wallet.pump_count || 0}
                      </div>
                      <div className="text-xs text-gray-400">Pumps Hit</div>
                    </div>
                    <div className="bg-white/5 rounded p-2 text-center">
                      <div className="text-sm font-bold text-green-400">
                        {(wallet.avg_roi_to_peak_pct || wallet.avg_realized_roi_pct || 0).toLocaleString()}%
                      </div>
                      <div className="text-xs text-gray-400">Avg ROI</div>
                    </div>
                    <div className="bg-white/5 rounded p-2 text-center">
                      <div className="text-sm font-bold text-blue-400">
                        {(wallet.avg_distance_to_ath_pct || 0).toFixed(2)}%
                      </div>
                      <div className="text-xs text-gray-400">Dist to ATH</div>
                    </div>
                    <div className="bg-white/5 rounded p-2 text-center">
                      <div className="text-sm font-bold text-purple-400">
                        {wallet.consistency_score?.toFixed(1) || 'N/A'}
                      </div>
                      <div className="text-xs text-gray-400">Consistency</div>
                    </div>
                  </div>
                </div>

                {/* Form Guide (Last 5 Actions) */}
                {wallet.form && wallet.form.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-gray-400 mb-2">
                      Form Guide (Last 5 Actions):
                    </div>
                    <div className="space-y-1">
                      {wallet.form.slice(0, 5).map((action, idx) => {
                        const isWin = action.type === 'win' || action.result === 'win';
                        const isDraw = action.type === 'draw' || action.result === 'draw';
                        
                        return (
                          <div key={idx} className="flex items-center gap-2 text-xs">
                            <span className={`w-3 h-3 rounded-full ${
                              isWin ? 'bg-green-500' : 
                              isDraw ? 'bg-gray-400' : 
                              'bg-red-500'
                            }`} />
                            <span className="text-gray-400">{action.time || `${idx + 1}d ago`}</span>
                            <span className="text-gray-300">{action.description || action.token || 'Trade'}</span>
                            {action.roi && (
                              <span className={isWin ? 'text-green-400' : 'text-red-400'}>
                                {action.roi}
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Recent Runners */}
                {wallet.other_runners && wallet.other_runners.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-gray-400 mb-2">
                      Recent Runners (Last 30 Days):
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      {wallet.other_runners.slice(0, 5).map((runner, idx) => (
                        <div key={idx} className="bg-white/5 rounded p-2">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-sm font-semibold text-yellow-400">
                              ${runner.symbol}
                            </span>
                            <span className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded">
                              {runner.multiplier}x
                            </span>
                          </div>
                          <div className="text-xs text-gray-400">
                            ROI: {runner.roi_multiplier}x
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Alert Settings Section */}
                <div className="pt-3 border-t border-white/10">
                  <div className="text-xs font-semibold text-gray-400 mb-2">
                    Alert Settings:
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => onToggleTelegramAlert && onToggleTelegramAlert(wallet)}
                          className={`p-2 rounded transition-colors ${
                            wallet.telegram_enabled 
                              ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' 
                              : 'bg-gray-500/20 text-gray-400 hover:bg-gray-500/30'
                          }`}
                        >
                          {wallet.telegram_enabled ? <Bell size={14} /> : <BellOff size={14} />}
                        </button>
                        <span className="text-xs text-gray-400">
                          Telegram: {wallet.telegram_enabled ? 'ON' : 'OFF'}
                        </span>
                      </div>
                      
                      {wallet.telegram_enabled && (
                        <div className="text-xs text-gray-500">
                          Min trade: ${wallet.min_trade_usd || 100}
                        </div>
                      )}
                    </div>

                    <button
                      onClick={() => onConfigure && onConfigure(wallet)}
                      className="flex items-center gap-1 px-3 py-1.5 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 rounded text-xs font-medium transition-colors"
                    >
                      <Settings size={12} />
                      Configure Alerts
                    </button>
                  </div>
                </div>

                {/* Degradation Alerts */}
                {wallet.degradation_alerts && wallet.degradation_alerts.length > 0 && (
                  <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded">
                    <div className="text-xs font-semibold text-yellow-400 mb-2">
                      ⚠️ Performance Alerts:
                    </div>
                    {wallet.degradation_alerts.map((alert, idx) => (
                      <div key={idx} className="text-xs text-yellow-300 mb-1">
                        • {alert.message || alert}
                      </div>
                    ))}
                    
                    {onReplace && (
                      <button
                        onClick={() => onReplace(wallet, null)}
                        className="mt-2 w-full px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded text-xs font-semibold transition-colors"
                      >
                        VIEW REPLACEMENTS
                      </button>
                    )}
                  </div>
                )}

                {/* Collapse Button */}
                <div className="flex justify-center pt-2">
                  <button
                    onClick={() => toggleExpand(walletAddr)}
                    className="text-xs text-gray-500 hover:text-purple-400 transition-colors flex items-center gap-1"
                  >
                    [COLLAPSE <ChevronUp size={10} />]
                  </button>
                </div>
              </div>
            </td>
          </tr>
        )}
      </React.Fragment>
    );
  };

  return (
    <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
      {/* Table Header */}
      <div className="bg-gradient-to-r from-purple-900/50 to-purple-800/30 border-b border-white/10 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold flex items-center gap-2">
            📊 YOUR SMART MONEY WATCHLIST
          </h2>
          <div className="text-sm text-gray-400">
            Last Updated: {new Date().toLocaleTimeString()}
          </div>
        </div>
      </div>

      {/* Filter & Sort Bar */}
      <div className="bg-gradient-to-r from-purple-900/20 to-purple-800/10 border-b border-white/10 p-4">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Filter size={16} className="text-purple-400" />
            <span className="text-sm font-semibold text-purple-300">Filter & Sort:</span>
          </div>
          
          <select 
            value={filterTier}
            onChange={(e) => setFilterTier(e.target.value)}
            className="px-4 py-2 bg-gray-900/80 border border-purple-500/30 rounded-lg text-sm text-white font-medium hover:bg-gray-900 hover:border-purple-500/50 transition-all cursor-pointer focus:outline-none focus:ring-2 focus:ring-purple-500/50 backdrop-blur-sm"
          >
            <option value="all" className="bg-gray-900">All Tiers</option>
            <option value="S" className="bg-gray-900">S-Tier</option>
            <option value="A" className="bg-gray-900">A-Tier</option>
            <option value="B" className="bg-gray-900">B-Tier</option>
            <option value="C" className="bg-gray-900">C-Tier</option>
          </select>

          <select 
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="px-4 py-2 bg-gray-900/80 border border-purple-500/30 rounded-lg text-sm text-white font-medium hover:bg-gray-900 hover:border-purple-500/50 transition-all cursor-pointer focus:outline-none focus:ring-2 focus:ring-purple-500/50 backdrop-blur-sm"
          >
            <option value="all" className="bg-gray-900">All Status</option>
            <option value="healthy" className="bg-gray-900">Healthy</option>
            <option value="warning" className="bg-gray-900">Warning</option>
            <option value="critical" className="bg-gray-900">Critical</option>
          </select>

          <select 
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="px-4 py-2 bg-gray-900/80 border border-purple-500/30 rounded-lg text-sm text-white font-medium hover:bg-gray-900 hover:border-purple-500/50 transition-all cursor-pointer focus:outline-none focus:ring-2 focus:ring-purple-500/50 backdrop-blur-sm"
          >
            <option value="position" className="bg-gray-900">Sort: Position</option>
            <option value="roi" className="bg-gray-900">Sort: ROI</option>
            <option value="score" className="bg-gray-900">Sort: Score</option>
            <option value="runners" className="bg-gray-900">Sort: Runners</option>
          </select>

          <select 
            value={timeRange}
            onChange={(e) => setTimeRange(e.target.value)}
            className="px-4 py-2 bg-gray-900/80 border border-purple-500/30 rounded-lg text-sm text-white font-medium hover:bg-gray-900 hover:border-purple-500/50 transition-all cursor-pointer focus:outline-none focus:ring-2 focus:ring-purple-500/50 backdrop-blur-sm"
          >
            <option value="7d" className="bg-gray-900">Last 7 Days</option>
            <option value="30d" className="bg-gray-900">Last 30 Days</option>
            <option value="60d" className="bg-gray-900">Last 60 Days</option>
            <option value="90d" className="bg-gray-900">Last 90 Days</option>
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-900/50 border-b border-white/10 sticky top-0">
            <tr>
              <th className="px-3 py-3 text-center text-xs font-semibold text-gray-300 uppercase">#</th>
              <th className="px-3 py-3 text-left text-xs font-semibold text-gray-300 uppercase">Wallet</th>
              <th className="px-3 py-3 text-center text-xs font-semibold text-gray-300 uppercase">Tier</th>
              <th className="px-3 py-3 text-center text-xs font-semibold text-gray-300 uppercase">Score</th>
              <th className="px-3 py-3 text-center text-xs font-semibold text-gray-300 uppercase">Form</th>
              <th className="px-3 py-3 text-center text-xs font-semibold text-gray-300 uppercase">Runners</th>
              <th className="px-3 py-3 text-right text-xs font-semibold text-gray-300 uppercase">30d ROI</th>
              <th className="px-3 py-3 text-center text-xs font-semibold text-gray-300 uppercase">Change</th>
            </tr>
          </thead>

          <tbody>
            {/* Champions League Zone */}
            {groupedWallets.champions.length > 0 && (
              <>
                <tr className="bg-green-500/5">
                  <td colSpan="8" className="px-3 py-2 text-xs font-semibold text-green-400 border-y border-green-500/30">
                    {getZoneLabel(1)}
                  </td>
                </tr>
                {groupedWallets.champions.map((wallet) => renderWalletRow(wallet))}
              </>
            )}

            {/* Mid-Table */}
            {groupedWallets.midtable.length > 0 && (
              <>
                <tr className="bg-white/5">
                  <td colSpan="8" className="px-3 py-2 text-xs font-semibold text-gray-400 border-y border-white/10">
                    {getZoneLabel(4)}
                  </td>
                </tr>
                {groupedWallets.midtable.map((wallet) => renderWalletRow(wallet))}
              </>
            )}

            {/* Monitoring Zone */}
            {groupedWallets.monitoring.length > 0 && (
              <>
                <tr className="bg-yellow-500/5">
                  <td colSpan="8" className="px-3 py-2 text-xs font-semibold text-yellow-400 border-y border-yellow-500/30">
                    {getZoneLabel(7)}
                  </td>
                </tr>
                {groupedWallets.monitoring.map((wallet) => renderWalletRow(wallet))}
              </>
            )}

            {/* Relegation Zone */}
            {groupedWallets.relegation.length > 0 && (
              <>
                <tr className="bg-red-500/5">
                  <td colSpan="8" className="px-3 py-2 text-xs font-semibold text-red-400 border-y border-red-500/30">
                    {getZoneLabel(9)}
                  </td>
                </tr>
                {groupedWallets.relegation.map((wallet) => renderWalletRow(wallet))}
              </>
            )}
          </tbody>
        </table>
      </div>

      {/* Promotion Queue */}
      {promotionQueue && promotionQueue.length > 0 && (
        <div className="border-t border-white/10 p-4 bg-purple-500/5">
          <div className="text-sm font-semibold text-purple-400 mb-3">
            💡 PROMOTION QUEUE (Next in line for your watchlist)
          </div>
          
          <div className="space-y-2">
            {promotionQueue.slice(0, 3).map((candidate, idx) => (
              <div 
                key={candidate.wallet || candidate.wallet_address}
                className="flex items-center justify-between p-3 bg-black/20 rounded-lg border border-purple-500/20"
              >
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-500">#{idx + 1}</span>
                  <code className="text-sm font-mono text-purple-300">
                    {(candidate.wallet || candidate.wallet_address)?.slice(0, 12)}...
                  </code>
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                    candidate.tier === 'S' ? 'bg-yellow-500/20 text-yellow-400' :
                    'bg-green-500/20 text-green-400'
                  }`}>
                    {candidate.tier}
                  </span>
                  <span className="text-xs text-gray-400">
                    Score: {candidate.professional_score || candidate.score}
                  </span>
                </div>
                
                <div className="flex items-center gap-4">
                  <span className="text-sm">
                    <span className="text-green-400 font-bold">
                      {candidate.roi_multiplier ? `${(candidate.roi_multiplier * 100).toFixed(0)}%` : 
                       candidate.roi_30d ? `${candidate.roi_30d}%` : 'N/A'}
                    </span>
                    <span className="text-gray-500 text-xs ml-1">ROI</span>
                  </span>
                  
                  <button
                    onClick={() => onReplace && onReplace(null, candidate)}
                    className="px-3 py-1 bg-purple-600 hover:bg-purple-700 rounded text-xs font-semibold transition-colors"
                  >
                    ADD NOW
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}