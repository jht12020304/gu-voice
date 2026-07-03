// =============================================================================
// Axios 實例 + snake_case / camelCase 自動轉換
// =============================================================================

import axios, { type AxiosInstance, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios';

import i18n, { SUPPORTED_LANGUAGES } from '../../i18n';

// URL `/:lng/*` 是使用者目前 active 語言的權威來源 —— i18n.resolvedLanguage 讀
// localStorage，切換語言後在 i18next changeLanguage 非同步 resolve 前可能還是
// 舊值，造成 Accept-Language 與 UI 不一致（韓文 UI 卻送 ko-KR header 的情境
// 實測發生過）。這裡優先讀 URL 第一段 locale，fallback 才回 i18n。
const _SUPPORTED_SET = new Set<string>(SUPPORTED_LANGUAGES as readonly string[]);

function getLangFromUrl(): string | undefined {
  if (typeof window === 'undefined') return undefined;
  const first = window.location.pathname.split('/').filter(Boolean)[0];
  return first && _SUPPORTED_SET.has(first) ? first : undefined;
}

// ---- 深度 key 轉換工具 ----

/**
 * snake_case -> camelCase
 * 只在 `_` 後接小寫字母時轉大寫；數字段位（如 icd10_codes、audio_b64）保持原樣，
 * 後端 snake_case 是權威來源，故此方向對所有現有欄位皆 round-trip safe。
 */
function snakeToCamelKey(key: string): string {
  return key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
}

/**
 * camelCase -> snake_case
 *
 * 舊版用 `/[A-Z]/g` 對每個大寫字母前都插底線，對「連續大寫縮寫」會炸開：
 *   httpURL -> http_u_r_l、userID -> user_i_d（後端無法對應）。
 * 改用 word-boundary 規則：
 *   1. 縮寫與後接的 Capitalized 詞之間斷詞：HTMLParser -> HTML_Parser
 *   2. 小寫/數字與大寫之間斷詞：userId -> user_Id、icd10Codes -> icd10_Codes
 * 不在「數字邊界」硬插底線，故 icd10_codes / audio_b64 / spo2 等現有欄位
 * 仍精確還原為原本的 wire key（行為不變），同時 httpURL -> http_url、userID -> user_id。
 */
function camelToSnakeKey(key: string): string {
  return key
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2')
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .toLowerCase();
}

/** 遞迴轉換物件的所有 key */
function deepConvertKeys(data: unknown, converter: (key: string) => string): unknown {
  if (data === null || data === undefined) return data;
  if (Array.isArray(data)) {
    return data.map((item) => deepConvertKeys(item, converter));
  }
  if (typeof data === 'object' && !(data instanceof Date) && !(data instanceof File) && !(data instanceof Blob)) {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
      result[converter(key)] = deepConvertKeys(value, converter);
    }
    return result;
  }
  return data;
}

export function snakeToCamel<T>(data: unknown): T {
  return deepConvertKeys(data, snakeToCamelKey) as T;
}

export function camelToSnake<T>(data: unknown): T {
  return deepConvertKeys(data, camelToSnakeKey) as T;
}

// ---- Cookie 工具 ----

// M-22：refresh token 改由後端以 httpOnly cookie 下發，前端讀不到（也不該讀）。
// 但 CSRF 防護採 double-submit：後端另下發一顆「非 httpOnly」的 csrf cookie，前端讀出
// 它的值放進 X-CSRF-Token header，後端比對 cookie 值 vs header 值是否一致。此函式只用來
// 讀那顆「非 httpOnly」的 csrf cookie；httpOnly 的 refresh token 在這裡天生讀不到。
function readCookie(name: string): string | undefined {
  if (typeof document === 'undefined' || !document.cookie) return undefined;
  const prefix = `${name}=`;
  for (const part of document.cookie.split(';')) {
    const c = part.trim();
    if (c.startsWith(prefix)) {
      return decodeURIComponent(c.slice(prefix.length));
    }
  }
  return undefined;
}

