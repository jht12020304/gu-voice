#!/usr/bin/env node
// =============================================================================
// i18n extract check — 比對 code 裡 t() 呼叫 vs 既有 locale JSON
//
// 做什麼：
//   1. 跑 i18next-parser，把「code 裡所有 t() key」extract 到 /tmp/urosense-i18n-extract/
//      （keepRemoved:true + defaultValue='' → tmp 版含所有被 parse 到的 key）
//   2. 讀 src/i18n/locales/zh-TW/<ns>.json（source of truth）
//   3. Diff：tmp 有、source 沒的 key → 「code 呼叫了但 JSON 缺的 key」
//   4. 有缺 key → exit 1 並列出；沒有 → exit 0
//
// 為何不直接用 parser --fail-on-update：
//   parser 的 --fail-on-update 會「先實際寫入 source，再 exit 1」，會污染
//   既有翻譯 JSON（本次明確要求不改 JSON）。所以改寫到 tmp + 自行 diff。
//
// 用法：
//   npm run i18n:extract:check           # CI mode，缺 key 則 exit 1
// =============================================================================

import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = resolve(__dirname, '..');
const TMP_DIR = '/tmp/urosense-i18n-extract';
const SOURCE_DIR = join(FRONTEND_ROOT, 'src/i18n/locales/zh-TW');
const TMP_ZH_DIR = join(TMP_DIR, 'zh-TW');

// Step 1 — 跑 parser 寫入 /tmp
const parseResult = spawnSync(
  'node',
  [
    join(FRONTEND_ROOT, 'node_modules/.bin/i18next'),
    '--config',
    join(FRONTEND_ROOT, 'i18next-parser.config.js'),
    '--silent',
  ],
  {
    cwd: FRONTEND_ROOT,
    stdio: ['inherit', 'pipe', 'inherit'],
    env: { ...process.env },
  },
);

if (parseResult.status !== 0) {
  console.error('[i18n:extract:check] parser 執行失敗');
  process.exit(parseResult.status ?? 2);
}

// Step 2 — 展開 JSON 成 flat key 集合
function flatten(obj, prefix = '') {
  const out = new Set();
  for (const [k, v] of Object.entries(obj ?? {})) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      for (const nested of flatten(v, key)) out.add(nested);
    } else {
      out.add(key);
    }
  }
  return out;
}

function loadJsonSafe(path) {
  if (!existsSync(path)) return {};
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch (err) {
    console.error(`[i18n:extract:check] 無法解析 ${path}: ${err.message}`);
    return {};
  }
}

// 只比對 zh-TW（source of truth）。其他 locale 的缺譯交給 A8 check_translations.py
if (!existsSync(TMP_ZH_DIR)) {
  console.error(`[i18n:extract:check] 找不到 parser 產物：${TMP_ZH_DIR}`);
  process.exit(2);
}

const missing = {}; // namespace → Set(keys)
const namespaces = readdirSync(TMP_ZH_DIR)
  .filter((f) => f.endsWith('.json'))
  .map((f) => f.replace(/\.json$/, ''));

for (const ns of namespaces) {
  const tmpKeys = flatten(loadJsonSafe(join(TMP_ZH_DIR, `${ns}.json`)));
  const sourceKeys = flatten(loadJsonSafe(join(SOURCE_DIR, `${ns}.json`)));
  const missingInSource = [...tmpKeys].filter((k) => !sourceKeys.has(k));
  if (missingInSource.length > 0) {
    missing[ns] = missingInSource.sort();
  }
}

const totalMissing = Object.values(missing).reduce((sum, arr) => sum + arr.length, 0);

if (totalMissing === 0) {
  console.log('[i18n:extract:check] PASS — 所有 t() 呼叫的 key 都已在 zh-TW locale JSON 裡');
  process.exit(0);
}

console.error(`[i18n:extract:check] FAIL — 發現 ${totalMissing} 個 t() 呼叫沒有對應 zh-TW JSON key\n`);
for (const [ns, keys] of Object.entries(missing)) {
  console.error(`  [${ns}] 缺 ${keys.length} 個 key：`);
  for (const k of keys) console.error(`    - ${k}`);
}
console.error(
  '\n處理方式：在 frontend/src/i18n/locales/zh-TW/<namespace>.json 補上對應 key 與翻譯，',
);
console.error('其他 locale 會由 A8 `scripts/check_translations.py` 的 CI 檢查追蹤。');
process.exit(1);
