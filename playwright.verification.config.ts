import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests', testMatch: 'verification.spec.ts',
  use: {
    baseURL: 'http://127.0.0.1:5176', headless: true,
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
  },
  webServer: [
    {
      command: '.venv/bin/python -m scripts.verification_e2e',
      url: 'http://127.0.0.1:8013/api/health', reuseExistingServer: false,
    },
    {
      command: 'npm run dev --workspace @elbow-room/web -- --port 5176',
      url: 'http://127.0.0.1:5176', env: { ELBOW_API_URL: 'http://127.0.0.1:8013' }, reuseExistingServer: false,
    },
  ],
});
