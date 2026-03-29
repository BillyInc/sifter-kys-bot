import { test, expect } from '@playwright/test';

test('homepage loads', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Sifter KYS/);
});

test('dashboard shows quick actions', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('What would you like to do today')).toBeVisible({ timeout: 10000 });
});

test('theme toggle works', async ({ page }) => {
  await page.goto('/');
  const html = page.locator('html');
  await expect(html).toHaveClass(/dark/);
});
