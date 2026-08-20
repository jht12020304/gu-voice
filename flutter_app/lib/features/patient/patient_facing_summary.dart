// 病患端「該顯示哪一份摘要／衛教」的唯一判斷點（session_complete_page 與
// patient_session_detail_page 共用）。
//
// 缺陷背景：SOAP 報告本體是**病歷**，語言跟著醫療機構固定為中文；病患端過去直接把
// `report.summary` 與 `plan.patientEducation` 印給病患看。中文場次沒問題，但英文／日文／
// 韓文／越南文場次的病患，問診全程講的是自己的語言，最後看到的卻是一段中文病歷摘要——
// 既讀不懂，也讓人以為系統壞了。
//
// 修法：後端在報告上另存 `patient_facing_localized`（{language, summary, patientEducation}）。
// 三態決策：
//   1. 有在地化版本且 `language` 與**場次語言**相符 → 顯示它。
//   2. 否則、且場次語言不是 zh-TW → 顯示在地化的通用訊息（`session.patientFacing.notice`），
//      **不得**退回中文病歷原文。措辭受 kiosk 鐵律拘束：病患已在候診區，只能請他稍候等
//      看診，禁止「盡速就醫」這類含糊指引。
//   3. 場次語言是 zh-TW → 維持現行為（顯示報告原文）。
//
// 語言比對用 `normalizeLanguage`：後端可能寫 `en`、`zh-Hant` 之類的變體，逐字比對會把
// 明明可用的在地化版本判成不符而退回通用訊息。

import '../../core/router/lng.dart';
import '../../data/models/soap_report.dart';

enum PatientSummaryMode {
  /// 後端在地化版本可用（語言與場次相符）。
  localized,

  /// 沒有可用的在地化版本，且場次非中文 → 通用訊息。
  genericNotice,

  /// zh-TW 場次 → 報告原文（現行為）。
  reportNative,
}

class PatientFacingSummary {
  final PatientSummaryMode mode;

  /// 可直接顯示的摘要；null＝沒有摘要可顯示（呼叫端用各自的 empty 文案／通用訊息）。
  final String? summary;

  /// 可直接顯示的衛教條目（已去空白、去空字串）。
  final List<String> education;

  const PatientFacingSummary({
    required this.mode,
    this.summary,
    this.education = const [],
  });

  /// 摘要區要不要改印通用訊息。
  bool get useGenericNotice => mode == PatientSummaryMode.genericNotice;
}

/// 清掉空白項。`List<String>` 的型別是 `cast<String>()` 來的（惰性），若後端塞了非字串
/// 元素，錯誤會在**取值時**才丟；整段包起來，任何非預期形狀都退成空清單而不是白畫面。
List<String> _clean(List<String>? raw) {
  if (raw == null) return const [];
  try {
    return [
      for (final e in raw)
        if (e.trim().isNotEmpty) e.trim(),
    ];
  } catch (_) {
    return const [];
  }
}

/// [sessionLanguage] 是**場次**語言（`Session.language`，後端解析後的最終語言），不是
/// 目前 URL 的 lng：病患看的是那一場問診當時實際使用的語言。抓不到場次時呼叫端傳
/// `currentLng` 當退路。
PatientFacingSummary resolvePatientFacingSummary({
  required String? sessionLanguage,
  String? reportSummary,
  List<String>? reportEducation,
  PatientFacingLocalized? localized,
}) {
  final lng = normalizeLanguage(sessionLanguage) ?? defaultLanguage;

  if (localized != null) {
    final localizedLng = normalizeLanguage(localized.language);
    final education = _clean(localized.patientEducation);
    final hasContent = localized.summary != null || education.isNotEmpty;
    if (localizedLng != null && localizedLng == lng && hasContent) {
      return PatientFacingSummary(
        mode: PatientSummaryMode.localized,
        summary: localized.summary,
        education: education,
      );
    }
  }

  // 非中文場次 + 沒有可用在地化版本 = 只給通用訊息。這裡刻意**不**帶任何報告原文欄位
  // 出去，避免日後有人在 UI 端「順手」再退回中文摘要。
  if (lng != defaultLanguage) {
    return const PatientFacingSummary(mode: PatientSummaryMode.genericNotice);
  }

  final summary = reportSummary?.trim();
  return PatientFacingSummary(
    mode: PatientSummaryMode.reportNative,
    summary: (summary == null || summary.isEmpty) ? null : summary,
    education: _clean(reportEducation),
  );
}
