// =============================================================================
// 防回歸：病患端顯示面與 intake 第三態旗標（2026-08 稽核拍板）
//
// 1. SessionCompletePage 不得渲染 ICD-10 碼與 AI 信心分數（醫師面資訊）。
// 2. 病患端兩頁的 summary 一律走 resolvePatientFacing（不得直接印 report.summary）。
// 3. MedicalInfoPage 的 noFamilyHistory 必須是**明確勾選才 true**，絕不可從空清單推斷
//    （不變式 #23 三態 gating；Flutter 端剛修掉的 IN-1 就是這個錯誤）。
//
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/screens/patient/__tests__/patientFacingSurface.test.mts
// =============================================================================

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const read = (rel: string) => readFileSync(resolve(HERE, rel), 'utf8');

const complete = read('../SessionCompletePage.tsx');
const detail = read('../PatientSessionDetailPage.tsx');
const medicalInfo = read('../MedicalInfoPage.tsx');
const soapPage = read('../../doctor/SOAPReportPage.tsx');

/** 去掉 // 與 /* *\/ 註解，避免「只在註解裡提到」被誤判成有渲染。 */
function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

// ── 1. 病患完成頁不得渲染 ICD-10 / AI 信心分數 ─────────────────────────────
{
  const code = stripComments(complete);
  assert.ok(
    !/icd10Codes/.test(code),
    'SessionCompletePage 又渲染了 ICD-10 碼：那是醫師面資訊，病患會誤讀成「AI 已診斷」',
  );
  assert.ok(
    !/aiConfidenceScore/.test(code) && !/complete\.aiConfidence/.test(code),
    'SessionCompletePage 又渲染了 AI 信心分數：模型自評對候診病患無行動意義且易誤讀成病情嚴重度',
  );
  // 醫師端不受此限——確認沒有被連坐刪掉
  assert.ok(
    /aiConfidenceScore/.test(stripComments(soapPage)),
    '醫師端 SOAPReportPage 的 AI 信心分數不該被移除（本次拍板只限病患端）',
  );
  console.log('1：病患完成頁無 ICD-10／AI 信心分數，醫師端維持顯示 — 通過');
}

// ── 2. 病患端 summary 一律走 resolvePatientFacing ──────────────────────────
for (const [name, src] of [
  ['SessionCompletePage', complete],
  ['PatientSessionDetailPage', detail],
] as const) {
  const code = stripComments(src);
  assert.ok(
    /resolvePatientFacing\s*\(/.test(code),
    `${name} 沒有使用 resolvePatientFacing`,
  );
  assert.ok(
    /patientFacing\.useGenericFallback/.test(code),
    `${name} 沒有處理 useGenericFallback：非中文場次會直接印出中文 summary`,
  );
  assert.ok(
    /patientFacing\.notice/.test(code),
    `${name} 沒有使用 session:patientFacing.notice 通用訊息`,
  );
  assert.ok(
    !/\breport\??\.summary\b/.test(code),
    `${name} 仍直接讀 report.summary：非中文場次的病患會拿到看不懂的中文報告`,
  );
}
console.log('2：病患端兩頁 summary 皆經 resolvePatientFacing 把關 — 通過');

// ── 3. noFamilyHistory 只能來自明確勾選 ────────────────────────────────────
{
  const code = stripComments(medicalInfo);

  assert.ok(
    /const \[noFamilyHistory, setNoFamilyHistory\] = useState\(false\)/.test(code),
    'MedicalInfoPage 缺少 noFamilyHistory 狀態（預設必須是 false＝「還沒表態」）',
  );

  // 勾選框存在，且勾起來時清空清單（與其他三個 no_* 同語意）
  assert.ok(
    /checked=\{noFamilyHistory\}/.test(code) &&
      /setNoFamilyHistory\(e\.target\.checked\)/.test(code) &&
      /setFamilyHistory\(\[\]\)/.test(code),
    'noFamilyHistory 勾選框缺漏，或勾選時未清空 familyHistory 列',
  );

  // 送出時直接送狀態值，且**不得**從清單長度推斷
  assert.ok(
    /\n\s*noFamilyHistory,\n/.test(code),
    'createSession 的 intake 沒有帶 noFamilyHistory',
  );
  assert.ok(
    !/noFamilyHistory[^\n]*familyHistory\.length/.test(code) &&
      !/familyHistory\.length\s*===\s*0[^\n]*noFamilyHistory/.test(code),
    '不得從 familyHistory 是否為空推斷 noFamilyHistory——「沒填」與「表明沒有」是不同兩態' +
      '（不變式 #23；Flutter 端 IN-1 就是這樣出錯的）',
  );

  // 其他三個 no_* 旗標的既有語意不得被連帶改壞
  for (const flag of ['noKnownAllergies', 'noCurrentMedications', 'noPastMedicalHistory']) {
    assert.ok(new RegExp(`${flag}:\\s*no`).test(code), `${flag} 送出方式被改動了`);
  }

  console.log('3：noFamilyHistory 為明確勾選的第三態旗標、不從空清單推斷 — 通過');
}

console.log('patientFacingSurface.test.mts — all assertions passed');
