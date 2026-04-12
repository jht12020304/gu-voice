// =============================================================================
// Axios 實例 + snake_case / camelCase 自動轉換
// =============================================================================

import axios, { type AxiosInstance, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios';

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

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
}> = [];

function processQueue(error: unknown, token: string | null = null) {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
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

    // 401 自動刷新 token
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return apiClient(originalRequest);
          })
          .catch((err) => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const refreshToken = localStorage.getItem('refresh_token');
      if (!refreshToken) {
        isRefreshing = false;
        // 清除認證資料並導向登入頁
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.location.href = '/login';
        return Promise.reject(error);
      }

      try {
        const { data } = await axios.post(
          `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'}/auth/refresh`,
          { refresh_token: refreshToken },
        );
        const newToken = data.access_token;
        const newRefreshToken = data.refresh_token;

        localStorage.setItem('access_token', newToken);
        localStorage.setItem('refresh_token', newRefreshToken);

        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        processQueue(null, newToken);
        return apiClient(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.location.href = '/login';
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    // 轉換錯誤回應 body
    if (error.response?.data) {
      error.response.data = snakeToCamel(error.response.data);
    }

    return Promise.reject(error);
  },
);

export default apiClient;