// 後端下發的 CSRF cookie 名稱（必須與後端 settings.CSRF_COOKIE_NAME 一致，
// 否則讀不到 csrf cookie → X-CSRF-Token 為空 → 每次 refresh/logout 都 403）。
const CSRF_COOKIE_NAME = 'gu_csrf_token';
const CSRF_HEADER_NAME = 'X-CSRF-Token';

// 跨站部署後備：refresh token 存 localStorage（Vercel ↔ Railway 跨站時 SameSite
// cookie 不會送出，cookie 路徑不可用）。sentry.ts 已將 'refresh_token' 列入 redact。
const REFRESH_TOKEN_STORAGE_KEY = 'refresh_token';

// ---- Axios 實例 ----

const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
  timeout: 30000,
  // M-22：帶上 / 接收後端的 httpOnly cookie（refresh token、csrf token）。
  // 後端 CORS 已 allow_credentials=true 並明確列舉 origin（非 '*'），符合瀏覽器在
  // credentials 模式下的要求。
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ---- Request 攔截器：附加 Token + CSRF + camelCase -> snake_case ----

// 雙路徑 refresh：refresh token 由後端 httpOnly cookie（同站）與 localStorage（跨站後備）
// 並行持有；一般 API 請求不經手 refresh token，只有 refreshAccessToken() 會讀寫。
// access token 維持既有 localStorage + Bearer header 處理。針對會改變狀態
// 的請求附上 X-CSRF-Token（double-submit）：值讀自非 httpOnly 的 csrf cookie，由瀏覽器
// 透過 withCredentials 一併送出的 cookie 供後端比對。
const _CSRF_SAFE_METHODS = new Set(['get', 'head', 'options']);

apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 從 localStorage 取得 access token（避免循環依賴 authStore）
    const token = localStorage.getItem('access_token');
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    // CSRF：non-safe method 才需要；header 值讀自非 httpOnly 的 csrf cookie。
    // cookie 不存在（後端尚未下發 / 安全方法）就不帶，後端對沒有 cookie 的情境本就放行。
    if (config.headers && !_CSRF_SAFE_METHODS.has((config.method || 'get').toLowerCase())) {
      const csrf = readCookie(CSRF_COOKIE_NAME);
      if (csrf && !config.headers[CSRF_HEADER_NAME]) {
        config.headers[CSRF_HEADER_NAME] = csrf;
      }
    }

    // 附帶目前語言給後端 LanguageMiddleware 解析；使用 BCP-47（如 zh-TW / en-US）。
    // 次序：URL `/:lng/*`（權威）→ i18n.resolvedLanguage → i18n.language。
    // 使用者覆蓋（config.headers['Accept-Language']）仍優先，避免 WebSocket / 測試 fixture 被蓋掉。
    if (config.headers && !config.headers['Accept-Language']) {
      const lng = getLangFromUrl() || (i18n.resolvedLanguage || i18n.language);
      if (lng) {
        config.headers['Accept-Language'] = lng;
      }
    }

    // 轉換請求 body
    if (config.data && typeof config.data === 'object' && !(config.data instanceof FormData)) {
      config.data = camelToSnake(config.data);
    }

    // 轉換 query params
    if (config.params) {
      config.params = camelToSnake(config.params);
    }

    return config;
  },
  (error) => Promise.reject(error),
);

// ---- Response 攔截器：snake_case -> camelCase + 處理 401 ----

// 單一共享 refresh promise：同一個 tab 內任意併發 401 只會觸發一次 /auth/refresh。
// 後端 P1-#11 做了 rotation + reuse detection，舊 refresh token 只能用一次，
// 若前端多次並發 POST 會被 reuse detection 踢掉，這個 shared promise 就是為了防它。
let refreshPromise: Promise<string> | null = null;

function clearAuthAndRedirect(): void {
  localStorage.removeItem('access_token');
  // 雙路徑 refresh：localStorage 的 refresh_token 是跨站後備 token 的正式儲存位置
  // （httpOnly cookie 那份由後端 /auth/logout 或過期負責失效），401 / 會話失效時
  // 必須一併清除，避免殘留已被 reuse-detection 判死的舊 token。
  localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  if (typeof window !== 'undefined') {
    window.location.href = '/login';
  }
}

