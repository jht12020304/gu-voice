import { chromium } from '@playwright/test';
const origin = process.env.ORIGIN || 'http://127.0.0.1:4317';
const browser = await chromium.launch({ headless: true });
for (const [stored, path] of [['zh-TW', '/en-US/login'], ['en-US', '/en-US/login'], [null, '/zh-TW/login'], ['en-US', '/zh-TW/login'], ['ja-JP', '/zh-TW/dashboard']]) {
  const ctx = await browser.newContext({ locale: 'zh-TW' });
  if (stored) await ctx.addInitScript((v) => localStorage.setItem('urosense:lng', v), stored);
  const page = await ctx.newPage();
  const locales = [];
  let bytes = 0;
  page.on('response', async (r) => { const p = new URL(r.url()).pathname; if (p.startsWith('/locales/')) { locales.push(p); try { bytes += (await r.body()).length; } catch {} } });
  await page.goto(origin + path, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const byLng = {}; for (const p of locales) { const l = p.split('/')[2]; byLng[l] = (byLng[l] || 0) + 1; }
  console.log(JSON.stringify({ storedLng: stored, path, localeRequests: locales.length, byLng, localeBytes: bytes }));
  await ctx.close();
}
await browser.close();
