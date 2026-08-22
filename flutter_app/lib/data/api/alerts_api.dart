import '../models/alert.dart';
import 'dio_client.dart';

typedef AlertPage = ({List<RedFlagAlert> data, String? nextCursor, bool hasMore, int totalCount});

// Port of frontend/src/services/api/alerts.ts. Backend localizes title/triggerReason/
// suggestedActions via Accept-Language (set by the Dio interceptor from the URL lng).
class AlertsApi {
  final _dio = ApiClient.instance.dio;

  Future<AlertPage> list({String? cursor, int limit = 20, String? severity, bool? acknowledged, String? sessionId}) async {
    final res = await _dio.get('/alerts', queryParameters: {
      'cursor': ?cursor,
      'limit': limit,
      'severity': ?severity,
      // 後端參數是 is_acknowledged；dio 會把 camelCase 轉 snake_case，
      // 舊值 'acknowledged'（單字）轉完還是 'acknowledged' → 篩選永遠沒生效
      // （未處理/已處理兩個 tab 等同「全部」，2026-08-23 稽核）。
      'isAcknowledged': ?acknowledged,
      'sessionId': ?sessionId,
    });
    final data = res.data as Map;
    final list = (data['data'] as List? ?? const []).map((e) => RedFlagAlert.fromJson(e as Map)).toList();
    final p = (data['pagination'] as Map?) ?? const {};
    return (
      data: list,
      nextCursor: p['nextCursor'] as String?,
      hasMore: (p['hasMore'] ?? false) as bool,
      totalCount: (p['totalCount'] as num?)?.toInt() ?? list.length,
    );
  }

  Future<RedFlagAlert> get(String id) async {
    final res = await _dio.get('/alerts/$id');
    return RedFlagAlert.fromJson(res.data as Map);
  }

  // Returns the PARTIAL response map (id + acknowledged* fields) for the caller to merge.
  Future<Map> acknowledge(String id, {String? actionTaken, String? notes}) async {
    final res = await _dio.post('/alerts/$id/acknowledge', data: {
      'actionTaken': ?actionTaken,
      'acknowledgeNotes': ?notes,
    });
    return res.data as Map;
  }

  Future<int> unacknowledgedCount() async {
    final res = await _dio.get('/alerts/unacknowledged/count');
    return ((res.data as Map)['count'] as num?)?.toInt() ?? 0;
  }
}
