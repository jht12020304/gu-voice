// =============================================================================
// F7 #1 驗證：/auth/logout 的 401 自動重試不得重放已被 refreshAccessToken()
// 輪換掉的舊 refresh token；重試 body 必須帶「當下」localStorage 的新 token。
//
// 直接 import 專案真正的 src/services/api/client.ts（透過 ts-loader.mjs 的
// resolve/load hook 讓 plain Node 能跑 TS 原始碼），不是重寫一份邏輯來測
// ——這樣才抓得到 client.ts 本身的回歸。
//
// 執行方式（本檔案所在目錄）：
//   node --experimental-strip-types --import ./register.mjs auth-logout-retry.test.mjs
// =============================================================================

import assert from 'node:assert/strict';
import axios from 'axios';

globalThis.localStorage = (() => {
  const store = new Map();
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
    clear: () => store.clear(),
  };
})();
globalThis.window = { location: { pathname: '/', href: 'http://localhost/' } };
globalThis.document = { cookie: '' };
globalThis.__IMPORT_META_ENV__ = { VITE_API_BASE_URL: 'http://api.test/api/v1' };

const { default: apiClient } = await import('../../src/services/api/client.ts');

// ── 初始狀態：使用者已登入，持有「舊」access/refresh token ──────────
localStorage.setItem('access_token', 'access-old');
localStorage.setItem('refresh_token', 'R1');

const calls = [];

function parseBody(data) {
  if (data == null) return {};
  if (typeof data === 'string') return data ? JSON.parse(data) : {};
  return data;
}

/** 自訂 axios adapter：完全不碰網路，模擬後端 /auth/logout + /auth/refresh 行為。 */
async function fakeAdapter(config) {
  const url = config.url || '';
  const auth = config.headers?.Authorization ?? config.headers?.get?.('Authorization');
  const body = parseBody(config.data);
  calls.push({ url, auth, body: { ...body } });

  const respond = (status, data) => ({
    data,
    status,
    statusText: String(status),
    headers: {},
    config,
    request: {},
  });

  if (url.includes('/auth/logout')) {
    if (auth === 'Bearer access-old') {
      // 第一次呼叫：access token 已過期 → 401（觸發攔截器 refresh + retry）
      const err = new Error('Request failed with status code 401');
      err.response = respond(401, { error: { message: 'unauthorized' } });
      err.config = config;
      err.isAxiosError = true;
      throw err;
    }
    // 重試呼叫：access token 已是新的 → 200
    return respond(200, { message: 'logged out' });
  }

  if (url.includes('/auth/refresh')) {
    assert.equal(
      body.refresh_token,
      'R1',
      'refresh 呼叫應帶「當下」localStorage 的 refresh token（R1）',
    );
    // 後端 rotation：R1 -> R2
    return respond(200, { access_token: 'access-new', refresh_token: 'R2' });
  }

  throw new Error(`未預期的請求：${url}`);
}

apiClient.defaults.adapter = fakeAdapter;
axios.defaults.adapter = fakeAdapter; // refreshAccessToken() 內部用裸 axios 呼叫 /auth/refresh

// ── 觸發：呼叫 logout（比照 frontend/src/services/api/auth.ts 的 logout()）──
const resp = await apiClient.post('/auth/logout', {
  refreshToken: localStorage.getItem('refresh_token'),
});
assert.equal(resp.status, 200, 'logout 重試後應成功（200）');

const logoutCalls = calls.filter((c) => c.url.includes('/auth/logout'));
assert.equal(logoutCalls.length, 2, '應該恰好發生兩次 logout 呼叫（原始 401 + 401-retry 一次）');

assert.equal(
  logoutCalls[0].body.refresh_token,
  'R1',
  '第一次 logout 呼叫帶的是使用者原本持有的 R1（符合預期，非本次修復重點）',
);

// ★ 核心斷言（F7 #1 的修復點）：retry 呼叫必須帶「輪換後的新」refresh token（R2），
// 不能重放已經被消耗掉的舊 token（R1）——否則新 token 永遠不會被撤銷，
// 使用者「登出」後該 refresh token 仍可用來換發新 session 到 7 天後才過期。
assert.equal(
  logoutCalls[1].body.refresh_token,
  'R2',
  'retry 的 logout 呼叫必須帶「當下」localStorage 的新 refresh token（R2），不可重放已輪換掉的 R1',
);

assert.equal(
  localStorage.getItem('access_token'),
  'access-new',
  'refresh 後 localStorage 的 access token 應更新',
);
assert.equal(
  localStorage.getItem('refresh_token'),
  'R2',
  'refresh 後 localStorage 的 refresh token 應旋轉為 R2',
);

console.log(
  'PASS: logout 401-retry 使用當下最新 refresh token 重建 body（不重放已輪換的舊 token）',
);

// 斷言全數通過即成功收場。client.ts 的動態 import（authStore → 真 i18n）會在
// Node stub 環境留下與本驗證無關的非同步 unhandled rejection，不主動 exit(0)
// 會讓行程以非零碼收尾、被 CI 誤判失敗。
process.exit(0);
