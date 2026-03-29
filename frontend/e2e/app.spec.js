import { test, expect } from '@playwright/test';

test('homepage loads with correct title', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Sifter KYS/);
});

test('dashboard shows quick actions', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText(/what would you like to do/i)).toBeVisible({ timeout: 10000 });
});

test('dark mode is default', async ({ page }) => {
  await page.goto('/');
  const html = page.locator('html');
  await expect(html).toHaveClass(/dark/);
});
