import DatabaseService from '../database/DatabaseService';

class ExtremeCaseHandler {
  constructor() {
    this.baseSlippage = 0.15;
    this.baseGas = 0.00001;
    this.extremeThresholds = {
      volatility: 0.50,
      liquidityCrash: 0.3,
      networkCongestion: 0.9,
      multiWalletSignal: 3,
      timePressure: 30000
    };
    this.extremeMultipliers = {
      slippage: { max: 0.50, panic: 0.75 },
      gas:      { urgent: 0.0005, panic: 0.001 }
    };
  }

  async calculateExtremeSlippage(token, action, context) {
    const {
      walletCount = 1, isSell = false,
      priceChange1m = 0, networkCongestion = 0.3,
      liquidity = 100000, nextTPDistance = null
    } = context;

    let extremeScore = 0;
    let reasons = [];
    let slippage = this.baseSlippage;
    let gas = this.baseGas;

    // 1. Volatility
    if (priceChange1m > this.extremeThresholds.volatility) {
      extremeScore += 40;
      slippage = Math.max(slippage, 0.35);
      gas = Math.max(gas, this.extremeMultipliers.gas.urgent);
      reasons.push(`Volatility: ${(priceChange1m * 100).toFixed(0)}% in 1m`);
    }

    // 2. Liquidity crisis
    const liquidityChange = await this.getLiquidityChange(token);
    if (liquidityChange < this.extremeThresholds.liquidityCrash) {
      extremeScore += 50;
      slippage = Math.max(slippage, 0.40);
      gas = Math.max(gas, this.extremeMultipliers.gas.urgent);
      reasons.push(`💧 Liquidity crashed ${((1 - liquidityChange) * 100).toFixed(0)}%`);
      if (isSell && liquidity < 10000) {
        slippage = this.extremeMultipliers.slippage.panic;
        gas = this.extremeMultipliers.gas.panic;
        reasons.push('🔥 PANIC MODE: Critical liquidity');
      }
    }

    // 3. Network congestion
    if (networkCongestion > this.extremeThresholds.networkCongestion) {
      extremeScore += 30;
      gas = Math.max(gas, this.extremeMultipliers.gas.urgent);
      reasons.push(`🌐 Network congested (${(networkCongestion * 100).toFixed(0)}%)`);
      if (networkCongestion > 0.95) {
        gas = this.extremeMultipliers.gas.panic;
        slippage = Math.max(slippage, 0.30);
      }
    }

    // 4. Whale activity
    const whaleActivity = await this.detectWhaleActivity(token);
    if (whaleActivity.detected) {
      extremeScore += 35;
      slippage = Math.max(slippage, 0.35);
      gas = Math.max(gas, this.extremeMultipliers.gas.urgent);
      reasons.push(`🐋 Whale ${whaleActivity.type} $${whaleActivity.amount?.toFixed(0)}`);
    }

    // 5. Multi-wallet FOMO (buys)
    if (!isSell && walletCount >= this.extremeThresholds.multiWalletSignal) {
      extremeScore += 45;
      slippage = Math.max(slippage, walletCount >= 5 ? 0.40 : 0.30);
      gas = Math.max(gas, this.extremeMultipliers.gas.urgent);
      reasons.push(`👥 ${walletCount} wallets buying`);
    }

    // 6. Time pressure (near TP)
    if (isSell && nextTPDistance && nextTPDistance < this.extremeThresholds.timePressure) {
      extremeScore += 25;
      slippage = Math.max(slippage, 0.25);
      gas = Math.max(gas, this.extremeMultipliers.gas.urgent);
      reasons.push(`⏰ TP in ${Math.floor(nextTPDistance / 1000)}s`);
    }

    // 7. Snipers
    const snipers = await this.detectSnipers(token);
    if (snipers > 3) {
      extremeScore += 30;
      slippage = Math.max(slippage, 0.35);
      gas = Math.max(gas, this.extremeMultipliers.gas.urgent);
      reasons.push(`🎯 ${snipers} snipers detected`);
    }

    // 8. MEV risk
    const mevRisk = await this.calculateMEVRisk(token);
    if (mevRisk > 0.7) {
      extremeScore += 40;
      gas = Math.max(gas, this.extremeMultipliers.gas.urgent);
      slippage = Math.max(slippage, 0.30);
      reasons.push(`🕵️ MEV risk ${(mevRisk * 100).toFixed(0)}%`);
      if (mevRisk > 0.9) {
        gas = this.extremeMultipliers.gas.panic;
        slippage = this.extremeMultipliers.slippage.panic;
      }
    }

    const isPanic = reasons.some(r => r.includes('PANIC'));
    const finalGas = isPanic ? this.extremeMultipliers.gas.panic : gas;
    const finalSlippage = isSell
      ? Math.min(slippage, this.extremeMultipliers.slippage.panic)
      : Math.min(slippage, this.extremeMultipliers.slippage.max);

    return {
      slippage: Number(finalSlippage.toFixed(3)),
      gas: Number(finalGas.toFixed(8)),
      extremeScore: Math.min(100, extremeScore),
      reasons,
      isExtreme: extremeScore > 50,
      isPanic,
      recommendedAction: this.getRecommendedAction(extremeScore, isSell)
    };
  }

