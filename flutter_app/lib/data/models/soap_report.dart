// Patient-visible subset of SOAPReport (types/index.ts). The patient screens show the
// summary, ICD-10 codes, review status and confidence — not the full S/O/A/P body (that's
// the doctor SOAPReportPage, Phase 5). Red-flag state is NOT on the report; read it from
// the parent Session. Keys arrive camelCased by the Dio interceptor.
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
      raw: json,
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
