// =============================================================================
// LanguageLayout — URL 語言前綴守衛
// 讀 `/:lng/*` 的 lng，驗證 → 同步 i18next / <html lang> / hreflang links。
// 未支援的 lng 會導去偵測到的預設語系。
// =============================================================================

import { useEffect } from 'react';
import { Navigate, Outlet, useLocation, useParams } from 'react-router-dom';

import i18n, { SUPPORTED_LANGUAGES, type SupportedLanguage } from '../../i18n';
import {
  detectInitialLanguage,
  isSupportedLanguage,
  stripLngFromPath,
} from '../../i18n/paths';

export default function LanguageLayout() {
  const { lng } = useParams<{ lng?: string }>();
  const location = useLocation();
  const valid = isSupportedLanguage(lng);
  const activeLng: SupportedLanguage | null = valid ? (lng as SupportedLanguage) : null;

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
