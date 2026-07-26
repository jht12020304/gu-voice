import 'dart:convert';

// RedFlagAlert (types/index.ts). Keys camelCased by the Dio interceptor. llmAnalysis is
// string OR object — see llmAnalysisText. acknowledged is derived from acknowledgedAt.
class RedFlagAlert {
  final String id;
  final String sessionId;
  final String conversationId;
  final String alertType; // rule_based | semantic | combined
  final String severity; // critical | high | medium
  final String title;
  final String? description;
  final String triggerReason;
  final List<String> triggerKeywords;
  final dynamic llmAnalysis; // String | Map | List | null
  final List<String> suggestedActions;
  final String? acknowledgedBy;
  final String? acknowledgedAt;
  final String? acknowledgeNotes;
  final String? actionTaken;
  final String createdAt;

  const RedFlagAlert({
    required this.id,
    required this.sessionId,
    this.conversationId = '',
    this.alertType = 'combined',
    required this.severity,
    required this.title,
    this.description,
    this.triggerReason = '',
    this.triggerKeywords = const [],
    this.llmAnalysis,
    this.suggestedActions = const [],
    this.acknowledgedBy,
    this.acknowledgedAt,
    this.acknowledgeNotes,
    this.actionTaken,
    required this.createdAt,
  });

  bool get acknowledged => acknowledgedAt != null;

  String get llmAnalysisText {
    final a = llmAnalysis;
    if (a == null) return '';
    if (a is String) return a;
    try {
      return const JsonEncoder.withIndent('  ').convert(a);
    } catch (_) {
      return a.toString();
    }
  }

  factory RedFlagAlert.fromJson(Map j) {
    List<String> strList(dynamic v) => v is List ? v.cast<String>() : const [];
    return RedFlagAlert(
      id: j['id'] as String,
      sessionId: (j['sessionId'] ?? '') as String,
      conversationId: (j['conversationId'] ?? '') as String,
      alertType: (j['alertType'] ?? 'combined') as String,
      severity: (j['severity'] ?? 'medium') as String,
      title: (j['title'] ?? '') as String,
      description: j['description'] as String?,
      triggerReason: (j['triggerReason'] ?? '') as String,
      triggerKeywords: strList(j['triggerKeywords']),
      llmAnalysis: j['llmAnalysis'],
      suggestedActions: strList(j['suggestedActions']),
      acknowledgedBy: j['acknowledgedBy'] as String?,
      acknowledgedAt: j['acknowledgedAt'] as String?,
      acknowledgeNotes: j['acknowledgeNotes'] as String?,
      actionTaken: j['actionTaken'] as String?,
      createdAt: (j['createdAt'] ?? '') as String,
    );
  }

  // Partial-response merge from POST /acknowledge (keeps title/severity/etc).
  RedFlagAlert mergeAck({String? acknowledgedBy, String? acknowledgedAt, String? acknowledgeNotes, String? actionTaken}) =>
      RedFlagAlert(
        id: id,
        sessionId: sessionId,
        conversationId: conversationId,
        alertType: alertType,
        severity: severity,
        title: title,
        description: description,
        triggerReason: triggerReason,
        triggerKeywords: triggerKeywords,
        llmAnalysis: llmAnalysis,
        suggestedActions: suggestedActions,
        acknowledgedBy: acknowledgedBy ?? this.acknowledgedBy,
        acknowledgedAt: acknowledgedAt ?? this.acknowledgedAt,
        acknowledgeNotes: acknowledgeNotes ?? this.acknowledgeNotes,
        actionTaken: actionTaken ?? this.actionTaken,
        createdAt: createdAt,
      );
}
