// =============================================================================
// Playwright 設定 — e2e 測試
// 啟動 vite dev server (port 5173)，以 chromium 為唯一 browser。
// 預設語系 en-US，i18n spec 會各自切換語系驗證。
// =============================================================================

import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.PW_PORT || 5173);
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  outputDir: 'test-results/artifacts',
  use: {
    baseURL: BASE_URL,
    locale: 'en-US',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    viewport: { width: 1280, height: 800 },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    // 強制 mock 模式 + 提供必要 VITE_ 變數，避免測試依賴後端 / Supabase
    command:
      'VITE_ENABLE_MOCK=true VITE_MOCK_ROLE=patient ' +
      'VITE_API_BASE_URL=http://localhost:8000/api/v1 ' +
      'VITE_WS_BASE_URL=ws://localhost:8000/api/v1/ws ' +
      'VITE_SUPABASE_URL=http://localhost:54321 ' +
      'VITE_SUPABASE_ANON_KEY=mock-anon-key ' +
      'npm run dev -- --host 127.0.0.1 --port ' + PORT,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
