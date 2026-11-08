import assert from 'node:assert/strict';
import { test } from 'node:test';
import { safeReturnTo } from '../returnTo.ts';

test('站內報告路徑原樣放行', () => {
  assert.equal(safeReturnTo('/zh-TW/reports/7f1c-uuid', 'en-US'), '/zh-TW/reports/7f1c-uuid');
  assert.equal(safeReturnTo('/ja-JP/reports', 'en-US'), '/ja-JP/reports');
});

test('其他位置一律回報告清單', () => {
  for (const bad of [undefined, null, 42, '', '//evil.example/x', 'https://evil.example', '/zh-TW/admin', '/zh-TW/reports/../x']) {
    assert.equal(safeReturnTo(bad, 'en-US'), '/en-US/reports');
  }
});
