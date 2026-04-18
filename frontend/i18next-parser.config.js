// =============================================================================
// i18next-parser 設定檔
//
// 用途：
//   - 掃 `src/**/*.{ts,tsx}` 所有 t() / i18next.t() / <Trans> 呼叫，
//     把「code 裡引用到、但 JSON locale 還沒寫」的 key 補成缺值條目，
//     作為 A7 「extract 缺 key 清單」流程的工具。
//
// 和 A8 (scripts/check_translations.py) 的分工：
//   - 本工具（parser）：檢查 CODE 有 t() 但 JSON 缺 key — caller side
//   - A8（check_translations）：檢查 zh-TW 有 key 但其他 locale 缺 — translator side
//   互補不重疊。
//
// 絕對不改既有 JSON 內容（零破壞）：
//   - `keepRemoved: true` 不刪 dynamic key（例如 `t(\`foo.${var}\`)`）
//   - `createOldCatalogs: false` 不產生 _old 備份檔
//   - `defaultValue` 對 zh-TW 回傳 key 本身、其他 locale 回傳空字串 —
//     這樣若真有缺 key，補進 JSON 後 A8 會在非 zh-TW locale 抓到空字串並報缺譯。
//
// CLI：
//   - `npm run i18n:extract`        — dry run（不實際寫 JSON，用 /tmp 暫存）
//   - `npm run i18n:extract:check`  — CI mode，遇缺 key warning 直接 exit 1
//
// i18next-parser v9 CLI binary 名稱是 `i18next`（套件 bin 對到 dist/cli.js）。
// =============================================================================

export default {
  // --- locale 清單：與 src/i18n/index.ts 的 SUPPORTED_LANGUAGES 一致 ------
  locales: ['zh-TW', 'en-US', 'ja-JP', 'ko-KR', 'vi-VN'],

  // --- namespace 與 key 分隔符 ------------------------------------------
  // 與 i18next 預設一致；t('common:save') → namespace=common, key=save
  defaultNamespace: 'common',
  namespaceSeparator: ':',
  keySeparator: '.',
  // 關閉 plural 自動展開：本專案 pluralization 策略用 `{{count}}` interpolation
  // 而非 `_one` / `_other` 變體，若保留預設 parser 會把每個帶 `{ count }` 的 t()
  // 展開成 `x_one` / `x_other` 兩 key，跟既有 JSON 的單 key `x: "{{count}} 則"`
  // 不一致，導致 check 誤報缺 key。
  pluralSeparator: false,

  // --- 掃描範圍 ----------------------------------------------------------
  // 略過 *.test.*（測試輔助 t() 不需要 extract）、型別宣告檔。
  input: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.test.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/**/__tests__/**',
  ],

  // --- 輸出 ------------------------------------------------------------
  // $LOCALE / $NAMESPACE 會被 parser 替換。為避免污染真實 source of truth
  // （frontend/src/i18n/locales/），預設寫到 /tmp 的臨時目錄 — 只驗證工具
  // 本身能跑、抓到哪些 key。若未來要正式寫回，可用 env I18N_EXTRACT_REAL=1
  // 切換（另開 `i18n:extract:write` script 包裝）。
  output:
    process.env.I18N_EXTRACT_REAL === '1'
      ? 'src/i18n/locales/$LOCALE/$NAMESPACE.json'
      : '/tmp/urosense-i18n-extract/$LOCALE/$NAMESPACE.json',

  // --- 不改既有 JSON 的關鍵選項 ----------------------------------------
  createOldCatalogs: false, // 不建 _old.json 備份
  keepRemoved: true,        // 不刪既有 key（保護 dynamic key — e.g. t(`foo.${x}`))
  sort: true,               // alphabetical 排序（穩定 diff）
  resetDefaultValueLocale: null, // 不因為 zh-TW 改值就重寫所有 locale

  // --- default value ---------------------------------------------------
  // - zh-TW: key 本身 → 方便工程師翻譯（至少看得懂原意）
  // - 其他 locale: '' → A8 check_translations 會把空字串也算缺譯，讓 CI 抓到
  defaultValue: (locale, _ns, key) => (locale === 'zh-TW' ? key : ''),

  // --- lexers：交給 parser 的預設（tsx / ts / js / jsx 都有內建）------
  // 沒覆寫就是用 default；i18next-parser v9 預設支援 TypeScript 與 JSX。

  // --- 其他 ------------------------------------------------------------
  verbose: true,                 // 列出新 key 細節
  failOnWarnings: false,         // 用 CLI --fail-on-warnings 控（check 模式才開）
  failOnUpdate: false,           // 同上；保留預設 false
  useKeysAsDefaultValue: false,  // 已用自訂 defaultValue function
  skipDefaultValues: false,
  indentation: 2,
  lineEnding: 'auto',
};
