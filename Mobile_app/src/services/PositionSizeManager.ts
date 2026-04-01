import AsyncStorage from '@react-native-async-storage/async-storage';

const POSITIONS_KEY = 'kys_positions';

interface Signal {
  walletCount: number;
  token: string;
  [key: string]: any;
}

class PositionSizeManager {
  portfolioTotal: number;
  maxPositionSize: number;
  positions: Map<string, number>;

  constructor(portfolioTotal: number = 10000) {
    this.portfolioTotal = portfolioTotal;
    this.maxPositionSize = portfolioTotal * 0.40; // Hard cap per token
    this.positions = new Map(); // token -> current size
    this.loadPositions();
  }

  async loadPositions(): Promise<void> {
    try {
      const saved = await AsyncStorage.getItem(POSITIONS_KEY);
      if (saved) this.positions = new Map(JSON.parse(saved));
    } catch {}
  }

  async savePositions(): Promise<void> {
    try {
      await AsyncStorage.setItem(POSITIONS_KEY, JSON.stringify([...this.positions]));
    } catch {}
  }

  calculatePosition(signal: Signal): number {
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

  getTotalExposure(): number {
    let total = 0;
    for (const size of this.positions.values()) total += size;
    return total;
  }

  updatePosition(token: string, size: number): void { this.positions.set(token, size); this.savePositions(); }
  closePosition(token: string): void { this.positions.delete(token); this.savePositions(); }
}

export default PositionSizeManager;
