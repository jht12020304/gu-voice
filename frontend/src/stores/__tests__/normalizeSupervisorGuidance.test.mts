// =============================================================================
// CONV-2 單元測試：normalizeSupervisorGuidance
// 純函式測試，無 DOM / store / 網路依賴。
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/stores/__tests__/normalizeSupervisorGuidance.test.mts
// =============================================================================

import assert from 'node:assert/strict';
import { normalizeSupervisorGuidance } from '../conversationStore.ts';

// 1) null / undefined → null
assert.equal(normalizeSupervisorGuidance(null), null, 'null payload → null');
assert.equal(normalizeSupervisorGuidance(undefined), null, 'undefined payload → null');

// 2) 完整 snake_case payload → camelCase 正規化
{
  const g = normalizeSupervisorGuidance({
    next_focus: '請問血尿是整泡都紅還是只有最後一段？',
    missing_hpi: ['severity', 'associated_symptoms'],
    hpi_completion_percentage: 40,
  });
  assert.ok(g, 'should produce a guidance object');
  assert.equal(g!.nextFocus, '請問血尿是整泡都紅還是只有最後一段？');
  assert.deepEqual(g!.missingHpi, ['severity', 'associated_symptoms']);
  assert.equal(g!.hpiCompletionPercentage, 40);
  assert.equal(g!.fallback, false, 'fallback defaults to false when absent');
}

// 3) 缺欄位 → 安全預設（空字串 / 空陣列 / 0）
{
  const g = normalizeSupervisorGuidance({});
  assert.ok(g);
  assert.equal(g!.nextFocus, '');
  assert.deepEqual(g!.missingHpi, []);
  assert.equal(g!.hpiCompletionPercentage, 0);
  assert.equal(g!.fallback, false);
}

// 4) fallback payload（後端 supervisor 逾時）→ fallback 旗標保留
{
  const g = normalizeSupervisorGuidance({
    next_focus: 'supervisor unavailable, continuing with default guidance',
    missing_hpi: [],
    hpi_completion_percentage: 0,
    fallback: true,
  });
  assert.ok(g);
  assert.equal(g!.fallback, true, 'fallback flag preserved');
}

// 5) missing_hpi 非陣列（防禦性）→ 退回空陣列
{
  const g = normalizeSupervisorGuidance({
    next_focus: 'x',
    missing_hpi: undefined,
    hpi_completion_percentage: undefined,
  });
  assert.ok(g);
  assert.deepEqual(g!.missingHpi, []);
  assert.equal(g!.hpiCompletionPercentage, 0);
}

console.log('PASS normalizeSupervisorGuidance.test.mts (5 cases)');
