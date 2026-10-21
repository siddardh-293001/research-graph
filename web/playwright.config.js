import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', timeout: 60000, workers: 1, retries: 0,
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || './test-results',
  use: {baseURL: process.env.PUBLIC_BASE_URL || 'http://127.0.0.1:8000', browserName: 'chromium', screenshot: 'only-on-failure', actionTimeout:10000},
});
