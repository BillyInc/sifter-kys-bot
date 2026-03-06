class PositionSizeManager {
  constructor(portfolioTotal) {
    this.portfolioTotal = portfolioTotal;
    this.maxPositionSize = portfolioTotal * 0.40; // Hard cap per token
    this.positions = new Map(); // token -> current size
  }

  calculatePosition(signal) {
    const { walletCount, token } = signal;
    const existing = this.positions.get(token) || 0;
    const tradingBalance = this.portfolioTotal * 0.10;
    let newSize = 0;

    if (walletCount >= 3) {
      newSize = this.portfolioTotal * 0.40;
    } else if (walletCount === 2) {
      newSize = existing === 0 ? tradingBalance : tradingBalance * 0.70;
    } else {
      newSize = existing === 0 ? tradingBalance * 0.30 : tradingBalance * 0.70;
    }

    // Cap at max position size
    const total = existing + newSize;
    if (total > this.maxPositionSize) {
      newSize = Math.max(0, this.maxPositionSize - existing);
    }

    // Cap at total portfolio exposure
    if (this.getTotalExposure() + newSize > this.portfolioTotal) {
      console.log('⚠️ Would exceed total exposure — blocking');
      return 0;
    }

    return newSize;
  }

  getTotalExposure() {
    let total = 0;
    for (const size of this.positions.values()) total += size;
    return total;
  }

  updatePosition(token, size) { this.positions.set(token, size); }
  closePosition(token) { this.positions.delete(token); }
}

export default PositionSizeManager;
