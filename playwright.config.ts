import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testIgnore: ['recorded-video.spec.ts', 'verification.spec.ts', 'complete-demo.spec.ts'],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    headless: true,
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
  },
  webServer: [
    {
      command: 'python3 -m apps.backend.elbow_room.server --port 8011 --interval 1 --database data/e2e.sqlite3',
      url: 'http://127.0.0.1:8011/api/health',
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev --workspace @elbow-room/web -- --port 5174',
      url: 'http://127.0.0.1:5174',
      env: { ELBOW_API_URL: 'http://127.0.0.1:8011' },
      reuseExistingServer: false,
    },
  ],
});
