// =============================================================================
// LanguageLayout — URL 語言前綴守衛
// 讀 `/:lng/*` 的 lng，驗證 → 同步 i18next / <html lang> / hreflang links。
// 未支援的 lng 會導去偵測到的預設語系。
// =============================================================================

import { useEffect, useRef } from 'react';
import { Navigate, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom';

import i18n, { SUPPORTED_LANGUAGES, type SupportedLanguage } from '../../i18n';
import {
  buildSwitchedPath,
  detectInitialLanguage,
  isSupportedLanguage,
  normalizeLanguage,
  stripLngFromPath,
} from '../../i18n/paths';
import { useAuthStore } from '../../stores/authStore';

export default function LanguageLayout() {
  const { lng } = useParams<{ lng?: string }>();
  const location = useLocation();
  const valid = isSupportedLanguage(lng);
  const activeLng: SupportedLanguage | null = valid ? (lng as SupportedLanguage) : null;

  const navigate = useNavigate();
  const userId = useAuthStore((s) => s.user?.id);
  const preferredLanguage = useAuthStore((s) => s.user?.preferredLanguage);
  const appliedForUserRef = useRef<string | null>(null);

  // 偏好語言一次性套用：登入 / 還原 session 後，把 URL 導到使用者偏好語系，
  // i18n 交給下方既有的「URL → i18n」effect 同步。刻意走 URL 而非直接 changeLanguage，
  // 維持「URL 為語言唯一權威」——確保 Accept-Language（讀 URL）與畫面（讀 i18n）永遠一致。
  //
  // one-shot guard（appliedForUserRef）只在「已導到偏好語系」後才標記完成：
  //   - 若先被其他 navigation 蓋掉（如登入後 LoginPage 自己的 redirect），會在下次
  //     location 變動時再次導正，直到 activeLng === target 才落 guard；避免 ref 被提前
  //     消耗造成偏好套用失敗（login 路徑實測過的 race）。
  //   - 落 guard 後不再校正：手動切換語言不會被偏好硬拉回（persistPreference 寫入可能
  //     silently fail，連續校正會把手動選擇拉回舊偏好）。
  useEffect(() => {
    if (!userId) {
      appliedForUserRef.current = null;
      return;
    }
    if (appliedForUserRef.current === userId) return;

    const target = normalizeLanguage(preferredLanguage);
    if (!target || !activeLng) return; // 偏好或 URL lng 還沒到齊 → 先不動、也不落 guard

    if (target === activeLng) {
      appliedForUserRef.current = userId; // 已在偏好語系 → 標記完成
      return;
    }

    navigate(
      buildSwitchedPath(location.pathname, location.search, location.hash, target),
      { replace: true },
    );
  }, [
    userId,
    preferredLanguage,
    activeLng,
    location.pathname,
    location.search,
    location.hash,
    navigate,
  ]);

  // 同步 i18next
  useEffect(() => {
    if (activeLng && i18n.language !== activeLng) {
      void i18n.changeLanguage(activeLng);
    }
  }, [activeLng]);

  // 同步 <html lang>
  useEffect(() => {
    if (activeLng && typeof document !== 'undefined') {
      document.documentElement.lang = activeLng;
    }
  }, [activeLng]);

  // 動態插入 hreflang <link>，離開或路徑變動時 cleanup
  useEffect(() => {
    if (!activeLng || typeof document === 'undefined') return;

    const origin = window.location.origin;
    const restPath = stripLngFromPath(location.pathname);
    const tail = restPath === '/' ? '' : restPath;
    const search = location.search || '';

    const elements: HTMLElement[] = SUPPORTED_LANGUAGES.map((code) => {
      const link = document.createElement('link');
      link.setAttribute('rel', 'alternate');
      link.setAttribute('hreflang', code);
      link.setAttribute('href', `${origin}/${code}${tail}${search}`);
      link.setAttribute('data-i18n-hreflang', code);
      document.head.appendChild(link);
      return link;
    });

    const xDefault = document.createElement('link');
    xDefault.setAttribute('rel', 'alternate');
    xDefault.setAttribute('hreflang', 'x-default');
    xDefault.setAttribute('href', `${origin}/zh-TW${tail}${search}`);
    xDefault.setAttribute('data-i18n-hreflang', 'x-default');
    document.head.appendChild(xDefault);
    elements.push(xDefault);

    return () => {
      elements.forEach((el) => {
        if (el.parentNode) el.parentNode.removeChild(el);
      });
    };
  }, [activeLng, location.pathname, location.search]);

  if (!valid) {
    const target = detectInitialLanguage();
    const rest = stripLngFromPath(location.pathname);
    const normalized = rest === '/' ? '' : rest;
    const to = `/${target}${normalized}${location.search || ''}${location.hash || ''}`;
    return <Navigate to={to} replace />;
  }

  return <Outlet />;
}
