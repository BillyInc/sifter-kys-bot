import { defineConfig } from '@playwright/test';

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  use: {
    baseURL: isCI ? 'http://localhost:4173' : 'http://localhost:5173',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: isCI ? 'pnpm run preview --port 4173' : 'pnpm run dev',
    port: isCI ? 4173 : 5173,
    reuseExistingServer: true,
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
