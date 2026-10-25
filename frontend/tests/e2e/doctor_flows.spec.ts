// =============================================================================
// 醫師端主要流程 e2e（mock 模式、VITE_MOCK_ROLE=doctor、純前端）
//   1. 登入頁 → 已認證醫師自動導向儀表板（標題可見）
//   2. SOAP 報告列表 → 有報告列 → 點進報告詳情（標題 + 摘要可見）
//   3. 紅旗警示列表 → 有警示列 → 確認（acknowledge）後徽章轉為已處理
// mock 模式下列表資料來自 store / 頁面內建 mock；acknowledge 仍打 API，故以
// page.route 回傳已確認的警示。
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
  // mock 模式仍會對 sessions / alerts 的輔助端點發請求（session meta、unacknowledged count）；
  // 一律擋下，避免等待 localhost:8000 逾時。
  await page.route(/\/api\/v1\/.*/, (route) =>
    route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { message: 'mocked' } }) }),
  );
  await page.goto(path);
}

test.describe('醫師端流程', () => {
  test('登入頁 → 儀表板', async ({ page }) => {
    await bootstrap(page, '/en-US/login');
    await expect(page).toHaveURL(/\/en-US\/dashboard$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Monthly consultation overview' })).toBeVisible();
    // 月份摘要卡（mock createMockMonthlySummary）
    await expect(page.locator('main')).toContainText(/\d/);
  });

  test('報告列表 → 報告詳情', async ({ page }) => {
    await bootstrap(page, '/en-US/reports');
    await expect(page.getByRole('heading', { level: 1, name: 'SOAP reports' })).toBeVisible();
    const rows = page.locator('main button.list-card');
    await expect(rows.first()).toBeVisible();
    expect(await rows.count()).toBeGreaterThanOrEqual(3);
    await rows.first().click();
    await expect(page).toHaveURL(/\/en-US\/reports\/[\w-]+$/);
    await expect(page.getByRole('heading', { level: 1, name: 'SOAP Report' })).toBeVisible();
    // reportStore mock 的英文摘要
    await expect(page.locator('main')).toContainText(/hematuria|Hematuria/);
  });

  test('警示列表 → acknowledge', async ({ page }) => {
    await bootstrap(page, '/en-US/alerts');
    await expect(page.getByRole('heading', { level: 1, name: 'Red-flag alerts' })).toBeVisible();

    // acknowledge 端點回傳已確認的警示（snake_case，client 會轉 camelCase）
    await page.route(/\/api\/v1\/alerts\/[\w-]+\/acknowledge$/, (route) => {
      const id = route.request().url().split('/').at(-2);
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id, acknowledged_by: 'mock-doctor-001', acknowledged_at: '2026-10-24T00:00:00Z' }),
      });
    });
    page.on('dialog', (dialog) => dialog.accept());

    const cards = page.locator('main .alert-card');
    await expect(cards.first()).toBeVisible();
    const pendingBefore = await page.getByText('Pending', { exact: true }).count();
    expect(pendingBefore).toBeGreaterThan(0);

    const firstPendingCard = cards.filter({ hasText: 'Pending' }).first();
    await expect(firstPendingCard).toBeVisible();
    const title = await firstPendingCard.locator('p.font-semibold').first().textContent();
    await firstPendingCard.getByRole('button', { name: 'Acknowledge' }).click();

    // 該卡片徽章轉為 Acknowledged、待處理數減一
    await expect(cards.filter({ hasText: title ?? '' }).first()).toContainText('Acknowledged');
    await expect(page.getByText('Pending', { exact: true })).toHaveCount(pendingBefore - 1);
  });
});
