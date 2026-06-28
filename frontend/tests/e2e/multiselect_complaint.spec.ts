// =============================================================================
// 主訴複選 e2e（mock 模式，純前端、不依賴後端）
// 驗證使用者需求：「主訴有機會可以複選嗎？來 narrow down 鑑別診斷」
//   1. 可複選多個症狀；第一個選的標記為「主要」(primary FK)
//   2. 可切換取消/重選；數量計數正確
//   3. 數量上限 (MAX_SELECT=5) 會擋住第 6 個
//   4. 按開始 → 導向 medical-info，complaintText 合併所有主訴名稱且 ≤200 code points
//      （complaintId = 第一個選的，醫療安全：名稱不被中途截斷）
// =============================================================================

import { test, expect, type Page } from '@playwright/test';

// mock 模式下 SelectComplaintPage 直接用內建 10 筆 mockComplaints，不打 API。
// 仍預寫 token + 語系，避免被導去登入頁。
async function bootstrap(page: Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem('urosense:lng', 'zh-TW');
      window.localStorage.setItem('access_token', 'mock-token');
      window.localStorage.setItem('refresh_token', 'mock-refresh');
    } catch {
      /* ignore */
    }
  });
  await page.goto('/zh-TW/patient/start');
  await page.waitForLoadState('networkidle');
}

// 用 nameEn（英文副標，永遠存在）定位卡片按鈕，避免 mock 中文/英文歧義
const card = (page: Page, nameEn: string) =>
  page.getByRole('button', { name: new RegExp(nameEn) });

test.describe('主訴複選', () => {
  test('可複選、標記主要、合併進 complaintText 且 ≤200', async ({ page }) => {
    await bootstrap(page);

    const hematuria = card(page, 'Hematuria');
    const frequent = card(page, 'Frequent Urination');
    const dysuria = card(page, 'Dysuria');
    const cta = page.locator('.sticky button');

    await expect(hematuria).toBeVisible();
    // 初始無選取 → CTA 停用
    await expect(cta).toBeDisabled();

    // 複選三個
    await hematuria.click();
    await frequent.click();
    await dysuria.click();

    await expect(hematuria).toHaveAttribute('aria-pressed', 'true');
    await expect(frequent).toHaveAttribute('aria-pressed', 'true');
    await expect(dysuria).toHaveAttribute('aria-pressed', 'true');

    // 「主要」badge 只掛在第一個選的（血尿）
    await expect(hematuria.getByText('主要')).toBeVisible();
    await expect(frequent.getByText('主要')).toHaveCount(0);

    // 計數 3/5、CTA 啟用
    await expect(page.getByText(/已選\s*3\s*\/\s*5/)).toBeVisible();
    await expect(cta).toBeEnabled();

    // 可切換：取消中間一個再選回
    await frequent.click();
    await expect(frequent).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByText(/已選\s*2\s*\/\s*5/)).toBeVisible();
    await frequent.click();
    await expect(frequent).toHaveAttribute('aria-pressed', 'true');

    // 開始 → 導向 medical-info，檢查 query
    await cta.click();
    await page.waitForURL(/\/patient\/medical-info/);

    const url = new URL(page.url());
    const complaintId = url.searchParams.get('complaintId') ?? '';
    const complaintText = url.searchParams.get('complaintText') ?? '';

    // 主要 = 第一個選的（血尿 = cc1）
    expect(complaintId).toBe('cc1');
    // 三個主訴名稱都進合併文字（協助醫師 narrow down）
    for (const n of ['血尿', '頻尿', '排尿疼痛']) {
      expect(complaintText).toContain(n);
    }
    // 醫療安全：合併文字以 code point 計 ≤200
    expect(Array.from(complaintText).length).toBeLessThanOrEqual(200);
  });

  test('數量上限 5：第 6 個被擋下', async ({ page }) => {
    await bootstrap(page);

    // 前 5 個（排尿症狀 4 個 + 疼痛 1 個）
    for (const n of [
      'Hematuria',
      'Frequent Urination',
      'Dysuria',
      'Urinary Incontinence',
      'Flank Pain',
    ]) {
      await card(page, n).click();
    }
    await expect(page.getByText(/已選\s*5\s*\/\s*5/)).toBeVisible();

    // 第 6 個（Lower Abdominal Pain）點了也不會被選取
    const sixth = card(page, 'Lower Abdominal Pain');
    await sixth.click();
    await expect(sixth).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByText(/已選\s*5\s*\/\s*5/)).toBeVisible();
  });
});
