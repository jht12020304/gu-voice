// =============================================================================
// i18n 路徑工具 — URL 語言前綴 `/:lng/*` 相關 helpers
// 與 SUPPORTED_LANGUAGES 綁定，封裝 lng 推算、帶前綴的 navigate/href。
// =============================================================================

import { useCallback, useMemo } from 'react';
import {
  useNavigate,
  useParams,
  type NavigateOptions,
  type To,
} from 'react-router-dom';

import i18n, { SUPPORTED_LANGUAGES, type SupportedLanguage } from './index';

const DEFAULT_LANGUAGE: SupportedLanguage = 'zh-TW';

export function isSupportedLanguage(value: unknown): value is SupportedLanguage {
  return typeof value === 'string' && (SUPPORTED_LANGUAGES as readonly string[]).includes(value);
}

/**
 * 將 BCP-47 或偏好語系 normalize 回 SUPPORTED_LANGUAGES 其一；
 * 例：`zh` / `zh-Hant` → `zh-TW`，`en` / `en-GB` → `en-US`。
 */
export function normalizeLanguage(raw: string | null | undefined): SupportedLanguage | null {
  if (!raw) return null;
  if (isSupportedLanguage(raw)) return raw;
  const lower = raw.toLowerCase();
  if (lower.startsWith('zh')) return 'zh-TW';
  if (lower.startsWith('en')) return 'en-US';
  if (lower.startsWith('ja')) return 'ja-JP';
  if (lower.startsWith('ko')) return 'ko-KR';
  if (lower.startsWith('vi')) return 'vi-VN';
  return null;
}

/**
 * 啟動 / 根路徑 redirect 時使用：
 * 優先順序：i18next currentLng > localStorage['urosense:lng'] > navigator.language > DEFAULT_LANGUAGE
 */
export function detectInitialLanguage(): SupportedLanguage {
  const fromI18n = normalizeLanguage(i18n.language);
  if (fromI18n) return fromI18n;

  if (typeof window !== 'undefined') {
    try {
      const stored = normalizeLanguage(window.localStorage.getItem('urosense:lng'));
      if (stored) return stored;
    } catch {
      // localStorage 可能被禁用，忽略
    }
    const navLang = normalizeLanguage(window.navigator?.language);
    if (navLang) return navLang;
  }

  return DEFAULT_LANGUAGE;
}

/**
 * 從 pathname 取出第一段 locale；不合法則回 null。
 */
export function extractLngFromPath(pathname: string): SupportedLanguage | null {
  const first = pathname.split('/').filter(Boolean)[0];
  return isSupportedLanguage(first) ? first : null;
}

/**
 * 去掉 pathname 首段 locale，回傳剩餘 path（保證以 `/` 起頭）。
 */
export function stripLngFromPath(pathname: string): string {
  const parts = pathname.split('/').filter(Boolean);
  if (parts.length === 0) return '/';
  if (isSupportedLanguage(parts[0])) {
    const rest = parts.slice(1).join('/');
    return rest ? `/${rest}` : '/';
  }
  return pathname.startsWith('/') ? pathname : `/${pathname}`;
}

/**
 * 將一個絕對 path（以 `/` 起頭、或不帶 lng）prepend 上指定 lng。
 * 若已帶 lng 會先 strip 再接上。保留 query / hash。
 */
export function prefixLngToPath(path: string, lng: SupportedLanguage): string {
  if (!path) return `/${lng}`;
  // 保留 query / hash
  const [pathnameRaw, ...restParts] = path.split(/([?#])/);
  const tail = path.slice(pathnameRaw.length);
  const pathname = pathnameRaw || '/';
  const cleaned = stripLngFromPath(pathname.startsWith('/') ? pathname : `/${pathname}`);
  const normalized = cleaned === '/' ? '' : cleaned;
  void restParts;
  return `/${lng}${normalized}${tail}`;
}

/** 目前 URL 的 lng（讀路由 params），不存在則用 detectInitialLanguage。 */
export function useCurrentLng(): SupportedLanguage {
  const { lng } = useParams<{ lng?: string }>();
  return useMemo(() => {
    const normalized = normalizeLanguage(lng);
    return normalized ?? detectInitialLanguage();
  }, [lng]);
}

/**
 * 取代 useNavigate：
 * - string path (以 `/` 起頭) 會自動 prepend 目前 lng；
 * - 相對路徑 / 數字 delta / 物件型 To 則照舊。
 */
export function useLocalizedNavigate() {
  const navigate = useNavigate();
  const lng = useCurrentLng();

  return useCallback(
    (to: To | number, options?: NavigateOptions) => {
      if (typeof to === 'number') {
        navigate(to);
        return;
      }
      if (typeof to === 'string') {
        if (to.startsWith('/')) {
          navigate(prefixLngToPath(to, lng), options);
        } else {
          navigate(to, options);
        }
        return;
      }
      if (to && typeof to === 'object') {
        const pathname = to.pathname;
        if (pathname && pathname.startsWith('/')) {
          navigate({ ...to, pathname: prefixLngToPath(pathname, lng) }, options);
          return;
        }
      }
      navigate(to as To, options);
    },
    [navigate, lng],
  );
}

/** 給 <Link to={...}> / <Navigate to={...}> 用：把絕對 path 補 lng 前綴。 */
export function useLocalizedTo() {
  const lng = useCurrentLng();
  return useCallback((path: string) => prefixLngToPath(path, lng), [lng]);
}

/** 供 LanguageSwitcher 使用：切語言時計算新 URL（保留現有子路徑 + search + hash）。 */
export function buildSwitchedPath(
  pathname: string,
  search: string,
  hash: string,
  nextLng: SupportedLanguage,
): string {
  const rest = stripLngFromPath(pathname);
  const normalized = rest === '/' ? '' : rest;
  return `/${nextLng}${normalized}${search || ''}${hash || ''}`;
}

export { DEFAULT_LANGUAGE };
