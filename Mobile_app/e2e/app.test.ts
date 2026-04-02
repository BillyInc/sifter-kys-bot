import { by, device, element, expect } from 'detox';

describe('App Launch', () => {
  beforeAll(async () => {
    await device.launchApp({ newInstance: true });
  });

  afterAll(async () => {
    await device.terminateApp();
  });

  it('should launch the app successfully', async () => {
    // The app lock screen or main navigator should be visible
    // When app_locked is not set, AppLock passes through to the navigator
    await expect(element(by.id('app-navigator'))).toBeVisible();
  });

  it('should show the bottom tab bar with four tabs', async () => {
    await expect(element(by.id('tab-dashboard'))).toBeVisible();
    await expect(element(by.id('tab-positions'))).toBeVisible();
    await expect(element(by.id('tab-elite'))).toBeVisible();
    await expect(element(by.id('tab-settings'))).toBeVisible();
  });

  it('should start on the Dashboard tab', async () => {
    await expect(element(by.id('dashboard-screen'))).toBeVisible();
  });

  it('should navigate to Positions tab', async () => {
    await element(by.id('tab-positions')).tap();
    await expect(element(by.id('positions-screen'))).toBeVisible();
  });

  it('should navigate to Elite tab', async () => {
    await element(by.id('tab-elite')).tap();
    await expect(element(by.id('elite-screen'))).toBeVisible();
  });

  it('should navigate to Settings tab', async () => {
    await element(by.id('tab-settings')).tap();
    await expect(element(by.id('settings-screen'))).toBeVisible();
  });

  it('should navigate back to Dashboard tab', async () => {
    await element(by.id('tab-dashboard')).tap();
    await expect(element(by.id('dashboard-screen'))).toBeVisible();
  });
});

describe('App Reload', () => {
  it('should reload the app without crashing', async () => {
    await device.reloadReactNative();
    await expect(element(by.id('app-navigator'))).toBeVisible();
  });
});