  getRecommendedAction(score, isSell) {
    if (score >= 80) return isSell ? 'SELL IMMEDIATELY - ANY PRICE' : 'BUY AGGRESSIVELY';
    if (score >= 60) return isSell ? 'SELL with high slippage' : 'BUY with urgency';
    if (score >= 40) return 'Proceed with caution';
    return 'Normal execution';
  }

  async getNetworkCongestion() {
    try {
      const apiKey = await DatabaseService.getSetting('api_key_helius');
      const response = await fetch(`https://api.helius.xyz/v0/priority-fee?api-key=${apiKey}`);
      const data = await response.json();
      return Math.min(1, (data.fee || 0) / 1000000);
    } catch { return 0.3; }
  }

  async getLiquidityChange(token) {
    try {
      const res = await fetch(`https://api.solana-tracker.io/tokens/${token}/liquidity`);
      const data = await res.json();
      return data.changePercent5m ? 1 + data.changePercent5m : 1.0;
    } catch { return 1.0; }
  }

  async detectWhaleActivity(token) {
    try {
      const res = await fetch(`https://api.solana-tracker.io/whales/${token}?minutes=5`);
      const data = await res.json();
      const largeTxs = (data.transactions || []).filter(tx => tx.usdValue > 10000);
      if (!largeTxs.length) return { detected: false };
      const buys = largeTxs.filter(t => t.type === 'buy');
      const sells = largeTxs.filter(t => t.type === 'sell');
      return {
        detected: true,
        type: buys.length > sells.length ? 'buying' : 'selling',
        amount: largeTxs.reduce((s, t) => s + t.usdValue, 0)
      };
    } catch { return { detected: false }; }
  }

  async detectSnipers(token) {
    try {
      const res = await fetch(`https://api.solana-tracker.io/snipers/${token}`);
      const data = await res.json();
      return data.count || 0;
    } catch { return 0; }
  }

  async calculateMEVRisk(token) {
    try {
      const apiKey = await DatabaseService.getSetting('api_key_helius');
      const res = await fetch(`https://api.helius.xyz/v0/mev/${token}?api-key=${apiKey}`);
      const data = await res.json();
      let risk = 0;
      if ((data.pendingTransactions || 0) > 10) risk += 0.3;
      if ((data.recentSandwiches || 0) > 5) risk += 0.4;
      if ((data.poolDepth || 100000) < 50000) risk += 0.3;
      return Math.min(1, risk);
    } catch { return 0.3; }
  }
}

export const extremeCaseHandler = new ExtremeCaseHandler();
export default extremeCaseHandler;
