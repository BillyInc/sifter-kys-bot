import { test, expect } from '@playwright/test';

test('login form is accessible', async ({ page }) => {
  await page.goto('/');
  // Check for sign in / sign up UI elements
  const authElement = page.getByText(/sign in|log in|get started/i);
  await expect(authElement).toBeVisible({ timeout: 10000 });
});
