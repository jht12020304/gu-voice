// =============================================================================
// 單元測試：wavEncoder（純函式，無 DOM / mic）
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/services/__tests__/wavEncoder.test.mts
// =============================================================================

import assert from 'node:assert/strict';
import { encodeWav, arrayBufferToBase64 } from '../wavEncoder.ts';

const ascii = (view: DataView, off: number, len: number): string => {
  let s = '';
  for (let i = 0; i < len; i++) s += String.fromCharCode(view.getUint8(off + i));
  return s;
};

// 1) header 結構正確 + 通過後端 magic（開頭 "RIFF"）
{
  const frames = [new Float32Array([0, 0.5, -0.5, 1, -1])];
  const buf = encodeWav(frames, 16000);
  const view = new DataView(buf);

  assert.equal(ascii(view, 0, 4), 'RIFF', 'starts with RIFF (backend _has_valid_audio_magic)');
  assert.equal(ascii(view, 8, 4), 'WAVE', 'WAVE tag');
  assert.equal(ascii(view, 12, 4), 'fmt ', 'fmt subchunk');
  assert.equal(ascii(view, 36, 4), 'data', 'data subchunk');

  const dataBytes = 5 * 2; // 5 samples × 16-bit
  assert.equal(buf.byteLength, 44 + dataBytes, 'total size = 44 header + data');
  assert.equal(view.getUint32(4, true), 36 + dataBytes, 'RIFF chunk size = 36 + dataBytes');
  assert.equal(view.getUint32(40, true), dataBytes, 'data subchunk size');
  assert.equal(view.getUint16(20, true), 1, 'PCM format = 1');
  assert.equal(view.getUint16(22, true), 1, 'mono');
  assert.equal(view.getUint32(24, true), 16000, 'sample rate echoed');
  assert.equal(view.getUint16(34, true), 16, '16 bits per sample');
  assert.equal(view.getUint32(28, true), 16000 * 2, 'byte rate = rate × blockAlign');
}

// 2) 取樣率忠實寫入（防變調 — 實機可能 48000）
{
  const buf = encodeWav([new Float32Array([0])], 48000);
  const view = new DataView(buf);
  assert.equal(view.getUint32(24, true), 48000, 'actual sample rate must be honored');
  assert.equal(view.getUint32(28, true), 48000 * 2, 'byte rate tracks actual rate');
}

// 3) Float32 → int16 量化 + clamp（防爆音溢位）
{
  const buf = encodeWav([new Float32Array([0, 1, -1, 2, -2])], 16000);
  const view = new DataView(buf);
  assert.equal(view.getInt16(44, true), 0, '0 → 0');
  assert.equal(view.getInt16(46, true), 0x7fff, '+1 → 0x7FFF');
  assert.equal(view.getInt16(48, true), -0x8000, '-1 → -0x8000');
  assert.equal(view.getInt16(50, true), 0x7fff, '+2 clamps to +1 → 0x7FFF');
  assert.equal(view.getInt16(52, true), -0x8000, '-2 clamps to -1 → -0x8000');
}

// 4) 多段 frames 串接：總樣本數 = 各段相加
{
  const buf = encodeWav([new Float32Array(3), new Float32Array(7), new Float32Array(2)], 16000);
  assert.equal(new DataView(buf).getUint32(40, true), (3 + 7 + 2) * 2, 'concatenated sample count');
}

// 5) 空輸入：仍是合法的 0-data WAV（不丟例外）
{
  const buf = encodeWav([], 16000);
  const view = new DataView(buf);
  assert.equal(buf.byteLength, 44, 'empty → header only');
  assert.equal(ascii(view, 0, 4), 'RIFF', 'empty still valid RIFF');
  assert.equal(view.getUint32(40, true), 0, 'empty data size 0');
}

// 6) base64 round-trips（送 WS 用）
{
  const buf = encodeWav([new Float32Array([0.25, -0.25])], 16000);
  const b64 = arrayBufferToBase64(buf);
  const decoded = Buffer.from(b64, 'base64');
  assert.equal(decoded.length, buf.byteLength, 'base64 decodes back to same length');
  assert.equal(decoded.toString('ascii', 0, 4), 'RIFF', 'decoded bytes still RIFF');
}

console.log('wavEncoder.test.mts — all assertions passed');
