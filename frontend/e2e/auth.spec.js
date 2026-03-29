import { test, expect } from '@playwright/test';

test('shows auth UI for unauthenticated users', async ({ page }) => {
  await page.goto('/');
  const authElement = page.getByText(/sign in|log in|get started/i);
  await expect(authElement).toBeVisible({ timeout: 10000 });
});