/**
 * 單一共享 refresh 入口（M-20 / M-22）。
 *
 * 整個 tab 內所有 refresh（response 攔截器的 401 自動重試 + authStore.refreshSession
 * 的主動續期）都必須走這支，靠 module-level `refreshPromise` 去重。後端做了 refresh
 * token rotation + reuse detection，舊 token 只能用一次；若 authStore 另開一套並發
 * POST /auth/refresh，會被 reuse detection 判定為重放而把使用者整個踢登出。故對外
 * export，讓 authStore 收斂到這個唯一入口。
 *
 * 雙路徑 refresh：同站部署由瀏覽器自動帶上後端下發的 httpOnly refresh cookie
 * （withCredentials: true）並附 X-CSRF-Token（double-submit，值讀自非 httpOnly 的
 * csrf cookie）；跨站部署（Vercel ↔ Railway）SameSite cookie 不會送出，改把
 * localStorage 的 refresh token 放進 body（後端 body 路徑免 CSRF）。成功時把新
 * access token 寫回 localStorage + authStore，並旋轉 localStorage 的 refresh token。
 */
export async function refreshAccessToken(): Promise<string> {
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
    // 使用裸 axios（非 apiClient）避免走入本檔的 request/response 攔截器，
    // 否則 refresh 失敗又會進入 401 分支造成遞迴。
    // L-22：裸 axios 不繼承 apiClient 的 timeout，明確帶 30s 避免 refresh 永遠 hang
    // 把共享 refreshPromise 卡死、後續所有 401 重試一起被阻塞。
    // M-22：裸 axios 也不繼承 apiClient 的 withCredentials，這裡明確帶上，否則
    // httpOnly 的 refresh cookie 不會被送出。CSRF header 手動補（裸 axios 不走
    // request 攔截器）；body 的 key 也因此必須直接用 snake_case refresh_token。
    const csrf = readCookie(CSRF_COOKIE_NAME);
    const headers = csrf ? { [CSRF_HEADER_NAME]: csrf } : undefined;
    const storedRefresh = localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
    const body = storedRefresh ? { refresh_token: storedRefresh } : {};
    const { data } = await axios.post<{ access_token: string; refresh_token?: string }>(
      `${baseURL}/auth/refresh`,
      body,
      { timeout: 30000, withCredentials: true, headers },
    );
    localStorage.setItem('access_token', data.access_token);
    if (data.refresh_token) {
      // rotation：舊 refresh token 已被後端消耗，必須立刻換存新的
      localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, data.refresh_token);
    }
    // 同步 authStore，讓 WS 重連 / UI 拿得到最新 token；動態 import 避免
    // client.ts ↔ authStore 靜態循環依賴。
    const { useAuthStore } = await import('../../stores/authStore');
    useAuthStore.setState({ accessToken: data.access_token });
    return data.access_token;
  })().finally(() => {
    refreshPromise = null;
  });

  return refreshPromise;
}

apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    // 轉換回應 body
    if (response.data) {
      response.data = snakeToCamel(response.data);
    }
    return response;
  },
  async (error) => {
    const originalRequest = error.config;

    // Mock 模式下不做 401 重導
    if (import.meta.env.VITE_ENABLE_MOCK === 'true') {
      return Promise.reject(error);
    }

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true;
      try {
        const newToken = await refreshAccessToken();
        originalRequest.headers = originalRequest.headers ?? {};
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        clearAuthAndRedirect();
        return Promise.reject(refreshError);
      }
    }

    // 轉換錯誤回應 body
    if (error.response?.data) {
      error.response.data = snakeToCamel(error.response.data);
    }

    return Promise.reject(error);
  },
);

// 測試 / debug 用：暴露目前 refresh 狀態（undefined 代表沒有 in-flight 的 refresh）
export function _getInflightRefresh(): Promise<string> | null {
  return refreshPromise;
}

export default apiClient;
