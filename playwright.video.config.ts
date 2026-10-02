import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: 'recorded-video.spec.ts',
  use: {
    baseURL: 'http://127.0.0.1:5175', headless: true,
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
  },
  webServer: [
    {
      command: '.venv/bin/python -m apps.backend.elbow_room.server --config data/video-e2e/config.json --port 8012 --database data/video-e2e/history.sqlite3',
      url: 'http://127.0.0.1:8012/api/health', reuseExistingServer: false,
    },
    {
      command: 'npm run dev --workspace @elbow-room/web -- --port 5175',
      url: 'http://127.0.0.1:5175', env: { ELBOW_API_URL: 'http://127.0.0.1:8012' }, reuseExistingServer: false,
    },
  ],
});
