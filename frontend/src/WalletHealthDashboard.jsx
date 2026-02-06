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

  const getHealthIcon = (status) => {
    switch (status) {
      case 'good': return <CheckCircle className="text-green-400" size={24} />;
      case 'warning': return <AlertCircle className="text-yellow-400" size={24} />;
      case 'critical': return <AlertCircle className="text-red-400" size={24} />;
      default: return <Activity className="text-gray-400" size={24} />;
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

  return (
    <div className="bg-gradient-to-br from-gray-900/50 to-gray-800/30 border border-white/10 rounded-2xl p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Activity className="text-purple-400" size={28} />
          <h2 className="text-xl font-bold">Watchlist Health Dashboard</h2>
        </div>
        
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors group"
            title="Refresh health data"
          >
            <RefreshCw className="text-gray-400 group-hover:text-white transition-colors" size={18} />
          </button>
        )}
      </div>

      {/* Overall Health Status */}
      <div className="mb-6 p-4 bg-white/5 border border-white/10 rounded-xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {getHealthIcon(health.overall)}
            <div>
              <div className="text-sm text-gray-400">Overall Health</div>
              <div className={`text-2xl font-bold ${getHealthColor(health.overall)}`}>
                🟢 {getHealthText(health.overall)}
              </div>
            </div>
          </div>
          
          <div className="text-right">
            <div className="text-3xl font-bold text-white">
              {health.healthy.length}/{wallets.length}
            </div>
            <div className="text-sm text-gray-400">wallets healthy</div>
          </div>
        </div>
      </div>

      {/* Wallets by Status */}
      <div className="space-y-4">
        
        {/* PERFORMING WELL */}
        {health.healthy.length > 0 && (
          <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <CheckCircle className="text-green-400" size={20} />
              <h3 className="font-bold text-green-400">
                🟢 PERFORMING WELL ({health.healthy.length})
              </h3>
            </div>
            
            <div className="space-y-2">
              {health.healthy.slice(0, 5).map((wallet) => (
                <div 
                  key={wallet.wallet_address || wallet.wallet}
                  className="flex items-center justify-between p-2 bg-black/20 rounded-lg hover:bg-black/30 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-purple-400 font-bold text-sm">
                      #{wallet.position}
                    </span>
                    <code className="text-sm font-mono text-gray-300">
                      {(wallet.wallet_address || wallet.wallet)?.slice(0, 8)}...
                    </code>
                    <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                      wallet.tier === 'S' ? 'bg-yellow-500/20 text-yellow-400' :
                      wallet.tier === 'A' ? 'bg-green-500/20 text-green-400' :
                      'bg-blue-500/20 text-blue-400'
                    }`}>
                      {wallet.tier}-Tier
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-4 text-xs">
                    <span className="text-green-400 font-bold">
                      {wallet.roi_30d || wallet.roi_percent || 0}% ROI
                    </span>
                    <span className="text-gray-400">
                      {wallet.runners_30d || wallet.runner_hits_30d || 0} runners
                    </span>
                    {onViewWallet && (
                      <button
                        onClick={() => onViewWallet(wallet)}
                        className="text-purple-400 hover:text-purple-300 transition-colors"
                      >
                        View →
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            
            {health.healthy.length > 5 && (
              <div className="mt-2 text-xs text-gray-500 text-center">
                +{health.healthy.length - 5} more performing well
              </div>
            )}
          </div>
        )}

        {/* MONITORING */}
        {health.monitoring.length > 0 && (
          <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <AlertCircle className="text-yellow-400" size={20} />
              <h3 className="font-bold text-yellow-400">
                🟡 MONITORING ({health.monitoring.length})
              </h3>
            </div>
            
            <div className="space-y-2">
              {health.monitoring.map((wallet) => {
                const alerts = wallet.degradation_alerts || [];
                const mainAlert = alerts[0] || {};
                
                return (
                  <div 
                    key={wallet.wallet_address || wallet.wallet}
                    className="bg-black/20 rounded-lg p-3"
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-3">
                        <span className="text-yellow-400 font-bold text-sm">
                          #{wallet.position}
                        </span>
                        <code className="text-sm font-mono text-gray-300">
                          {(wallet.wallet_address || wallet.wallet)?.slice(0, 8)}...
                        </code>
                        <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                          wallet.tier === 'A' ? 'bg-green-500/20 text-green-400' :
                          wallet.tier === 'B' ? 'bg-blue-500/20 text-blue-400' :
                          'bg-gray-500/20 text-gray-400'
                        }`}>
                          {wallet.tier}-Tier
                        </span>
                      </div>
                      
                      <div className="text-xs text-gray-400">
                        {wallet.roi_30d || wallet.roi_percent || 0}% ROI • {wallet.runners_30d || 0} runners
                      </div>
                    </div>
                    
                    {mainAlert.message && (
                      <div className="text-xs text-yellow-300 mb-2">
                        ⚠️ {mainAlert.message}
                      </div>
                    )}
                    
                    {onFindReplacements && (
                      <button
                        onClick={() => onFindReplacements(wallet.wallet_address || wallet.wallet)}
                        className="text-xs text-purple-400 hover:text-purple-300 transition-colors"
                      >
                        [VIEW REPLACEMENT OPTIONS]
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* CRITICAL / ACTION NEEDED */}
        {health.critical.length > 0 && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <AlertCircle className="text-red-400" size={20} />
              <h3 className="font-bold text-red-400">
                🔴 ACTION NEEDED ({health.critical.length})
              </h3>
            </div>
            
            <div className="space-y-3">
              {health.critical.map((wallet) => {
                const alerts = wallet.degradation_alerts || [];
                
                return (
                  <div 
                    key={wallet.wallet_address || wallet.wallet}
                    className="bg-black/20 rounded-lg p-3 border border-red-500/20"
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-3">
                        <span className="text-red-400 font-bold text-sm">
                          #{wallet.position}
                        </span>
                        <code className="text-sm font-mono text-gray-300">
                          {(wallet.wallet_address || wallet.wallet)?.slice(0, 8)}...
                        </code>
                        <span className="px-2 py-0.5 bg-gray-500/20 text-gray-400 rounded text-xs font-bold">
                          {wallet.tier}-Tier
                        </span>
                      </div>
                      
                      <div className="text-xs text-red-400 font-bold">
                        {wallet.roi_30d || wallet.roi_percent || 0}% ROI
                      </div>
                    </div>
                    
                    <div className="mb-3 space-y-1">
                      {alerts.map((alert, idx) => (
                        <div key={idx} className="text-xs text-red-300">
                          ❌ {alert.message || alert}
                        </div>
                      ))}
                    </div>
                    
                    {wallet.suggested_replacement && (
                      <div className="mb-2 p-2 bg-purple-500/10 border border-purple-500/30 rounded text-xs">
                        <span className="text-purple-400 font-semibold">💡 Suggested replacement: </span>
                        <code className="text-purple-300">
                          {wallet.suggested_replacement.slice(0, 12)}...
                        </code>
                      </div>
                    )}
                    
                    <div className="flex gap-2">
                      {onFindReplacements && (
                        <>
                          <button
                            onClick={() => onFindReplacements(wallet.wallet_address || wallet.wallet, true)}
                            className="flex-1 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-xs font-semibold transition-colors"
                          >
                            AUTO-REPLACE
                          </button>
                          <button
                            onClick={() => onFindReplacements(wallet.wallet_address || wallet.wallet, false)}
                            className="flex-1 px-3 py-1.5 bg-white/10 hover:bg-white/20 border border-white/10 rounded-lg text-xs font-semibold transition-colors"
                          >
                            CHOOSE MANUALLY
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Performance Comparison */}
      {stats && (
        <div className="mt-6 p-4 bg-white/5 border border-white/10 rounded-xl">
          <div className="text-sm text-gray-400 mb-2">📊 Performance vs 30 days ago:</div>
          
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-300">Your watchlist avg:</span>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-white">
                  {stats.avg_watchlist_roi || stats.avg_roi_30d || 0}%
                </span>
                {performance.trend === 'up' && (
                  <div className="flex items-center gap-1 text-green-400 text-xs">
                    <ArrowUpRight size={14} />
                    +{performance.change.toFixed(0)}%
                  </div>
                )}
                {performance.trend === 'down' && (
                  <div className="flex items-center gap-1 text-red-400 text-xs">
                    <ArrowDownRight size={14} />
                    -{performance.change.toFixed(0)}%
                  </div>
                )}
                {performance.trend === 'stable' && (
                  <div className="flex items-center gap-1 text-gray-400 text-xs">
                    <Minus size={14} />
                    stable
                  </div>
                )}
              </div>
            </div>
            
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-300">Platform avg:</span>
              <span className="text-lg font-bold text-gray-400">
                {stats.platform_avg_roi || 234}%
              </span>
            </div>
            
            {stats.performance_vs_platform && (
              <div className="pt-2 border-t border-white/10">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-400">You're outperforming by:</span>
                  <span className={`text-lg font-bold ${
                    stats.performance_vs_platform > 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {stats.performance_vs_platform > 0 ? '+' : ''}{stats.performance_vs_platform}% 🎯
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}