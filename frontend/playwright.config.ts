// =============================================================================
// Playwright 設定 — e2e 測試
// 啟動三個 vite dev server（mock 模式、角色不同）：
//   5175 VITE_MOCK_ROLE=patient → project `chromium`（病患端 / i18n spec）
//   5176 VITE_MOCK_ROLE=doctor  → project `chromium-doctor`（tests/e2e/doctor_*.spec.ts）
//   5177 VITE_MOCK_ROLE=admin   → project `chromium-admin`（tests/e2e/admin_*.spec.ts）
// 以 chromium 為唯一 browser。預設語系 en-US，i18n spec 會各自切換語系驗證。
// =============================================================================

import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.PW_PORT || 5175);
const DOCTOR_PORT = Number(process.env.PW_DOCTOR_PORT || 5176);
const ADMIN_PORT = Number(process.env.PW_ADMIN_PORT || 5177);
const BASE_URL = `http://localhost:${PORT}`;
const DOCTOR_BASE_URL = `http://localhost:${DOCTOR_PORT}`;
const ADMIN_BASE_URL = `http://localhost:${ADMIN_PORT}`;

// 強制 mock 模式 + 提供必要 VITE_ 變數，避免測試依賴後端 / Supabase
function devServer(role: 'patient' | 'doctor' | 'admin', port: number) {
  return {
    command:
      `VITE_ENABLE_MOCK=true VITE_MOCK_ROLE=${role} ` +
      'VITE_API_BASE_URL=http://localhost:8000/api/v1 ' +
      'VITE_WS_BASE_URL=ws://localhost:8000/api/v1/ws ' +
      'VITE_SUPABASE_URL=http://localhost:54321 ' +
      'VITE_SUPABASE_ANON_KEY=mock-anon-key ' +
      `npm run dev -- --host 127.0.0.1 --port ${port}`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'pipe' as const,
    stderr: 'pipe' as const,
  };
}

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
      testIgnore: [/doctor_.*\.spec\.ts/, /admin_.*\.spec\.ts/],
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'chromium-doctor',
      testMatch: /doctor_.*\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], baseURL: DOCTOR_BASE_URL },
    },
    {
      name: 'chromium-admin',
      testMatch: /admin_.*\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], baseURL: ADMIN_BASE_URL },
    },
  ],
  webServer: [devServer('patient', PORT), devServer('doctor', DOCTOR_PORT), devServer('admin', ADMIN_PORT)],
});
