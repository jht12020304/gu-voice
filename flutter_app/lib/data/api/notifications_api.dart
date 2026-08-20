import '../models/notification.dart';
import 'dio_client.dart';

typedef NotifPage = ({List<AppNotification> data, String? nextCursor, bool hasMore});

// Port of frontend/src/services/api/notifications.ts (list/mark-read/unread-count).
class NotificationsApi {
  // Lazy on purpose (same reason as SessionsApi): `ApiClient.instance.dio` is only
  // initialised by `main()`, so an eager field initializer makes this class
  // unconstructible in plain `flutter test` — and unsubclassable by fakes.
  late final _dio = ApiClient.instance.dio;

  Future<NotifPage> list({String? cursor, int limit = 20, String? type, bool? isRead}) async {
    final res = await _dio.get('/notifications', queryParameters: {
      'cursor': ?cursor,
      'limit': limit,
      'type': ?type,
      'isRead': ?isRead,
    });
    final data = res.data as Map;
    final list = (data['data'] as List? ?? const []).map((e) => AppNotification.fromJson(e as Map)).toList();
    final p = (data['pagination'] as Map?) ?? const {};
    return (data: list, nextCursor: p['nextCursor'] as String?, hasMore: (p['hasMore'] ?? false) as bool);
  }

  Future<void> markRead(String id) => _dio.put('/notifications/$id/read');

  Future<void> markAllRead() => _dio.put('/notifications/read-all');

  Future<int> unreadCount() async {
    final res = await _dio.get('/notifications/unread-count');
    return ((res.data as Map)['count'] as num?)?.toInt() ?? 0;
  }
}
