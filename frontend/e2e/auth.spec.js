import { test, expect } from '@playwright/test';

test('page loads without crash', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#root')).toBeAttached();
  // Wait for React to hydrate — check for any rendered content
  await page.waitForTimeout(3000);
  const content = await page.locator('#root').innerHTML();
  // Root should have some content after React renders (even if just loading state)
  expect(content.length).toBeGreaterThan(0);
});
