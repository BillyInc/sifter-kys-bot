import { test, expect } from '@playwright/test';

test('page loads without auth crash', async ({ page }) => {
  await page.goto('/');
  // App should render even without Supabase configured in CI
  await expect(page.locator('#root')).toBeAttached();
  await expect(page.locator('#root')).not.toBeEmpty();
});
