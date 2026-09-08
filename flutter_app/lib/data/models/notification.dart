// Notification (types/index.ts). data holds sessionId/alertId for tap routing.
class AppNotification {
  final String id;
  final String type; // red_flag | session_complete | report_ready | system
  final String title;
  final String? body;
  final Map data;
  final bool isRead;
  final String? readAt;
  final String createdAt;

  const AppNotification({
    required this.id,
    required this.type,
    required this.title,
    this.body,
    this.data = const {},
    this.isRead = false,
    this.readAt,
    required this.createdAt,
  });

  factory AppNotification.fromJson(Map j) => AppNotification(
        id: j['id'] as String,
        type: (j['type'] ?? 'system') as String,
        title: (j['title'] ?? '') as String,
        body: j['body'] as String?,
        data: (j['data'] as Map?) ?? const {},
        isRead: (j['isRead'] ?? false) as bool,
        readAt: j['readAt'] as String?,
        createdAt: (j['createdAt'] ?? '') as String,
      );

  AppNotification copyWith({bool? isRead, String? readAt}) => AppNotification(
        id: id,
        type: type,
        title: title,
        body: body,
        data: data,
        isRead: isRead ?? this.isRead,
        readAt: readAt ?? this.readAt,
        createdAt: createdAt,
      );

  // Tap routing: alertId -> /alerts/:id; report_ready+sessionId -> /reports/:id;
  // sessionId -> /sessions/:id; else null.
  String? route() {
    final alertId = data['alertId'];
    if (alertId is String) return '/alerts/$alertId';
    final sessionId = data['sessionId'];
    // 2026-09-09：報告完成改落在快速開單頁（摘要 → 勾選 AI 建議檢查 → 送出）。
    // 醫師收到這則推播的當下要做的決定通常只有一個：要不要開檢查。完整 S/O/A/P、
    // 逐字稿與 PDF 仍在 /reports/:sessionId，快速開單頁底部有一條連過去。
    // 這支同時是通知中心點擊的來源，所以站內清單點下去也會落在同一頁——刻意一致。
    if (type == 'report_ready' && sessionId is String) return '/orders/$sessionId';
    if (sessionId is String) return '/sessions/$sessionId';
    return null;
  }
}
