import { by, device, element, expect } from 'detox';

describe('Wallet Connection Flow', () => {
  beforeAll(async () => {
    await device.launchApp({ newInstance: true });
  });

  afterAll(async () => {
    await device.terminateApp();
  });

  it('should navigate to Settings then ConnectWallet screen', async () => {
    // Go to Settings tab
    await element(by.id('tab-settings')).tap();
    await expect(element(by.id('settings-screen'))).toBeVisible();

    // Tap the Connect Wallet button
    await element(by.id('settings-connect-wallet-btn')).tap();
    await expect(element(by.id('connect-wallet-screen'))).toBeVisible();
  });

  it('should display the Connect Wallet screen header', async () => {
    await expect(element(by.id('connect-wallet-title'))).toBeVisible();
    await expect(element(by.text('Connect Wallet'))).toBeVisible();
  });

  it('should show the primary wallet adapter connect button', async () => {
    await expect(element(by.id('wallet-adapter-connect-btn'))).toBeVisible();
  });

  it('should show the advanced import toggle', async () => {
    await expect(element(by.id('advanced-toggle-btn'))).toBeVisible();
  });

  it('should expand advanced section when toggled', async () => {
    await element(by.id('advanced-toggle-btn')).tap();

    // Import and Create tabs should appear
    await expect(element(by.id('tab-import'))).toBeVisible();
    await expect(element(by.id('tab-create'))).toBeVisible();
  });

  it('should show the private key input when Import tab is active', async () => {
    await element(by.id('tab-import')).tap();
    await expect(element(by.id('private-key-input'))).toBeVisible();
    await expect(element(by.id('import-wallet-btn'))).toBeVisible();
  });

  it('should show the Generate button when Create tab is active', async () => {
    await element(by.id('tab-create')).tap();
    await expect(element(by.id('generate-wallet-btn'))).toBeVisible();
  });

  it('should show the security note', async () => {
    await expect(element(by.id('security-note'))).toBeVisible();
  });

  it('should collapse advanced section when toggled again', async () => {
    await element(by.id('advanced-toggle-btn')).tap();

    // Private key input should no longer be visible
    await expect(element(by.id('private-key-input'))).not.toBeVisible();
  });

  it('should navigate back from ConnectWallet screen', async () => {
    await device.pressBack();
    await expect(element(by.id('settings-screen'))).toBeVisible();
  });
});
