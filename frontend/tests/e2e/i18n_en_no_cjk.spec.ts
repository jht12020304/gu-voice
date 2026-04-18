// =============================================================================
// B9 — i18n e2e: en-US 下病患流程關鍵頁面不得有 CJK 字元
// ---------------------------------------------------------------------------
// 流程：
//   1. 每個 test 先在 addInitScript 裡把 localStorage['urosense:lng'] 預寫成目標
//      語系；這個腳本會在任何 page script 執行前跑，因此 i18next LanguageDetector
//      初始化時就能讀到正確值。
//   2. 同時 intercept /api/v1/** 常用 endpoint，回傳帶 `name_by_lang.en-US` 的 mock
//      資料，避免測試依賴真實後端。
//   3. 各頁面 load 完後，抓 document.body.innerText，regex 比對 CJK 字元。
//   4. 同樣流程跑 zh-TW baseline，確認 CJK 數量 > 0（避免 regex 寫錯卻偵測不到）。
// =============================================================================

import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// CJK 範圍：CJK Unified Ideographs / 日文假名 / 韓文音節
const CJK_REGEX = /[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/g;

type PatientPage = {
  /** 給檔名用的 slug */
  slug: string;
  /** 相對於 baseURL 的 path（不含 lng 前綴）。runner 會自動接上 /${lng}${path}。*/
  path: string;
  /** 用於等待頁面 ready 的元素 role+name 或純 selector。不填則等 body 可見。*/
  waitFor?: (page: Page) => Promise<void>;
  /** 是否需要帶 Intake 用的 query string（complaint 資訊）。*/
  withComplaintParams?: boolean;
};

const patientPages: PatientPage[] = [
  {
    slug: 'select-complaint',
    // 真實路由是 /patient/start（SelectComplaintPage）— 參考 RootNavigator.tsx
    path: '/patient/start',
    waitFor: async (page) => {
      await page.waitForLoadState('networkidle');
    },
  },
  {
    slug: 'medical-info',
    path: '/patient/medical-info',
    withComplaintParams: true,
    waitFor: async (page) => {
      await page.waitForLoadState('networkidle');
    },
  },
  {
    slug: 'session-complete',
    // SessionCompletePage 需要 sessionId param
    path: '/patient/session/mock-session-001/complete',
    waitFor: async (page) => {
      await page.waitForLoadState('networkidle');
    },
  },
  {
    slug: 'thank-you',
    path: '/patient/session/mock-session-001/thank-you',
    waitFor: async (page) => {
      await page.waitForLoadState('networkidle');
    },
  },
];

/** 雙語 mock 主訴資料；en-US 欄位故意 unique，確保真的走 i18n 而非巧合英文。 */
const mockComplaintsPayload = {
  complaints: [
    {
      id: 'cc1',
      name: '血尿',
      name_en: 'Hematuria',
      name_by_lang: {
        'zh-TW': '血尿',
        'en-US': 'Hematuria',
      },
      description: '尿液中帶血或呈紅色',
      description_by_lang: {
        'zh-TW': '尿液中帶血或呈紅色',
        'en-US': 'Blood visible in urine',
      },
      category: '排尿症狀',
      category_by_lang: {
        'zh-TW': '排尿症狀',
        'en-US': 'Voiding symptoms',
      },
      is_default: true,
      is_active: true,
      display_order: 1,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 'cc2',
      name: '頻尿',
      name_en: 'Frequent Urination',
      name_by_lang: {
        'zh-TW': '頻尿',
        'en-US': 'Frequent Urination',
      },
      category: '排尿症狀',
      category_by_lang: {
        'zh-TW': '排尿症狀',
        'en-US': 'Voiding symptoms',
      },
      is_default: true,
      is_active: true,
      display_order: 2,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
  ],
};

const mockSessionPayload = {
  id: 'mock-session-001',
  patient_id: 'mock-patient-001',
  doctor_id: 'mock-doctor-001',
  chief_complaint_id: 'cc1',
  chief_complaint_text: 'Hematuria for 3 days',
  status: 'completed',
  red_flag: false,
  language: 'en-US',
  started_at: '2026-04-10T13:30:00Z',
  completed_at: '2026-04-10T13:45:00Z',
  duration_seconds: 900,
  created_at: '2026-04-10T13:30:00Z',
  updated_at: '2026-04-10T13:45:00Z',
};

const mockReportPayload = {
  id: 'mock-report-001',
  session_id: 'mock-session-001',
  status: 'generated',
  summary: 'Patient presents with gross hematuria persisting for three days.',
  created_at: '2026-04-10T13:46:00Z',
  updated_at: '2026-04-10T13:46:00Z',
};

/** 掛上 API mock 路由；避免 hit 真實後端。 */
async function installApiMocks(page: Page): Promise<void> {
  // Chief complaints 列表
  await page.route(/\/api\/v1\/chief_complaints(\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockComplaintsPayload),
    }),
  );

  // Session by id
  await page.route(/\/api\/v1\/sessions\/[\w-]+$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessionPayload),
    }),
  );

  // Sessions list / create
  await page.route(/\/api\/v1\/sessions(\?.*)?$/, (route) => {
    const method = route.request().method();
    if (method === 'POST') {
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(mockSessionPayload),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ sessions: [mockSessionPayload], total: 1 }),
    });
  });

  // Report by session
  await page.route(/\/api\/v1\/sessions\/[\w-]+\/report$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockReportPayload),
    }),
  );
  await page.route(/\/api\/v1\/reports\/.*$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockReportPayload),
    }),
  );

  // auth/me fallback（若 Mock 模式沒開仍會被呼叫，直接回 401 讓 Mock user 接手）
  await page.route(/\/api\/v1\/auth\/.*/, (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: { message: 'unauthorized' } }),
    }),
  );
}

