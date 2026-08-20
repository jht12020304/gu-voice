// Patient-visible subset of SOAPReport (types/index.ts). The patient screens show the
// summary and review status only — NOT ICD-10 codes, NOT the AI confidence score, and not
// the full S/O/A/P body (that's the doctor SOAPReportPage). Those three are clinician-facing:
// an unverified ICD-10 code shown to a patient reads as a diagnosis, and a confidence
// percentage invites the patient to weigh the AI against the doctor who has not reviewed it
// yet. Red-flag state is NOT on the report; read it from the parent Session.
// Keys arrive camelCased by the Dio interceptor.
class SoapReport {
  final String id;
  final String sessionId;
  final String status; // generating | generated | failed
  final String reviewStatus; // pending | approved | revision_needed
  final String? summary;
  final List<String> icd10Codes;
  final bool? icd10Verified;
  final double? aiConfidenceScore;
  final List<String> patientEducation; // plan.patientEducation — the patient-facing advice
  final String? reviewNotes;
  /// 後端 `patient_facing_localized`（JSONB，camelCase 後為 `patientFacingLocalized`）。
  /// 缺欄位／null 是常態（舊報告、後端還沒填）——一律容錯成 null，由呼叫端決定退路。
  final PatientFacingLocalized? patientFacingLocalized;
  // The full decoded body. The doctor SOAP page reads nested S/O/A/P from here with
  // defensive coercion (the AI JSON is messy: snake/camel, string-vs-array), instead of
  // modeling dozens of nested classes.
  final Map raw;

  const SoapReport({
    required this.id,
    required this.sessionId,
    required this.status,
    required this.reviewStatus,
    this.summary,
    this.icd10Codes = const [],
    this.icd10Verified,
    this.aiConfidenceScore,
    this.patientEducation = const [],
    this.reviewNotes,
    this.patientFacingLocalized,
    this.raw = const {},
  });

  factory SoapReport.fromJson(Map json) {
    final codes = json['icd10Codes'];
    final edu = (json['plan'] as Map?)?['patientEducation'];
    return SoapReport(
      id: json['id'] as String,
      sessionId: (json['sessionId'] ?? '') as String,
      status: (json['status'] ?? 'generating') as String,
      reviewStatus: (json['reviewStatus'] ?? 'pending') as String,
      summary: json['summary'] as String?,
      icd10Codes: codes is List ? codes.cast<String>() : const [],
      icd10Verified: json['icd10Verified'] as bool?,
      aiConfidenceScore: (json['aiConfidenceScore'] as num?)?.toDouble(),
      patientEducation: edu is List ? edu.cast<String>() : const [],
      reviewNotes: json['reviewNotes'] as String?,
      patientFacingLocalized: PatientFacingLocalized.tryParse(
        json['patientFacingLocalized'] ?? json['patient_facing_localized'],
      ),
      raw: json,
    );
  }
}

/// SOAP 報告的**病患面在地化版本**（後端 `soap_reports.patient_facing_localized` JSONB）。
///
/// 為什麼需要它：SOAP 報告本體是病歷，語言固定跟著醫療機構（中文），非中文場次的病患
/// 若直接看到 `summary`／`plan.patientEducation`，看到的是一段讀不懂的中文病歷。後端另外
/// 產一份病患面的在地化文字放這裡，並帶上它**實際被寫成哪個語言**（`language`），前端只有
/// 在該語言與場次語言相符時才顯示——語言不符就等於沒有在地化版本（例如報告在病患切語言
/// 前產生），寧可退回通用訊息也不能顯示看不懂的文字。
///
/// 解析一律容錯：整個欄位是後端新增的，舊報告沒有它，形狀不對（非 Map／language 非字串／
/// patientEducation 混入非字串）一律當作沒有，不得讓病患端整頁爆掉。
class PatientFacingLocalized {
  /// 這份在地化文字實際被寫成的語言（BCP-47，如 `en-US`）。
  final String language;
  final String? summary;
  final List<String> patientEducation;

  const PatientFacingLocalized({
    required this.language,
    this.summary,
    this.patientEducation = const [],
  });

  /// 回傳 null＝沒有可用的在地化版本（缺欄位、null、形狀不對）。
  static PatientFacingLocalized? tryParse(dynamic json) {
    if (json is! Map) return null;
    final lng = json['language'];
    if (lng is! String || lng.trim().isEmpty) return null;
    final summary = json['summary'];
    // 後端經 Dio interceptor 已轉 camelCase，但 raw 內容若哪天原樣穿透也要能讀。
    final edu = json['patientEducation'] ?? json['patient_education'];
    return PatientFacingLocalized(
      language: lng.trim(),
      summary: summary is String && summary.trim().isNotEmpty ? summary.trim() : null,
      patientEducation: edu is List
          ? [
              for (final e in edu)
                if (e is String && e.trim().isNotEmpty) e.trim(),
            ]
          : const [],
    );
  }
}

// Transcript DTO from GET /sessions/{id}/conversations, ordered by sequenceNumber.
class ConversationTurn {
  final String id;
  final int sequenceNumber;
  final String role; // patient | assistant | system
  final String contentText;
  final double? sttConfidence;
  final bool redFlagDetected;

  /// 後端 `createdAt`（ISO-8601）。L10-7 起 `resume_failed` 的逐字稿重建會把它搬進
  /// `ChatMessage.timestamp`——用「重抓當下的時間」會讓重建後的訊息全部同一秒。
  final String? createdAt;

  const ConversationTurn({
    required this.id,
    required this.sequenceNumber,
    required this.role,
    required this.contentText,
    this.sttConfidence,
    this.redFlagDetected = false,
    this.createdAt,
  });

  factory ConversationTurn.fromJson(Map json) => ConversationTurn(
        id: json['id'] as String,
        sequenceNumber: (json['sequenceNumber'] as num?)?.toInt() ?? 0,
        role: (json['role'] ?? 'assistant') as String,
        contentText: (json['contentText'] ?? '') as String,
        sttConfidence: (json['sttConfidence'] as num?)?.toDouble(),
        redFlagDetected: (json['redFlagDetected'] ?? false) as bool,
        createdAt: json['createdAt'] as String?,
      );
}
