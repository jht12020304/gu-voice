// =============================================================================
// Axios 實例 + snake_case / camelCase 自動轉換
// =============================================================================

import axios, { type AxiosInstance, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios';

import i18n from '../../i18n';

// ---- 深度 key 轉換工具 ----

/** snake_case -> camelCase */
function snakeToCamelKey(key: string): string {
  return key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
}

/** camelCase -> snake_case */
function camelToSnakeKey(key: string): string {
  return key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
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

// ---- Axios 實例 ----

const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ---- Request 攔截器：附加 Token + camelCase -> snake_case ----

apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 從 localStorage 取得 token（避免循環依賴 authStore）
    const token = localStorage.getItem('access_token');
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    // 附帶目前語言給後端 LanguageMiddleware 解析；使用 BCP-47（如 zh-TW / en-US）。
    // 使用者覆蓋（config.headers['Accept-Language']）優先，避免 WebSocket / 測試 fixture 被蓋掉。
    if (config.headers && !config.headers['Accept-Language']) {
      const lng = (i18n.resolvedLanguage || i18n.language) as string | undefined;
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
  localStorage.removeItem('refresh_token');
  if (typeof window !== 'undefined') {
    window.location.href = '/login';
  }
}

async function refreshAccessToken(): Promise<string> {
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) {
      throw new Error('No refresh token available');
    }
    const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
    // 使用裸 axios（非 apiClient）避免走入本檔的 request/response 攔截器，
    // 否則 refresh 失敗又會進入 401 分支造成遞迴。
    const { data } = await axios.post<{ access_token: string; refresh_token: string }>(
      `${baseURL}/auth/refresh`,
      { refresh_token: refreshToken },
    );
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
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
