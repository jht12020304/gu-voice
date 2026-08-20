// =============================================================================
// 單元測試：resolvePatientFacing（病患端要顯示哪一份 summary / patientEducation）
//
// 守護的行為（語音管線不變式 #12 + #24）：SOAP 本體固定 zh-TW，但 summary 與
// plan.patientEducation 是病患面欄位。非中文場次若沒有可用的 patient_facing_localized，
// **不得**把中文報告內容丟給看不懂的病患，必須退回在地化通用訊息。
//
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/utils/__tests__/patientFacingReport.test.mts
// =============================================================================

import assert from 'node:assert/strict';
import { resolvePatientFacing, normalizeStringList } from '../patientFacingReport.ts';

type Arg = Parameters<typeof resolvePatientFacing>[0];

const zhReport = {
  summary: '病患主訴血尿三天，無發燒。',
  plan: { patientEducation: ['多喝水', '如廁後留意尿液顏色'] },
} as unknown as NonNullable<Arg>;

// ── 1. 有 patientFacingLocalized 且語言相符 → 用它 ──────────────────────────
{
  const report = {
    ...zhReport,
    patientFacingLocalized: {
      language: 'vi-VN',
      summary: 'Quý vị bị tiểu ra máu 3 ngày, không sốt.',
      patientEducation: ['Uống nhiều nước'],
    },
  } as unknown as NonNullable<Arg>;

  const r = resolvePatientFacing(report, 'vi-VN');
  assert.equal(r.source, 'localized');
  assert.equal(r.useGenericFallback, false);
  assert.equal(r.summary, 'Quý vị bị tiểu ra máu 3 ngày, không sốt.');
  assert.deepEqual(r.patientEducation, ['Uống nhiều nước']);
  console.log('情境 1（在地化文字語言相符）：採用在地化版本 — 通過');
}

// ── 2. patientFacingLocalized 語言與場次語言不符 → 不得使用 ────────────────
{
  const report = {
    ...zhReport,
    patientFacingLocalized: {
      language: 'en-US',
      summary: 'You have had blood in your urine for three days.',
      patientEducation: ['Drink plenty of water'],
    },
  } as unknown as NonNullable<Arg>;

  const r = resolvePatientFacing(report, 'vi-VN');
  assert.equal(r.source, 'none');
  assert.equal(r.useGenericFallback, true);
  assert.equal(r.summary, null);
  assert.deepEqual(r.patientEducation, []);
  console.log('情境 2（在地化文字是另一種語言）：退回通用訊息、不顯示錯語言內容 — 通過');
}

// ── 3. 非中文場次、完全沒有在地化文字 → 通用訊息（絕不退回中文 summary） ────
{
  for (const lang of ['en-US', 'ja-JP', 'ko-KR', 'vi-VN']) {
    const r = resolvePatientFacing(zhReport, lang);
    assert.equal(r.useGenericFallback, true, `${lang} 應退回通用訊息`);
    assert.equal(r.summary, null, `${lang} 不得顯示中文 summary`);
    assert.deepEqual(r.patientEducation, [], `${lang} 不得顯示中文 patientEducation`);
    assert.ok(
      !JSON.stringify(r).includes('血尿'),
      `${lang} 的回傳值不得夾帶任何中文報告內容`,
    );
  }
  console.log('情境 3（非中文場次無在地化文字）：四語皆退回通用訊息 — 通過');
}

// ── 4. zh-TW 場次 → 維持顯示報告本體的中文 summary ─────────────────────────
{
  const r = resolvePatientFacing(zhReport, 'zh-TW');
  assert.equal(r.source, 'report');
  assert.equal(r.useGenericFallback, false);
  assert.equal(r.summary, '病患主訴血尿三天，無發燒。');
  assert.deepEqual(r.patientEducation, ['多喝水', '如廁後留意尿液顏色']);
  console.log('情境 4（zh-TW 場次）：維持顯示中文 summary — 通過');
}

// ── 5. zh-TW 場次但報告尚無 summary → 不算語言性 fallback ──────────────────
{
  const r = resolvePatientFacing({ summary: '   ' } as unknown as NonNullable<Arg>, 'zh-TW');
  assert.equal(r.useGenericFallback, false, 'zh-TW 走各頁既有的「尚無摘要」文案，不是語言 fallback');
  assert.equal(r.summary, null);
  console.log('情境 5（zh-TW 但報告無摘要）：不誤判成語言性 fallback — 通過');
}

// ── 6. 在地化欄位存在但內容全空 → 視同沒有，往下走既有規則 ─────────────────
{
  const emptyLocalized = {
    ...zhReport,
    patientFacingLocalized: { language: 'ja-JP', summary: '  ', patientEducation: [] },
  } as unknown as NonNullable<Arg>;

  assert.equal(resolvePatientFacing(emptyLocalized, 'ja-JP').useGenericFallback, true);
  assert.equal(
    resolvePatientFacing({ ...emptyLocalized, patientFacingLocalized: { language: 'zh-TW' } } as unknown as NonNullable<Arg>, 'zh-TW').source,
    'report',
  );
  console.log('情境 6（在地化欄位空殼）：視同不存在 — 通過');
}

// ── 7. 報告不存在 / 語言缺漏 → 不得爆炸 ────────────────────────────────────
{
  assert.equal(resolvePatientFacing(null, 'en-US').useGenericFallback, true);
  assert.equal(resolvePatientFacing(undefined, 'zh-TW').summary, null);
  // 場次語言缺漏：判不準一律歸保守側（不顯示中文內容）
  assert.equal(resolvePatientFacing(zhReport, null).useGenericFallback, true);
  assert.equal(resolvePatientFacing(zhReport, undefined).useGenericFallback, true);
  console.log('情境 7（report/language 缺漏）：保守退回通用訊息、不 throw — 通過');
}

// ── 8. 主語言子標籤相容（zh-Hant-TW / zh-TW） ──────────────────────────────
{
  const report = {
    ...zhReport,
    patientFacingLocalized: { language: 'en', summary: 'Summary in English.' },
  } as unknown as NonNullable<Arg>;
  assert.equal(resolvePatientFacing(report, 'en-US').source, 'localized');
  assert.equal(resolvePatientFacing(zhReport, 'zh-Hant-TW').source, 'report');
  console.log('情境 8（主語言子標籤相容）：zh-Hant-TW / en 視為相符 — 通過');
}

// ── 9. patientEducation 執行期形狀正規化（舊 .join 曾 TypeError 炸頁） ──────
{
  assert.deepEqual(normalizeStringList(undefined), []);
  assert.deepEqual(normalizeStringList(null), []);
  assert.deepEqual(normalizeStringList('單一字串'), ['單一字串']);
  assert.deepEqual(normalizeStringList(['', '  ', 'a']), ['a']);
  assert.deepEqual(normalizeStringList([null, 1, 'b'] as unknown), ['b']);
  console.log('情境 9（衛教清單形狀正規化）：非預期形狀不壞畫面 — 通過');
}

console.log('patientFacingReport.test.mts — all assertions passed');
