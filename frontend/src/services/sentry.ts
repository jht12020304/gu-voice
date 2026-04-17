// =============================================================================
// Sentry 初始化 + PII 過濾（TODO P1-#9）
// =============================================================================
// - 未設 VITE_SENTRY_DSN 時靜默跳過，允許本機 / mock 開發不啟用
// - beforeSend 移除事件中常見敏感欄位（密碼 / JWT / Authorization header）

import * as Sentry from '@sentry/react';

const SENSITIVE_KEY_FRAGMENTS = [
  'password',
  'access_token',
  'refresh_token',
  'authorization',
  'api_key',
  'api-key',
  'secret',
  'jwt',
  'cookie',
  'set-cookie',
];

function isSensitiveKey(key: string): boolean {
  const lower = key.toLowerCase();
  return SENSITIVE_KEY_FRAGMENTS.some((frag) => lower.includes(frag));
}

function redact(node: unknown): unknown {
  if (node === null || node === undefined) return node;
  if (Array.isArray(node)) return node.map(redact);
  if (typeof node === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      out[k] = isSensitiveKey(k) ? '[Filtered]' : redact(v);
    }
    return out;
  }
  return node;
}

export function initSentry(): boolean {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  const env = import.meta.env.VITE_APP_ENV || 'development';

  if (!dsn) {
    // 不 throw、不 console.error：本機開發 / mock 模式常態沒設
    return false;
  }

  Sentry.init({
    dsn,
    environment: env,
    tracesSampleRate: 0.1,
    sendDefaultPii: false,
    beforeSend(event) {
      return redact(event) as typeof event;
    },
    beforeBreadcrumb(breadcrumb) {
      return redact(breadcrumb) as typeof breadcrumb;
    },
  });

  return true;
}

// 供測試 import
export const _redact = redact;
