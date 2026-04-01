import useStore from '../src/store/useStore';

describe('useStore', () => {
  beforeEach(() => {
    useStore.setState({
      isConnected: false,
      walletAddress: null,
      activeTrades: [],
      tradeHistory: [],
      error: null,
    } as any);
  });

  test('initial state has no wallet connected', () => {
    const state = useStore.getState();
    expect((state as any).isConnected).toBe(false);
    expect((state as any).walletAddress).toBeNull();
  });

  test('setWallet updates connection state', () => {
    (useStore.getState() as any).setWallet('ABC123', 'secret');
    const state = useStore.getState();
    expect((state as any).isConnected).toBe(true);
    expect((state as any).walletAddress).toBe('ABC123');
  });

  test('disconnect clears wallet', () => {
    (useStore.getState() as any).setWallet('ABC123', 'secret');
    (useStore.getState() as any).disconnect();
    const state = useStore.getState();
    expect((state as any).isConnected).toBe(false);
    expect((state as any).walletAddress).toBeNull();
  });

  test('clearError resets error state', () => {
    useStore.setState({ error: 'test error' });
    useStore.getState().clearError();
    expect(useStore.getState().error).toBeNull();
  });

  test('updateSettings merges settings', () => {
    const initial = useStore.getState().settings;
    useStore.getState().updateSettings({ minBuyUSD: 200 } as any);
    expect((useStore.getState().settings as any).minBuyUSD).toBe(200);
  });
});
