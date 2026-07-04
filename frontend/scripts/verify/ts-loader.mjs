// =============================================================================
// F7 稽核修復（auth 三條 low）驗證用的最小 ESM resolve/load hook。
//
// 目的：讓 plain Node（無 tsx / ts-node，本任務規則不可改 package.json 裝新
// devDependency）能直接 import 專案的 .ts 原始碼跑驗證，而不是重寫一份邏輯
// 來測——這樣才抓得到真正檔案的回歸。搭配 Node 22+ 內建的 TypeScript
// type-stripping（`--experimental-strip-types`，Node 23.6+/24 起可能免旗標）。
//
// 用法（在 frontend/scripts/verify/ 目錄下）：
//   node --experimental-strip-types --import ./register.mjs <test-file>.mjs
//
// 這個 hook 做兩件 Node 原生 ESM 沒有、但 Vite/bundler 有的事：
//   1. 相對 import 缺副檔名時補 .ts / .tsx / /index.ts（TS 原始碼慣例）。
//   2. `import.meta.env.*`（Vite 專有）轉譯成 `globalThis.__IMPORT_META_ENV__.*`，
//      測試腳本可預先塞好需要的環境變數值。
//
// 不處理：瀏覽器全域（window / document / localStorage / WebSocket）一律由
// 個別測試腳本自行 stub，保持這支 loader 通用、不綁死特定模組的假設。
//
// 唯一的例外：client.ts 的 `import i18n, { SUPPORTED_LANGUAGES } from '../../i18n'`。
// 真正的 src/i18n/index.ts 會即時 `void i18next.use(HttpBackend)...init(...)`
// （fire-and-forget，未 await），若在 Node 這個 promise chain 中途對瀏覽器 API
// （fetch 相對路徑、navigator 等）拋錯，會變成 unhandled rejection —— Node 預設
// 對 unhandled rejection 是直接終止行程，會讓驗證腳本整個爆掉。因此改導向一顆
// 只提供 client.ts 需要的形狀（`default.resolvedLanguage` / `SUPPORTED_LANGUAGES`）
// 的內建 stub，不碰真正的 i18next 初始化。
// =============================================================================

const STUB_I18N_URL = 'f7-verify-stub:i18n';

export async function resolve(specifier, context, nextResolve) {
  if (specifier === '../../i18n' && context.parentURL?.endsWith('/services/api/client.ts')) {
    return { url: STUB_I18N_URL, shortCircuit: true };
  }
  try {
    return await nextResolve(specifier, context);
  } catch (err) {
    if (specifier.startsWith('.') || specifier.startsWith('/')) {
      for (const suffix of ['.ts', '.tsx', '/index.ts', '/index.tsx']) {
        try {
          return await nextResolve(specifier + suffix, context);
        } catch {
          /* try next suffix */
        }
      }
    }
    throw err;
  }
}

export async function load(url, context, nextLoad) {
  if (url === STUB_I18N_URL) {
    return {
      format: 'module',
      shortCircuit: true,
      source: `
        export const SUPPORTED_LANGUAGES = ['zh-TW', 'en-US', 'ja-JP', 'ko-KR', 'vi-VN'];
        export default { resolvedLanguage: 'zh-TW', language: 'zh-TW' };
      `,
    };
  }

  const result = await nextLoad(url, context);

  if (url.endsWith('.ts') || url.endsWith('.tsx')) {
    const src = typeof result.source === 'string' ? result.source : result.source?.toString('utf8');
    if (src && src.includes('import.meta.env')) {
      return {
        ...result,
        source: src.replaceAll('import.meta.env', 'globalThis.__IMPORT_META_ENV__'),
      };
    }
  }
  return result;
}
