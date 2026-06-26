// =============================================================================
// 單元測試：PcmRingBuffer（純函式，無 DOM / mic）
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/services/__tests__/pcmRingBuffer.test.mts
// =============================================================================

import assert from 'node:assert/strict';
import { PcmRingBuffer } from '../pcmRingBuffer.ts';

// 1) 未滿時 readLast 取得全部、順序正確
{
  const r = new PcmRingBuffer(10);
  r.write(new Float32Array([1, 2, 3]));
  assert.equal(r.available(), 3);
  assert.deepEqual(Array.from(r.readLast(10)), [1, 2, 3], 'returns all when fewer than n');
  assert.deepEqual(Array.from(r.readLast(2)), [2, 3], 'returns the most recent n, oldest→newest');
}

// 2) 超過容量 → 環形覆蓋最舊，只保留最近 capacity 個
{
  const r = new PcmRingBuffer(4);
  r.write(new Float32Array([1, 2, 3, 4, 5, 6]));
  assert.equal(r.available(), 4, 'capped at capacity');
  assert.deepEqual(Array.from(r.readLast(4)), [3, 4, 5, 6], 'keeps most recent 4 in order');
  assert.deepEqual(Array.from(r.readLast(2)), [5, 6], 'most recent 2');
}

// 3) 跨多次 write 的環形邊界正確（wrap 後順序不亂）
{
  const r = new PcmRingBuffer(3);
  r.write(new Float32Array([1, 2]));
  r.write(new Float32Array([3, 4])); // 覆蓋掉 1 → 內容 [2,3,4]
  assert.deepEqual(Array.from(r.readLast(3)), [2, 3, 4], 'wrap preserves time order');
  r.write(new Float32Array([5])); // → [3,4,5]
  assert.deepEqual(Array.from(r.readLast(3)), [3, 4, 5]);
}

// 4) readLast(0) 與空緩衝
{
  const r = new PcmRingBuffer(5);
  assert.equal(r.readLast(3).length, 0, 'empty buffer → empty read');
  r.write(new Float32Array([9]));
  assert.equal(r.readLast(0).length, 0, 'readLast(0) → empty');
}

// 5) clear 後歸零
{
  const r = new PcmRingBuffer(4);
  r.write(new Float32Array([1, 2, 3]));
  r.clear();
  assert.equal(r.available(), 0, 'cleared');
  assert.equal(r.readLast(4).length, 0, 'cleared read empty');
  r.write(new Float32Array([7, 8]));
  assert.deepEqual(Array.from(r.readLast(4)), [7, 8], 'usable after clear');
}

// 6) 防呆：非法 capacity 丟例外
{
  assert.throws(() => new PcmRingBuffer(0), 'capacity 0 rejected');
  assert.throws(() => new PcmRingBuffer(-3), 'negative rejected');
  assert.throws(() => new PcmRingBuffer(2.5), 'non-integer rejected');
}

console.log('pcmRingBuffer.test.mts — all assertions passed');
