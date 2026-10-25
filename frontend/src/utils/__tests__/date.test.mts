// =============================================================================
// 單元測試：utils/date 本地日／月工具
//
// 守護的行為（CLAUDE.md 鐵律）：依日期分組／篩選一律用**裝置本地日**分桶，
// 跨午夜的 ISO 時間戳必須落在本地日而不是 UTC 日；月區間要帶本地時區位移。
//
// 執行方式：cd frontend && npm test（或 node --experimental-strip-types
//   --import ./scripts/verify/register.mjs src/utils/__tests__/date.test.mts）
// =============================================================================

import assert from 'node:assert/strict';
import { addMonths, dayLabel, localDayBounds, localDayKey, localMonthRange, monthKey, monthRangeLabel } from '../date.ts';

const tzOffsetMin = new Date(2026, 0, 15).getTimezoneOffset();

// ── 1. localDayKey：跨午夜邊界用本地日（不是 UTC 日）─────────────────────────
{
  // 本地 2026-03-01 00:00:30 → 不論裝置時區，key 必須是本地的 03-01
  const justAfterMidnight = new Date(2026, 2, 1, 0, 0, 30);
  assert.equal(localDayKey(justAfterMidnight.toISOString()), '2026-03-01');
  // 本地 2026-02-28 23:59:30 → 02-28
  const justBeforeMidnight = new Date(2026, 1, 28, 23, 59, 30);
  assert.equal(localDayKey(justBeforeMidnight.toISOString()), '2026-02-28');
  // 兩者的 UTC 日在非 UTC 時區會不同於本地日——確認我們沒有拿 UTC 日
  if (tzOffsetMin !== 0) {
    const utcDay = justAfterMidnight.toISOString().slice(0, 10);
    const localDay = localDayKey(justAfterMidnight);
    assert.ok(utcDay !== localDay || tzOffsetMin > 0, 'expected local-day bucketing to differ from UTC slice');
  }
  assert.equal(localDayKey('not-a-date'), 'unknown');
  assert.equal(localDayKey(new Date(2026, 11, 5)), '2026-12-05');
}

// ── 2. localMonthRange / monthRangeLabel ─────────────────────────────────────
{
  const { start, end } = localMonthRange('2026-02');
  assert.equal(start.getTime(), new Date(2026, 1, 1, 0, 0, 0, 0).getTime());
  assert.equal(end.getTime(), new Date(2026, 1, 28, 23, 59, 59, 999).getTime());
  // 閏年
  assert.equal(localMonthRange('2028-02').end.getDate(), 29);
  // 12 月的月末不可溢到隔年
  assert.equal(localMonthRange('2026-12').end.getTime(), new Date(2026, 11, 31, 23, 59, 59, 999).getTime());
  assert.equal(monthRangeLabel('2026-02'), '2026/02/01 - 2026/02/28');
  assert.equal(monthKey(new Date(2026, 0, 31)), '2026-01');
  // toISOString 帶時區位移：在 +08:00 的 2026-02-01 00:00 本地 = 2026-01-31T16:00Z
  assert.equal(start.toISOString(), new Date(Date.UTC(2026, 1, 1, 0, 0, 0, 0) + tzOffsetMin * 60_000).toISOString());
}

// ── 3. localDayBounds ────────────────────────────────────────────────────────
{
  const { start, end } = localDayBounds('2026-10-24');
  assert.equal(start.getTime(), new Date(2026, 9, 24, 0, 0, 0, 0).getTime());
  assert.equal(end.getTime(), new Date(2026, 9, 24, 23, 59, 59, 999).getTime());
}

// ── 4. addMonths 夾日 ────────────────────────────────────────────────────────
{
  assert.equal(monthKey(addMonths(new Date(2026, 0, 31), 1)), '2026-02');
  assert.equal(addMonths(new Date(2026, 0, 31), 1).getDate(), 28);
  assert.equal(monthKey(addMonths(new Date(2026, 0, 15), -1)), '2025-12');
  assert.equal(monthKey(addMonths(new Date(2026, 11, 15), 1)), '2027-01');
}

// ── 5. dayLabel 依 locale 輸出 ───────────────────────────────────────────────
{
  const label = dayLabel('2026-03-01T00:00:00', 'en-US');
  assert.match(label, /Sunday/);
  assert.match(label, /March 1, 2026/);
  assert.equal(dayLabel('garbage', 'en-US'), '-');
}

console.log('date.test.mts: all assertions passed');
