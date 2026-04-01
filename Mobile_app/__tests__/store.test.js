import useStore from '../src/store/useStore';

describe('useStore', () => {
  beforeEach(() => {
    useStore.setState({
      isConnected: false,
      walletAddress: null,
      activeTrades: [],
      tradeHistory: [],
      error: null,
    });
  });

  test('initial state has no wallet connected', () => {
    const state = useStore.getState();
    expect(state.isConnected).toBe(false);
    expect(state.walletAddress).toBeNull();
  });

  test('setWallet updates connection state', () => {
    useStore.getState().setWallet('ABC123', 'secret');
    const state = useStore.getState();
    expect(state.isConnected).toBe(true);
    expect(state.walletAddress).toBe('ABC123');
  });

  test('disconnect clears wallet', () => {
    useStore.getState().setWallet('ABC123', 'secret');
    useStore.getState().disconnect();
    const state = useStore.getState();
    expect(state.isConnected).toBe(false);
    expect(state.walletAddress).toBeNull();
  });

  test('clearError resets error state', () => {
    useStore.setState({ error: 'test error' });
    useStore.getState().clearError();
    expect(useStore.getState().error).toBeNull();
  });

  test('updateSettings merges settings', () => {
    const initial = useStore.getState().settings;
    useStore.getState().updateSettings({ minBuyUSD: 200 });
    expect(useStore.getState().settings.minBuyUSD).toBe(200);
  });
});
