// Count fonts.googleapis.com / fonts.gstatic.com requests (and bytes) per page on a vite preview build.
// Usage: cd frontend && node <this> <distDir> [label]
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import path from 'node:path';

// resolve @playwright/test from the frontend cwd (script lives in the scratchpad)
const { chromium } = createRequire(path.join(process.cwd(), 'package.json'))('@playwright/test');

const dist = process.argv[2];
const label = process.argv[3] || dist;
const PORT = 4318;
const origin = `http://127.0.0.1:${PORT}`;

const server = spawn('npx', ['vite', 'preview', '--outDir', dist, '--port', String(PORT), '--strictPort', '--host', '127.0.0.1'], { stdio: 'ignore' });
const deadline = Date.now() + 30_000;
while (Date.now() < deadline) {
  try { const r = await fetch(origin + '/'); if (r.ok) break; } catch { /* not up yet */ }
  await new Promise((r) => setTimeout(r, 250));
}

const browser = await chromium.launch({ headless: true });
const results = {};
try {
  for (const p of ['/en-US/login', '/ja-JP/login', '/zh-TW/login']) {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const hits = { googleapis: new Set(), gstatic: new Set() };
    const bytes = { googleapis: 0, gstatic: 0 };
    page.on('request', (req) => {
      const u = new URL(req.url());
      if (u.hostname === 'fonts.googleapis.com') hits.googleapis.add(u.href);
      if (u.hostname === 'fonts.gstatic.com') hits.gstatic.add(u.href);
    });
    page.on('response', async (resp) => {
      const u = new URL(resp.url());
      const k = u.hostname === 'fonts.googleapis.com' ? 'googleapis' : u.hostname === 'fonts.gstatic.com' ? 'gstatic' : null;
      if (!k) return;
      try { bytes[k] += (await resp.body()).length; } catch { /* ignore */ }
    });
    await page.goto(origin + p, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const families = [...hits.googleapis].map((h) => decodeURIComponent(new URL(h).searchParams.getAll('family').join('|')));
    results[p] = { googleapis: hits.googleapis.size, gstatic: hits.gstatic.size, families, bytes };
    await ctx.close();
  }
} finally {
  await browser.close();
  server.kill();
}
console.log(`== ${label}`);
for (const [p, r] of Object.entries(results)) {
  console.log(`${p}: googleapis=${r.googleapis} (${r.bytes.googleapis} B css) gstatic=${r.gstatic} (${r.bytes.gstatic} B woff2) families=[${r.families.join(' ; ')}]`);
}
