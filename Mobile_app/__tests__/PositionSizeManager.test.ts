jest.mock('@react-native-async-storage/async-storage', () => ({
  getItem: jest.fn(() => Promise.resolve(null)),
  setItem: jest.fn(() => Promise.resolve()),
}));

import PositionSizeManager from '../src/services/PositionSizeManager';

describe('PositionSizeManager', () => {
  let manager: PositionSizeManager;

  beforeEach(() => {
    manager = new PositionSizeManager();
    manager.positions = new Map();
    (manager as any).portfolioSize = 10000;
    (manager as any).tradingBalance = 5000;
  });

  test('calculates position size for single wallet signal', () => {
    const size = (manager as any).calculateSize({
      token: 'TOKEN1',
      wallets: ['wallet1'],
      strength: 'normal',
    });
    // First signal from 1 wallet = 30% of trading balance
    expect(size).toBeLessThanOrEqual((manager as any).tradingBalance * 0.4);
    expect(size).toBeGreaterThan(0);
  });

  test('position tracking records correctly', () => {
    manager.updatePosition('TOKEN1', 1000);
    expect(manager.positions.has('TOKEN1')).toBe(true);
    expect(manager.positions.get('TOKEN1')).toBe(1000);
  });

  test('close position removes tracking', () => {
    manager.updatePosition('TOKEN1', 1000);
    manager.closePosition('TOKEN1');
    expect(manager.positions.has('TOKEN1')).toBe(false);
  });

  test('never exceeds 40% per token', () => {
    // Even with multiple signals, should cap
    manager.updatePosition('TOKEN1', 3000);
    const remaining = (manager as any).calculateSize({
      token: 'TOKEN1',
      wallets: ['w1', 'w2', 'w3'],
      strength: 'mega',
    });
    const total = 3000 + remaining;
    expect(total).toBeLessThanOrEqual((manager as any).portfolioSize * 0.4);
  });
});
