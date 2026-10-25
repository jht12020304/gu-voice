// =============================================================================
// 管理員：使用者管理頁 e2e（mock 模式、VITE_MOCK_ROLE=admin、純前端）
//   頁面渲染（標題 + mock 使用者列）→ 點「Add User」→ 新增對話框開啟（表單欄位可見）
// =============================================================================

import { test, expect } from '@playwright/test';

test('使用者管理頁渲染並可開啟新增對話框', async ({ page }) => {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem('urosense:lng', 'en-US');
      window.localStorage.setItem('access_token', 'mock-token');
      window.localStorage.setItem('refresh_token', 'mock-refresh');
    } catch {
      /* ignore */
    }
  });
  await page.route(/\/api\/v1\/.*/, (route) =>
    route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { message: 'mocked' } }) }),
  );
  await page.goto('/en-US/admin/users');

  await expect(page.getByRole('heading', { level: 1, name: 'User Management' })).toBeVisible();
  // mockUsers 的 email 真的渲染出來（不是只有 200）
  await expect(page.locator('main')).toContainText('doctor@gu-voice.local');
  await expect(page.locator('main')).toContainText('admin@gu-voice.local');

  await page.getByRole('button', { name: 'Add User' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'Add User' })).toBeVisible();
  await expect(dialog.getByText(/Name/)).toBeVisible();
  await expect(dialog.getByText(/Email/)).toBeVisible();
});
