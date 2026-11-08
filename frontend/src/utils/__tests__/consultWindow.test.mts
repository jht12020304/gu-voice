import assert from 'node:assert/strict';
import { test } from 'node:test';
import { consultWindow } from '../consultWindow.ts';

test('場次欄位優先，缺值用逐字稿頭尾補', () => {
  const turns = ['2026-11-08T01:00:30Z', null, '2026-11-08T01:07:05Z'];
  assert.equal(consultWindow(null, turns).seconds, 395);
  assert.equal(consultWindow({ durationSeconds: 590, startedAt: '2026-11-08T01:00:00Z' }, turns).seconds, 590);
  assert.equal(consultWindow({ startedAt: '2026-11-08T01:00:00Z' }, turns).start, Date.parse('2026-11-08T01:00:00Z'));
  assert.equal(consultWindow(undefined, []).seconds, undefined);
});
