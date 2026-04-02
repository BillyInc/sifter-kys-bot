import { by, device, element, expect } from 'detox';

describe('Settings Screen', () => {
  beforeAll(async () => {
    await device.launchApp({ newInstance: true });
  });

  afterAll(async () => {
    await device.terminateApp();
  });

  it('should navigate to the Settings tab', async () => {
    await element(by.id('tab-settings')).tap();
    await expect(element(by.id('settings-screen'))).toBeVisible();
  });

  it('should display the Account section', async () => {
    await expect(element(by.text('Account'))).toBeVisible();
    await expect(element(by.text('Plan'))).toBeVisible();
    await expect(element(by.text('Wallet'))).toBeVisible();
  });

  it('should display the Portfolio section', async () => {
    await expect(element(by.text('Portfolio'))).toBeVisible();
    await expect(element(by.id('portfolio-input'))).toBeVisible();
    await expect(element(by.id('portfolio-save-btn'))).toBeVisible();
  });

  it('should allow editing portfolio value', async () => {
    await element(by.id('portfolio-input')).clearText();
    await element(by.id('portfolio-input')).typeText('50000');
    await expect(element(by.id('portfolio-input'))).toHaveText('50000');
  });

  it('should display the Trade Settings section', async () => {
    await expect(element(by.text('Trade Settings'))).toBeVisible();
    await expect(element(by.id('min-buy-input'))).toBeVisible();
    await expect(element(by.id('auto-replace-switch'))).toBeVisible();
  });

  it('should toggle the auto-replace switch', async () => {
    await element(by.id('auto-replace-switch')).tap();
    // Toggle back
    await element(by.id('auto-replace-switch')).tap();
  });

  it('should display the MEV Protection section', async () => {
    await element(by.id('settings-screen')).scrollTo('bottom');
    await expect(element(by.text('MEV Protection'))).toBeVisible();
  });

  it('should display the Danger Zone section', async () => {
    await expect(element(by.id('kill-switch-btn'))).toBeVisible();
    await expect(element(by.id('self-destruct-btn'))).toBeVisible();
  });

  it('should navigate to ConnectWallet from Settings', async () => {
    await element(by.id('settings-screen')).scrollTo('top');
    await element(by.id('settings-connect-wallet-btn')).tap();
    await expect(element(by.id('connect-wallet-screen'))).toBeVisible();
    await device.pressBack();
  });
});
