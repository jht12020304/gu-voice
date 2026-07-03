// =============================================================================
// 主訴「其他」選項 e2e（mock 模式，純前端、不依賴後端）
// 驗證使用者需求：「主訴選擇要有『其他』選項」
//   1. 「其他」卡片顯示在「其他」section，虛線框（border-dashed）略作區別
//   2. 含「其他」時補充說明必填：空自述 → CTA disabled + 提示；輸入後放行
//   3. 只選「其他」→ complaintId = sentinel UUID、complaintText = 自述原文
//      （不含字面「其他」佔位詞，AI/SOAP/紅旗吃的是病患自述）
//   4. 可與其他主訴併選；primary = 第一個選的；合併文字 ≤200 code points
//   5. 回歸：不含「其他」時補充說明維持選填
// =============================================================================

import { test, expect, type Page } from '@playwright/test';

// 與 SelectComplaintPage / 後端 seed（20260704_1000-seed_other_chief_complaint）同步
const SENTINEL_ID = '00000000-0000-4000-8000-0000000000ff';

// mock 模式下 SelectComplaintPage 直接用內建 mockComplaints，不打 API。
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

// 用 nameEn（英文副標，永遠存在）定位卡片按鈕；mock 中無其他含 'Other' 子串的 nameEn
const card = (page: Page, nameEn: string) =>
  page.getByRole('button', { name: new RegExp(nameEn) });

const cta = (page: Page) => page.locator('.sticky button');

test.describe('主訴「其他」選項', () => {
  test('「其他」卡片在「其他」section、虛線框', async ({ page }) => {
    await bootstrap(page);

    // section 標題「其他」之後的卡片格中找到 Other 卡
    const otherHeading = page.getByRole('heading', { name: '其他', exact: true });
    await expect(otherHeading).toBeVisible();
    const grid = otherHeading.locator('xpath=following-sibling::div');
    const otherCard = grid.getByRole('button', { name: /Other/ });
    await expect(otherCard).toBeVisible();
    await expect(otherCard).toHaveClass(/border-dashed/);
  });

  test('只選「其他」：自述必填，送出後 complaintText = 自述原文', async ({ page }) => {
    await bootstrap(page);

    const other = card(page, 'Other');
    await other.click();
    await expect(other).toHaveAttribute('aria-pressed', 'true');

    // 空自述 → CTA 停用 + 必填提示可見
    await expect(cta(page)).toBeDisabled();
    await expect(page.getByText('已選擇「其他」，請先簡單描述您的症狀')).toBeVisible();

    // textarea 標成必填（label 與 aria）
    await expect(page.getByText('補充說明（必填）')).toBeVisible();
    const textarea = page.locator('textarea');
    await expect(textarea).toHaveAttribute('aria-required', 'true');

    // 輸入自述 → 提示消失、CTA 啟用
    const complaint = '睪丸腫了一顆，摸起來會痛';
    await textarea.fill(complaint);
    await expect(page.getByText('已選擇「其他」，請先簡單描述您的症狀')).toHaveCount(0);
    await expect(cta(page)).toBeEnabled();

    await cta(page).click();
    await page.waitForURL(/\/patient\/medical-info/);

    const url = new URL(page.url());
    // FK 指向 sentinel；文字是自述原文，不含字面「其他」佔位詞
    expect(url.searchParams.get('complaintId')).toBe(SENTINEL_ID);
    expect(url.searchParams.get('complaintText')).toBe(complaint);
    expect(url.searchParams.get('complaintText') ?? '').not.toContain('其他');
    // MedicalInfo header 顯示用的名稱仍是在地化「其他」
    expect(url.searchParams.get('complaintName')).toBe('其他');
  });

  test('血尿 + 其他 併選：primary = 血尿，合併文字含自述、不含「其他」', async ({ page }) => {
    await bootstrap(page);

    await card(page, 'Hematuria').click();
    await card(page, 'Other').click();

    // 含「其他」→ 即使已有具名主訴，自述仍必填
    await expect(cta(page)).toBeDisabled();

    const note = '睪丸也腫腫的';
    await page.locator('textarea').fill(note);
    await expect(cta(page)).toBeEnabled();

    await cta(page).click();
    await page.waitForURL(/\/patient\/medical-info/);

    const url = new URL(page.url());
    const complaintText = url.searchParams.get('complaintText') ?? '';
    expect(url.searchParams.get('complaintId')).toBe('cc1'); // primary = 第一個選的
    expect(complaintText).toContain('血尿');
    expect(complaintText).toContain(note);
    expect(complaintText).not.toContain('其他');
    // 醫療安全：合併文字以 code point 計 ≤200
    expect(Array.from(complaintText).length).toBeLessThanOrEqual(200);
  });

  test('「其他」先選 + 血尿：primary = sentinel', async ({ page }) => {
    await bootstrap(page);

    await card(page, 'Other').click();
    await card(page, 'Hematuria').click();
    await page.locator('textarea').fill('皮膚也癢癢的');

    await cta(page).click();
    await page.waitForURL(/\/patient\/medical-info/);

    const url = new URL(page.url());
    expect(url.searchParams.get('complaintId')).toBe(SENTINEL_ID);
  });

  test('回歸：不含「其他」時補充說明仍選填', async ({ page }) => {
    await bootstrap(page);

    await card(page, 'Hematuria').click();
    // 選填 label、CTA 直接可按
    await expect(page.getByText('補充說明（選填）')).toBeVisible();
    await expect(cta(page)).toBeEnabled();

    await cta(page).click();
    await page.waitForURL(/\/patient\/medical-info/);
    expect(new URL(page.url()).searchParams.get('complaintText')).toBe('血尿');
  });
});
