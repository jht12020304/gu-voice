// =============================================================================
// useWsMessageRenderer — 將 canonical WSLocalizedPayload 以 i18next 渲染。
//
// 切語言時能「自動重渲染」的關鍵：上層元件把收到的 `{code, params}` 存成
// state（**不存 rendered string**），在 render time 用 `t(code, params)`；
// `useTranslation('ws')` 會訂閱 i18n.language 變動，切語言時元件自動 re-render
// 並得到新語言字串。
// =============================================================================

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';

import type { WSLocalizedPayload } from './types';

/**
 * 將 canonical payload 轉成當前語言的字串（不快取）。
 * 推薦在 render 中呼叫；切語言時自動重算。
 */
export function useWsMessageRenderer() {
  const { t, i18n } = useTranslation('ws');

  const render = useCallback(
    (payload: WSLocalizedPayload | null | undefined): string => {
      if (!payload || !payload.code) return '';
      // i18next 的 t() 若 key 不存在會回傳 key 本身；ns 已由 useTranslation 綁定。
      return t(payload.code, {
        ...(payload.params ?? {}),
        defaultValue: payload.code,
      }) as string;
    },
    [t],
  );

  return { render, language: i18n.language };
}
