import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests', testMatch: 'complete-demo.spec.ts', timeout: 120000,
  use: {
    baseURL: 'http://127.0.0.1:5178', headless: true,
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
  },
  webServer: {
    command: '.venv/bin/python scripts/run-demo.py --rtsp-video data/evaluation-smoke/empty.avi --port 8071 --web-port 5178 --verifier-port 8083',
    url: 'http://127.0.0.1:5178', reuseExistingServer: false, timeout: 120000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 15000 },
  },
});
