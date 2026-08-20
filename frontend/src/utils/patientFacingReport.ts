// =============================================================================
// 病患面 SOAP 文字的取用規則（SessionCompletePage / PatientSessionDetailPage 共用）
//
// 背景（語音管線不變式 #12 與 #24）：
//   - SOAP 報告本體固定 zh-TW——讀者是院內醫護（`SOAP_REPORT_LANGUAGE`，2026-07-19 拍板）。
//   - 但 `summary` 與 `plan.patientEducation` 這兩個欄位**會渲染給病患看**，受 kiosk
//     措辭鐵律（#11）約束。
//   - 於是非中文場次出現斷層：越南語病患問診完，畫面上是一段中文摘要。
//
// 現行規則（後端新增 `soap_reports.patient_facing_localized` 後）：
//   1. 報告帶 `patientFacingLocalized` 且其 `language` **符合場次語言** → 用它。
//   2. 否則場次語言是 zh-TW → 用報告本體的 `summary` / `plan.patientEducation`
//      （報告本來就是中文，病患看得懂）。
//   3. 否則（非中文場次、沒有可用的在地化文字）→ **不顯示中文報告內容**，改由呼叫端
//      顯示在地化通用訊息（`session:patientFacing.notice`）。硬塞中文比不塞更糟：
//      病患看不懂卻以為那是給自己的醫囑。
//
// 為什麼要比對 language 而不是「有就用」：報告是 generation-time-fixed 資料，場次語言
// 若在生成後被改過（或報告來自尚未支援該語言的舊版後端），欄位裡會是另一種語言的文字。
// 判不準一律退回通用訊息——這與 §3b gating「判不準就歸保守側」同一原則。
// =============================================================================

import type { PatientFacingLocalized, SOAPReport } from '../types';

/** 主語言碼比較（`zh-TW` vs `zh-Hant-TW` 這類寫法差異不該讓在地化文字整份作廢）。 */
function sameLanguage(a: string | null | undefined, b: string | null | undefined): boolean {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const na = a.trim().toLowerCase();
  const nb = b.trim().toLowerCase();
  if (!na || !nb) return false;
  if (na === nb) return true;
  // 退一步只比對主語言子標籤（zh / en / ja / ko / vi）
  return na.split('-')[0] === nb.split('-')[0];
}

function isChinese(language: string | null | undefined): boolean {
  return typeof language === 'string' && language.trim().toLowerCase().startsWith('zh');
}

/**
 * 正規化成「非空字串陣列」。
 *
 * 型別上是 `string[]`，但實際來源是 LLM 產出 + 後端出口過濾，執行期可能是
 * undefined / null / 空陣列 / 單一字串 / 含空字串或 null 的陣列。舊寫法
 * `report?.plan?.patientEducation?.join('；')` 在「被換成字串」時會直接 TypeError
 * 把整頁炸掉（PatientSessionDetailPage 修過一次），這裡一律先正規化。
 */
export function normalizeStringList(raw: unknown): string[] {
  const items = Array.isArray(raw) ? raw : typeof raw === 'string' ? [raw] : [];
  return items
    .filter((x): x is string => typeof x === 'string')
    .map((x) => x.trim())
    .filter((x) => x.length > 0);
}

export interface ResolvedPatientFacing {
  /** 可顯示的摘要；`null` = 沒有病患看得懂的內容 */
  summary: string | null;
  /** 可顯示的衛教條目（已正規化為非空字串陣列） */
  patientEducation: string[];
  /**
   * `true` = 呼叫端應改顯示在地化通用訊息（`session:patientFacing.notice`）。
   * 與「summary 為 null」不完全等價：中文場次但報告尚未產出摘要時，走的是各頁既有的
   * 「尚無摘要」文案，不是這條語言性 fallback。
   */
  useGenericFallback: boolean;
  /** 這段文字實際來自哪裡（測試與除錯用；UI 不顯示） */
  source: 'localized' | 'report' | 'none';
}

/**
 * 依場次語言決定病患端要顯示的 summary / patientEducation。
 *
 * @param report        該場次的 SOAP 報告（可能為 null / 尚未產生）
 * @param sessionLanguage 場次語言（`sessions.language`，非 UI 當下語言）
 */
export function resolvePatientFacing(
  report: Pick<SOAPReport, 'summary' | 'plan' | 'patientFacingLocalized'> | null | undefined,
  sessionLanguage: string | null | undefined,
): ResolvedPatientFacing {
  const localized: PatientFacingLocalized | null | undefined = report?.patientFacingLocalized;

  if (localized && sameLanguage(localized.language, sessionLanguage)) {
    const summary = typeof localized.summary === 'string' ? localized.summary.trim() : '';
    const education = normalizeStringList(localized.patientEducation);
    // 欄位存在但兩個內容都空 → 等同沒有在地化文字，往下走既有規則。
    if (summary || education.length > 0) {
      return {
        summary: summary || null,
        patientEducation: education,
        useGenericFallback: false,
        source: 'localized',
      };
    }
  }

  if (isChinese(sessionLanguage)) {
    const summary = typeof report?.summary === 'string' ? report.summary.trim() : '';
    return {
      summary: summary || null,
      patientEducation: normalizeStringList(report?.plan?.patientEducation),
      useGenericFallback: false,
      source: 'report',
    };
  }

  // 非中文場次且沒有可用在地化文字：不得把中文報告內容丟給病患。
  return { summary: null, patientEducation: [], useGenericFallback: true, source: 'none' };
}
