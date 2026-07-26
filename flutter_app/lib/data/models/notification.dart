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
    if (type == 'report_ready' && sessionId is String) return '/reports/$sessionId';
    if (sessionId is String) return '/sessions/$sessionId';
    return null;
  }
}
