import { test, expect } from '@playwright/test';

test('homepage loads with correct title', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Sifter KYS/);
});

test('page renders without crash', async ({ page }) => {
  await page.goto('/');
  // Just verify the root element rendered
  await expect(page.locator('#root')).toBeAttached();
});

test('no console errors on load', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  await page.goto('/');
  await page.waitForTimeout(2000);
  // Filter out expected errors (Supabase auth when not configured)
  const realErrors = errors.filter(
    (e) => !e.includes('supabase') && !e.includes('auth') && !e.includes('fetch')
  );
  expect(realErrors).toHaveLength(0);
});
