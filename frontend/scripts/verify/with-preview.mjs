// =============================================================================
// 在 `vite preview`（port 4317、production build、非 mock）上跑 smoothness 腳本。
//
//   npm run build && npm run verify:smoothness        # smoothness-browser.mjs
//   npm run build && npm run verify:smoothness:perf   # smoothness-performance.mjs
//
// 兩支腳本都讀 SMOOTHNESS_ORIGIN（預設 http://127.0.0.1:4317）並用 Playwright 的
// `chrome` channel（需本機裝 Google Chrome）；所有後端流量由腳本自己攔截，不需要 API。
// 結果 JSON 寫到 $SMOOTHNESS_OUTPUT（預設 /tmp）。刻意不納入 `npm test`：要先 build、
// 要真瀏覽器、跑數十秒。若 4317 已有 preview 在跑（或自行設了 SMOOTHNESS_ORIGIN）就直接用。
// =============================================================================

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';

const script = process.argv[2];
if (!script) {
  console.error('usage: node scripts/verify/with-preview.mjs <script.mjs>');
  process.exit(2);
}
if (!existsSync('dist/index.html')) {
  console.error('[with-preview] dist/ 不存在，先跑 `npm run build`');
  process.exit(2);
}

const PORT = 4317;
const origin = process.env.SMOOTHNESS_ORIGIN || `http://127.0.0.1:${PORT}`;

async function up() {
  try {
    return (await fetch(origin + '/')).ok;
  } catch {
    return false;
  }
}

let preview = null;
if (!(await up())) {
  preview = spawn('npx', ['vite', 'preview', '--port', String(PORT), '--strictPort', '--host', '127.0.0.1'], {
    stdio: 'ignore',
  });
  const deadline = Date.now() + 30_000;
  while (!(await up())) {
    if (Date.now() > deadline) {
      preview.kill();
      console.error('[with-preview] vite preview 30s 內沒起來');
      process.exit(1);
    }
    await new Promise((r) => setTimeout(r, 250));
  }
}

const child = spawn(process.execPath, [script], { stdio: 'inherit', env: { ...process.env, SMOOTHNESS_ORIGIN: origin } });
child.on('exit', (code) => {
  preview?.kill();
  process.exit(code ?? 1);
});
