import React from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  AlertCircle, 
  CheckCircle, 
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  RefreshCw
} from 'lucide-react';

export default function WalletHealthDashboard({ 
  wallets = [], 
  stats = null,
  onViewWallet,
  onFindReplacements,
  onRefresh 
}) {
  
  // Calculate health metrics
  const calculateHealth = () => {
    if (!wallets || wallets.length === 0) {
      return {
        overall: 'unknown',
        healthy: [],
        monitoring: [],
        critical: []
      };
    }

    const healthy = wallets.filter(w => 
      w.status === 'healthy' || 
      (!w.degradation_alerts || w.degradation_alerts.length === 0)
    );
    
    const monitoring = wallets.filter(w => 
      w.status === 'warning' || 
      (w.degradation_alerts && w.degradation_alerts.some(a => a.severity === 'yellow' || a.severity === 'orange'))
    );
    
    const critical = wallets.filter(w => 
      w.status === 'critical' || 
      (w.degradation_alerts && w.degradation_alerts.some(a => a.severity === 'red'))
    );

    // Determine overall health
    let overall = 'good';
    if (critical.length > 0) {
      overall = 'critical';
    } else if (monitoring.length > 2 || monitoring.length / wallets.length > 0.3) {
      overall = 'warning';
    }

    return { overall, healthy, monitoring, critical };
  };

  const health = calculateHealth();

  // Calculate performance comparison
  const getPerformanceComparison = () => {
    if (!stats || !stats.avg_roi_30d || !stats.avg_roi_60d) {
      return { change: 0, trend: 'stable' };
    }

    const change = ((stats.avg_roi_30d - stats.avg_roi_60d) / Math.abs(stats.avg_roi_60d)) * 100;
    
    let trend = 'stable';
    if (change > 10) trend = 'up';
    else if (change < -10) trend = 'down';

    return { change: Math.abs(change), trend };
  };

  const performance = getPerformanceComparison();

  const getHealthColor = (status) => {
    switch (status) {
      case 'good': return 'text-green-400';
      case 'warning': return 'text-yellow-400';
      case 'critical': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  const getHealthText = (status) => {
    switch (status) {
      case 'good': return 'GOOD';
      case 'warning': return 'WARNING';
      case 'critical': return 'CRITICAL';
      default: return 'UNKNOWN';
    }
  };

  const getHealthEmoji = (status) => {
    switch (status) {
      case 'good': return '🟢';
      case 'warning': return '🟡';
      case 'critical': return '🔴';
      default: return '⚪';
    }
  };

  return (
    <div className="bg-gradient-to-br from-gray-900/50 to-gray-800/30 border border-white/10 rounded-xl p-4">
      {/* Compact Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Activity className="text-purple-400" size={18} />
          <h2 className="text-base font-bold">Watchlist Health</h2>
        </div>
        
        <div className="flex items-center gap-3">
          <span className="text-base">{getHealthEmoji(health.overall)}</span>
          <div className={`text-sm font-bold ${getHealthColor(health.overall)}`}>
            {getHealthText(health.overall)}
          </div>
          <div className="text-sm text-gray-400">
            {health.healthy.length}/{wallets.length}
          </div>
          {onRefresh && (
            <button
              onClick={onRefresh}
              className="p-1 hover:bg-white/10 rounded transition-colors"
              title="Refresh"
            >
              <RefreshCw className="text-gray-400 hover:text-white" size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Wallets by Status - Compact */}
      <div className="space-y-3">
        
        {/* CRITICAL - Show First */}
        {health.critical.length > 0 && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className="text-red-400" size={16} />
              <h3 className="text-xs font-bold text-red-400">
                ACTION NEEDED ({health.critical.length})
              </h3>
            </div>
            
            <div className="space-y-2">
              {health.critical.map((wallet) => {
                const alerts = wallet.degradation_alerts || [];
                
                return (
                  <div 
                    key={wallet.wallet_address || wallet.wallet}
                    className="bg-black/20 rounded p-2 border border-red-500/20"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className="text-red-400 font-bold text-xs">#{wallet.position}</span>
                        <code className="text-xs font-mono text-gray-300">
                          {(wallet.wallet_address || wallet.wallet)?.slice(0, 6)}...
                        </code>
                        <span className="px-1.5 py-0.5 bg-gray-500/20 text-gray-400 rounded text-xs">
                          {wallet.tier}
                        </span>
                      </div>
                      <span className="text-xs text-red-400 font-bold">
                        {wallet.roi_30d || wallet.roi_percent || 0}%
                      </span>
                    </div>
                    
                    {alerts[0] && (
                      <div className="text-xs text-red-300 mb-2">
                        ❌ {alerts[0].message || alerts[0]}
                      </div>
                    )}
                    
                    {onFindReplacements && (
                      <div className="flex gap-2">
                        <button
                          onClick={() => onFindReplacements(wallet.wallet_address || wallet.wallet, true)}
                          className="flex-1 px-2 py-1 bg-purple-600 hover:bg-purple-700 rounded text-xs font-semibold"
                        >
                          AUTO-REPLACE
                        </button>
                        <button
                          onClick={() => onFindReplacements(wallet.wallet_address || wallet.wallet, false)}
                          className="flex-1 px-2 py-1 bg-white/10 hover:bg-white/20 rounded text-xs"
                        >
                          CHOOSE
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* MONITORING */}
        {health.monitoring.length > 0 && (
          <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <AlertCircle className="text-yellow-400" size={16} />
                <h3 className="text-xs font-bold text-yellow-400">
                  MONITORING ({health.monitoring.length})
                </h3>
              </div>
            </div>
            
            <div className="space-y-1.5">
              {health.monitoring.slice(0, 3).map((wallet) => {
                const alerts = wallet.degradation_alerts || [];
                
                return (
                  <div 
                    key={wallet.wallet_address || wallet.wallet}
                    className="bg-black/20 rounded p-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-yellow-400 font-bold text-xs">#{wallet.position}</span>
                        <code className="text-xs font-mono text-gray-300">
                          {(wallet.wallet_address || wallet.wallet)?.slice(0, 6)}...
                        </code>
                        <span className="px-1.5 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs">
                          {wallet.tier}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400">
                          {wallet.roi_30d || wallet.roi_percent || 0}%
                        </span>
                        {onViewWallet && (
                          <button
                            onClick={() => onViewWallet(wallet)}
                            className="text-xs text-purple-400 hover:text-purple-300"
                          >
                            →
                          </button>
                        )}
                      </div>
                    </div>
                    {alerts[0]?.message && (
                      <div className="text-xs text-yellow-300 mt-1">
                        ⚠️ {alerts[0].message}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            
            {health.monitoring.length > 3 && (
              <div className="mt-1 text-xs text-gray-500 text-center">
                +{health.monitoring.length - 3} more
              </div>
            )}
          </div>
        )}

        {/* PERFORMING WELL - Collapsed */}
        {health.healthy.length > 0 && (
          <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CheckCircle className="text-green-400" size={16} />
                <h3 className="text-xs font-bold text-green-400">
                  PERFORMING WELL ({health.healthy.length})
                </h3>
              </div>
              <div className="text-xs text-gray-400">
                Avg {(health.healthy.reduce((sum, w) => sum + (w.roi_30d || w.roi_percent || 0), 0) / health.healthy.length).toFixed(0)}% ROI
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Compact Performance */}
      {stats && (
        <div className="mt-3 space-y-3">
          {/* Performance Comparison */}
          <div className="p-3 bg-white/5 border border-white/10 rounded-lg">
            <div className="flex items-center justify-between text-xs mb-2">
              <span className="text-gray-400">Your avg:</span>
              <div className="flex items-center gap-2">
                <span className="font-bold text-white">
                  {stats.avg_watchlist_roi || stats.avg_roi_30d || 0}%
                </span>
                {performance.trend === 'up' && (
                  <span className="text-green-400">
                    <ArrowUpRight size={12} className="inline" /> +{performance.change.toFixed(0)}%
                  </span>
                )}
                {performance.trend === 'down' && (
                  <span className="text-red-400">
                    <ArrowDownRight size={12} className="inline" /> -{performance.change.toFixed(0)}%
                  </span>
                )}
              </div>
            </div>
            
            {stats.platform_avg_roi && (
              <div className="flex items-center justify-between text-xs pt-2 border-t border-white/10">
                <span className="text-gray-400">vs Platform:</span>
                <span className={`font-bold ${
                  (stats.avg_watchlist_roi || stats.avg_roi_30d || 0) > stats.platform_avg_roi 
                    ? 'text-green-400' 
                    : 'text-red-400'
                }`}>
                  {stats.performance_vs_platform > 0 ? '+' : ''}{stats.performance_vs_platform}% 🎯
                </span>
              </div>
            )}
          </div>

          {/* Quick Stats Grid */}
          <div className="p-3 bg-gradient-to-r from-purple-900/20 to-purple-800/10 border border-purple-500/30 rounded-lg">
            <div className="text-xs font-semibold text-purple-300 mb-2">📊 Quick Stats</div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <div className="text-lg font-bold text-green-400">
                  {health.healthy.length}
                </div>
                <div className="text-xs text-gray-400">Healthy</div>
              </div>
              <div>
                <div className="text-lg font-bold text-yellow-400">
                  {health.monitoring.length}
                </div>
                <div className="text-xs text-gray-400">Monitoring</div>
              </div>
              <div>
                <div className="text-lg font-bold text-red-400">
                  {health.critical.length}
                </div>
                <div className="text-xs text-gray-400">Critical</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}