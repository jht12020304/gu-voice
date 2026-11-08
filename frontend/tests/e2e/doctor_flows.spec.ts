// =============================================================================
// 醫師端主要流程 e2e（mock 模式、VITE_MOCK_ROLE=doctor、純前端）
// 網頁版只剩醫師看報告：
//   1. 登入頁 / 已移除的舊頁 → 已認證醫師自動導向報告列表
//   2. 報告列表 → 點進報告（患者名稱、摘要、SOAP、逐字稿、快速開單）
//   3. 快速開單：勾 AI 建議檢查 → 送出的 payload 正確
// mock 模式下列表資料來自 store / 頁面內建 mock；開單仍打 API，故以 page.route 攔截。
// =============================================================================

import { test, expect, type Page } from '@playwright/test';

async function bootstrap(page: Page, path: string): Promise<void> {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem('urosense:lng', 'en-US');
      window.localStorage.setItem('access_token', 'mock-token');
      window.localStorage.setItem('refresh_token', 'mock-refresh');
    } catch {
      /* ignore */
    }
  });
  // mock 模式仍會對 sessions / exam-orders 等輔助端點發請求；
  // 一律擋下，避免等待 localhost:8000 逾時。
  await page.route(/\/api\/v1\/.*/, (route) =>
    route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { message: 'mocked' } }) }),
  );
  await page.goto(path);
}

test.describe('醫師端流程', () => {
  test('登入頁與舊頁 → 報告列表', async ({ page }) => {
    await bootstrap(page, '/en-US/login');
    await expect(page).toHaveURL(/\/en-US\/reports$/);
    await page.goto('/en-US/dashboard');
    await expect(page).toHaveURL(/\/en-US\/reports$/);
    await expect(page.getByRole('heading', { level: 1, name: 'SOAP reports' })).toBeVisible();
  });

  test('報告列表 → 報告詳情', async ({ page }) => {
    await bootstrap(page, '/en-US/reports');
    const rows = page.locator('main button.list-card');
    await expect(rows.first()).toBeVisible();
    expect(await rows.count()).toBeGreaterThanOrEqual(3);
    await rows.first().click();
    await expect(page).toHaveURL(/\/en-US\/reports\/[\w-]+$/);
    // 標題是患者名稱（mock session）
    await expect(page.getByRole('heading', { level: 1 })).not.toBeEmpty();
    await expect(page.locator('main')).toContainText(/hematuria|Hematuria/);
    await expect(page.getByRole('heading', { name: 'Quick orders' })).toBeVisible();
    await expect(page.getByRole('button', { name: /Export PDF/ })).toBeVisible();
  });

  test('快速開單送出勾選項目', async ({ page }) => {
    await bootstrap(page, '/en-US/reports/s1');
    let posted: unknown = null;
    await page.route(/\/api\/v1\/sessions\/[\w-]+\/exam-orders$/, async (route) => {
      posted = route.request().postDataJSON();
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ id: 'o1', session_id: 's1', ordered_by: 'd1', items: [], note: null, created_at: '2026-11-08T00:00:00Z' }),
      });
    });
    const boxes = page.locator('#quick-orders-title').locator('..').locator('..').getByRole('checkbox');
    await expect(boxes.first()).toBeVisible();
    await boxes.first().check();
    await page.getByRole('button', { name: 'Confirm and submit' }).click();
    await expect.poll(() => posted).not.toBeNull();
    const body = posted as { items: Array<{ test_name: string }> };
    expect(body.items).toHaveLength(1);
    expect(body.items[0].test_name).toBeTruthy();
  });

});
