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

  /// 註冊 FCM 裝置 token（backend/app/routers/notifications.py 的 `FCMTokenCreate`：
  /// `device_token` / `platform` / `device_name`）。這裡照慣例寫 camelCase，Dio 的
  /// request interceptor 會轉成 snake_case。同一個 token 重送＝後端 upsert。
  Future<void> registerFcmToken({
    required String token,
    required String platform,
    String? deviceName,
  }) =>
      _dio.post('/notifications/fcm-token', data: {
        'deviceToken': token,
        'platform': platform,
        'deviceName': ?deviceName,
      });

  /// 移除裝置 token（登出）。token 是 path segment，FCM token 含 `:`／`/` 之類的字元，
  /// 必須編碼過再拼進 URL。
  Future<void> removeFcmToken(String token) =>
      _dio.delete('/notifications/fcm-token/${Uri.encodeComponent(token)}');
}
