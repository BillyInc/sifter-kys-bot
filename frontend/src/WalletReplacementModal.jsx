import React, { useState } from 'react';
import { 
  X, 
  ArrowRight, 
  TrendingUp, 
  Target, 
  Activity,
  CheckCircle,
  AlertCircle,
  Copy
} from 'lucide-react';

export default function WalletReplacementModal({ 
  currentWallet, 
  suggestions = [],
  onReplace,
  onDismiss 
}) {
  const [selectedReplacement, setSelectedReplacement] = useState(null);
  const [isReplacing, setIsReplacing] = useState(false);
  const [copied, setCopied] = useState(null);

  const handleCopy = (text, label) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleReplace = async () => {
    if (!selectedReplacement || !onReplace) return;
    
    setIsReplacing(true);
    
    try {
      await onReplace(selectedReplacement);
      // Modal will close from parent
    } catch (error) {
      console.error('Replace error:', error);
      alert('Failed to replace wallet');
    } finally {
      setIsReplacing(false);
    }
  };

  const formatPercent = (value) => {
    if (!value) return '0';
    return value > 0 ? `+${value.toFixed(0)}` : value.toFixed(0);
  };

  const getComparisonColor = (current, replacement) => {
    if (replacement > current) return 'text-green-400';
    if (replacement < current) return 'text-red-400';
    return 'text-gray-400';
  };

  return (
    <div 
      className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in"
      onClick={onDismiss}
    >
      <div 
        className="bg-gradient-to-br from-gray-900 to-gray-950 border border-white/10 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="bg-gradient-to-r from-purple-900/50 to-purple-800/30 border-b border-white/10 p-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold mb-1">🔄 Wallet Replacement</h2>
              <p className="text-sm text-gray-400">
                Choose a better-performing wallet to replace the declining one
              </p>
            </div>
            <button
              onClick={onDismiss}
              className="p-2 hover:bg-white/10 rounded-lg transition-colors"
            >
              <X size={24} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto max-h-[calc(90vh-200px)]">
          {/* Current Wallet (Declining) */}
          <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-xl">
            <div className="flex items-center gap-2 mb-3">
              <AlertCircle className="text-red-400" size={20} />
              <h3 className="font-bold text-red-400">Current Wallet (Declining)</h3>
            </div>
            
            <div className="grid grid-cols-4 gap-4">
              <div>
                <div className="text-xs text-gray-400 mb-1">Address</div>
                <div className="flex items-center gap-2">
                  <code className="text-sm font-mono text-gray-300">
                    {currentWallet?.wallet_address?.slice(0, 12)}...
                  </code>
                  <button
                    onClick={() => handleCopy(currentWallet?.wallet_address, 'current')}
                    className="p-1 hover:bg-white/10 rounded transition-colors"
                  >
                    {copied === 'current' ? (
                      <CheckCircle className="text-green-400" size={12} />
                    ) : (
                      <Copy className="text-gray-400" size={12} />
                    )}
                  </button>
                </div>
              </div>
              
              <div>
                <div className="text-xs text-gray-400 mb-1">Tier</div>
                <span className={`px-2 py-1 rounded text-sm font-bold ${
                  currentWallet?.tier === 'S' ? 'bg-yellow-500/20 text-yellow-400' :
                  currentWallet?.tier === 'A' ? 'bg-green-500/20 text-green-400' :
                  'bg-gray-500/20 text-gray-400'
                }`}>
                  {currentWallet?.tier}
                </span>
              </div>
              
              <div>
                <div className="text-xs text-gray-400 mb-1">Professional Score</div>
                <div className="text-lg font-bold text-red-400">
                  {currentWallet?.professional_score || currentWallet?.score || 0}
                </div>
              </div>
              
              <div>
                <div className="text-xs text-gray-400 mb-1">30d ROI</div>
                <div className="text-lg font-bold text-red-400">
                  {formatPercent(currentWallet?.roi_30d || 0)}%
                </div>
              </div>
            </div>

            {/* Issues */}
            {currentWallet?.degradation_alerts && currentWallet.degradation_alerts.length > 0 && (
              <div className="mt-3 pt-3 border-t border-red-500/30">
                <div className="text-xs font-semibold text-red-400 mb-2">Issues:</div>
                {currentWallet.degradation_alerts.map((alert, idx) => (
                  <div key={idx} className="text-xs text-red-300 mb-1">
                    ❌ {alert.message || alert}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Replacement Suggestions */}
          <div className="mb-6">
            <h3 className="font-bold text-lg mb-4 flex items-center gap-2">
              <TrendingUp className="text-green-400" size={20} />
              Recommended Replacements
            </h3>

            {suggestions.length === 0 ? (
              <div className="p-8 text-center bg-white/5 rounded-xl">
                <p className="text-gray-400">No replacement suggestions available</p>
              </div>
            ) : (
              <div className="space-y-3">
                {suggestions.map((suggestion, idx) => {
                  const isSelected = selectedReplacement?.wallet === suggestion.wallet;
                  
                  return (
                    <div
                      key={suggestion.wallet}
                      onClick={() => setSelectedReplacement(suggestion)}
                      className={`p-4 border rounded-xl cursor-pointer transition-all ${
                        isSelected 
                          ? 'bg-purple-500/20 border-purple-500/50 ring-2 ring-purple-500/30' 
                          : 'bg-white/5 border-white/10 hover:border-purple-500/30 hover:bg-white/10'
                      }`}
                    >
                      {/* Header */}
                      <div className="flex items-start justify-between mb-3">
                        <div className="flex items-center gap-3">
                          <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold ${
                            idx === 0 ? 'bg-yellow-500/20 text-yellow-400' :
                            idx === 1 ? 'bg-gray-400/20 text-gray-400' :
                            'bg-orange-500/20 text-orange-400'
                          }`}>
                            #{idx + 1}
                          </div>
                          
                          <div>
                            <div className="flex items-center gap-2 mb-1">
                              <code className="text-sm font-mono text-gray-300">
                                {suggestion.wallet?.slice(0, 16)}...
                              </code>
                              {idx === 0 && (
                                <span className="px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded text-xs font-bold">
                                  RECOMMENDED
                                </span>
                              )}
                            </div>
                            
                            <div className="flex items-center gap-2">
                              <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                                suggestion.tier === 'S' ? 'bg-yellow-500/20 text-yellow-400' :
                                'bg-green-500/20 text-green-400'
                              }`}>
                                {suggestion.tier}-Tier
                              </span>
                              
                              <span className="text-xs text-purple-400">
                                {(suggestion.similarity_score * 100).toFixed(0)}% similar
                              </span>
                            </div>
                          </div>
                        </div>

                        {isSelected && (
                          <CheckCircle className="text-purple-400" size={24} />
                        )}
                      </div>

                      {/* Comparison Stats */}
                      <div className="grid grid-cols-4 gap-3 mb-3">
                        <div className="bg-black/30 rounded p-2 text-center">
                          <div className={`text-lg font-bold ${
                            getComparisonColor(
                              currentWallet?.professional_score || 0,
                              suggestion.professional_score
                            )
                          }`}>
                            {suggestion.professional_score}
                          </div>
                          <div className="text-xs text-gray-400">Score</div>
                          <div className="text-xs text-green-400 font-semibold">
                            +{(suggestion.professional_score - (currentWallet?.professional_score || 0)).toFixed(0)}
                          </div>
                        </div>

                        <div className="bg-black/30 rounded p-2 text-center">
                          <div className="text-lg font-bold text-green-400">
                            {suggestion.runner_hits_30d || 0}
                          </div>
                          <div className="text-xs text-gray-400">Runners</div>
                          <div className="text-xs text-green-400 font-semibold">
                            +{(suggestion.runner_hits_30d || 0) - (currentWallet?.runners_30d || 0)}
                          </div>
                        </div>

                        <div className="bg-black/30 rounded p-2 text-center">
                          <div className="text-lg font-bold text-green-400">
                            {formatPercent(suggestion.roi_multiplier * 100 || suggestion.roi_30d)}%
                          </div>
                          <div className="text-xs text-gray-400">ROI</div>
                          <div className="text-xs text-green-400 font-semibold">
                            +{((suggestion.roi_multiplier * 100 || suggestion.roi_30d) - (currentWallet?.roi_30d || 0)).toFixed(0)}%
                          </div>
                        </div>

                        <div className="bg-black/30 rounded p-2 text-center">
                          <div className="text-lg font-bold text-purple-400">
                            {suggestion.professional_grade || 'N/A'}
                          </div>
                          <div className="text-xs text-gray-400">Grade</div>
                        </div>
                      </div>

                      {/* Why Better */}
                      {suggestion.why_better && suggestion.why_better.length > 0 && (
                        <div className="pt-3 border-t border-white/10">
                          <div className="text-xs font-semibold text-gray-400 mb-2">
                            Why this wallet is better:
                          </div>
                          <div className="space-y-1">
                            {suggestion.why_better.slice(0, 3).map((reason, ridx) => (
                              <div key={ridx} className="text-xs text-green-400">
                                ✓ {reason}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Estimated Impact */}
          {selectedReplacement && (
            <div className="p-4 bg-blue-500/10 border border-blue-500/30 rounded-xl">
              <div className="flex items-center gap-2 mb-3">
                <Target className="text-blue-400" size={18} />
                <h4 className="font-semibold text-blue-400">Estimated Impact</h4>
              </div>
              
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-400">Watchlist avg score:</span>
                  <span className="ml-2 text-white font-bold">
                    {currentWallet?.professional_score || 0} → {selectedReplacement.professional_score}
                  </span>
                  <span className="ml-1 text-green-400 text-xs">
                    (+{(selectedReplacement.professional_score - (currentWallet?.professional_score || 0)).toFixed(0)})
                  </span>
                </div>
                
                <div>
                  <span className="text-gray-400">Monthly runners:</span>
                  <span className="ml-2 text-white font-bold">
                    {currentWallet?.runners_30d || 0} → {selectedReplacement.runner_hits_30d || 0}
                  </span>
                  <span className="ml-1 text-green-400 text-xs">
                    (+{(selectedReplacement.runner_hits_30d || 0) - (currentWallet?.runners_30d || 0)})
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-white/10 p-4 bg-white/5 flex gap-3">
          <button
            onClick={onDismiss}
            className="flex-1 px-4 py-3 bg-white/10 hover:bg-white/20 rounded-lg font-semibold transition-colors"
          >
            Cancel
          </button>
          
          <button
            onClick={handleReplace}
            disabled={!selectedReplacement || isReplacing}
            className="flex-1 px-4 py-3 bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-700 hover:to-purple-600 disabled:from-purple-600/30 disabled:to-purple-500/30 rounded-lg font-semibold transition-all flex items-center justify-center gap-2"
          >
            {isReplacing ? (
              <>
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Replacing...
              </>
            ) : (
              <>
                <ArrowRight size={18} />
                Replace Wallet
              </>
            )}
          </button>
        </div>
      </div>

      <style jsx>{`
        @keyframes fade-in {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        @keyframes scale-in {
          from {
            opacity: 0;
            transform: scale(0.95);
          }
          to {
            opacity: 1;
            transform: scale(1);
          }
        }

        .animate-fade-in {
          animation: fade-in 0.2s ease-out;
        }

        .animate-scale-in {
          animation: scale-in 0.3s ease-out;
        }
      `}</style>
    </div>
  );
}