/** 收集頁面可見文字中的 CJK 字元。 */
async function collectCjkChars(page: Page): Promise<string[]> {
  const innerText = await page.evaluate(() => document.body.innerText || '');
  const matches = innerText.match(CJK_REGEX) || [];
  return matches;
}

/** 預先把 localStorage['urosense:lng'] 設成目標語系，i18next 初始化時就會拿到。 */
async function setLngBeforeLoad(page: Page, lng: 'en-US' | 'zh-TW'): Promise<void> {
  await page.addInitScript((targetLng) => {
    try {
      window.localStorage.setItem('urosense:lng', targetLng);
      window.localStorage.setItem('access_token', 'mock-token');
      window.localStorage.setItem('refresh_token', 'mock-refresh');
    } catch {
      // sandbox / storage 被 block 時忽略
    }
  }, lng);
}

/** 截圖目錄，失敗與成功都落地，方便人工檢查。 */
function screenshotPath(lng: string, slug: string): string {
  const dir = path.join('test-results', `i18n-${lng}`);
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, `${slug}.png`);
}

function buildComplaintQuery(): string {
  const params = new URLSearchParams({
    complaintId: 'cc1',
    complaintName: 'Hematuria',
    complaintText: 'Blood in urine for 3 days',
  });
  return `?${params.toString()}`;
}

// -----------------------------------------------------------------------------
// en-US：所有頁面應「零 CJK」
// -----------------------------------------------------------------------------
test.describe('i18n en-US: patient pages should contain no CJK characters', () => {
  for (const pageDef of patientPages) {
    test(`[en-US] ${pageDef.slug} has zero CJK chars`, async ({ page }) => {
      await setLngBeforeLoad(page, 'en-US');
      await installApiMocks(page);

      const query = pageDef.withComplaintParams ? buildComplaintQuery() : '';
      const url = `/en-US${pageDef.path}${query}`;
      await page.goto(url);

      if (pageDef.waitFor) {
        await pageDef.waitFor(page);
      } else {
        await page.waitForLoadState('networkidle');
      }

      // 先截圖保留事證（不論 pass/fail 都會有）
      await page.screenshot({ path: screenshotPath('en', pageDef.slug), fullPage: true });

      const cjkChars = await collectCjkChars(page);
      const unique = Array.from(new Set(cjkChars));

      if (cjkChars.length > 0) {
        // 把 leak 的字元與前 10 筆 sample 列在錯誤訊息中，方便除錯
        const sample = cjkChars.slice(0, 20).join('');
        console.error(
          `[i18n leak] ${pageDef.slug} — ${cjkChars.length} CJK chars, ` +
            `${unique.length} unique. Sample: "${sample}" | Unique: ${unique.join(' ')}`,
        );
      }

      expect(
        cjkChars,
        `Page "/en-US${pageDef.path}" leaked CJK chars (unique=${unique.join(' ')}).`,
      ).toEqual([]);
    });
  }
});

// -----------------------------------------------------------------------------
// zh-TW baseline：同樣流程但預期 CJK > 0（證明 regex 真的會抓到）
// -----------------------------------------------------------------------------
test.describe('i18n zh-TW baseline: regex sanity check', () => {
  test('[zh-TW] select-complaint should contain CJK (sanity for regex)', async ({ page }) => {
    await setLngBeforeLoad(page, 'zh-TW');
    await installApiMocks(page);

    await page.goto('/zh-TW/patient/start');
    await page.waitForLoadState('networkidle');

    await page.screenshot({ path: screenshotPath('zh', 'select-complaint'), fullPage: true });

    const cjkChars = await collectCjkChars(page);
    expect(
      cjkChars.length,
      'zh-TW baseline must contain CJK chars — if this fails, the regex or the page failed to load.',
    ).toBeGreaterThan(0);
  });
});
