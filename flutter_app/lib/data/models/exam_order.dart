// 檢查醫囑（醫師快速開單頁）。後端 `app/models/exam_order.py` 的對應物。
//
// items 是**快照**而不是對報告的參照：AI 建議的檢查項目是 LLM 生成的自由字串，
// 院內沒有代碼表可綁（2026-09-09 拍板先不綁）。報告日後被重新生成時 plan 會整個
// 換掉，只有這份快照還原得出醫師當時到底勾了什麼。
//
// Keys arrive camelCased by the Dio interceptor.

/// 一筆檢查項目。欄位形狀刻意對齊 SOAP `plan.recommendedTests` 的元素，
/// 勾選後原樣送回後端即可。
class ExamOrderItem {
  final String testName;
  final String? urgency;
  final String? rationale;

  const ExamOrderItem({required this.testName, this.urgency, this.rationale});

  /// 從 SOAP plan 的一筆建議檢查建立。後端 LLM 輸出 snake/camel 混用，兩形都認
  /// （與 soap_report_page 的防禦性讀取同一個理由）。
  static ExamOrderItem? fromPlanTest(dynamic raw) {
    if (raw is! Map) return null;
    final name = (raw['testName'] ?? raw['test_name'])?.toString().trim() ?? '';
    if (name.isEmpty) return null;
    String? nonEmpty(dynamic v) {
      final s = v?.toString().trim() ?? '';
      return s.isEmpty ? null : s;
    }

    return ExamOrderItem(
      testName: name,
      urgency: nonEmpty(raw['urgency']),
      rationale: nonEmpty(raw['rationale']),
    );
  }

  factory ExamOrderItem.fromJson(Map j) => ExamOrderItem(
        testName: (j['testName'] ?? j['test_name'] ?? '').toString(),
        urgency: j['urgency'] as String?,
        rationale: j['rationale'] as String?,
      );

  Map<String, Object?> toJson() => {
        'testName': testName,
        'urgency': ?urgency,
        'rationale': ?rationale,
      };

  @override
  bool operator ==(Object other) =>
      other is ExamOrderItem &&
      other.testName == testName &&
      other.urgency == urgency &&
      other.rationale == rationale;

  @override
  int get hashCode => Object.hash(testName, urgency, rationale);
}

/// 一張已送出的檢查單。append-only —— 醫師可重新勾選再送，以最新一張為準。
class ExamOrder {
  final String id;
  final String sessionId;
  final String? reportId;
  final String orderedBy;
  final List<ExamOrderItem> items;
  final String? note;
  final String createdAt;

  const ExamOrder({
    required this.id,
    required this.sessionId,
    this.reportId,
    required this.orderedBy,
    required this.items,
    this.note,
    required this.createdAt,
  });

  factory ExamOrder.fromJson(Map j) => ExamOrder(
        id: (j['id'] ?? '').toString(),
        sessionId: (j['sessionId'] ?? '').toString(),
        reportId: j['reportId'] as String?,
        orderedBy: (j['orderedBy'] ?? '').toString(),
        items: [
          for (final e in (j['items'] as List? ?? const []))
            if (e is Map) ExamOrderItem.fromJson(e),
        ],
        note: j['note'] as String?,
        createdAt: (j['createdAt'] ?? '').toString(),
      );
}
