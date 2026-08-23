import '../models/session.dart';
import '../models/soap_report.dart';
import 'dio_client.dart';

// Port of frontend/src/services/api/sessions.ts (subset). Request/response keys are
// converted camel<->snake by the Dio interceptors.
/// 一頁場次 + 游標（`fetchRange` 用它翻完整個區間）。
class SessionsPage {
  const SessionsPage({required this.sessions, this.nextCursor, this.hasMore = false});
  final List<Session> sessions;
  final String? nextCursor;
  final bool hasMore;
}

class SessionsApi {
  // Lazy on purpose: `ApiClient.instance.dio` needs platform channels, so an eager
  // field initializer makes this class unconstructible in plain `flutter test`
  // (and unsubclassable by fakes). Nothing here works without a request anyway.
  late final _dio = ApiClient.instance.dio;

  Future<Session> createSession(Map<String, dynamic> payload) async {
    final res = await _dio.post('/sessions', data: payload);
    return Session.fromJson(res.data as Map);
  }

  Future<Session> getSession(String id) async {
    final res = await _dio.get('/sessions/$id');
    return Session.fromJson(res.data as Map);
  }

  // Cursor-paginated list; patient token is auto-scoped to own sessions.
  Future<List<Session>> getSessions({
    int? limit,
    String? patientId,
    String? status,
    String? dateFrom,
    String? dateTo,
    String? cursor,
    String? sortBy,
    String? sortOrder,
  }) async {
    final page = await getSessionsPage(
      limit: limit,
      patientId: patientId,
      status: status,
      dateFrom: dateFrom,
      dateTo: dateTo,
      cursor: cursor,
      sortBy: sortBy,
      sortOrder: sortOrder,
    );
    return page.sessions;
  }

  /// 同 [getSessions]，但把游標一起帶回來——呼叫端要走完整個區間時需要它。
  ///
  /// `dateFrom` / `dateTo` 是 ISO-8601 字串，**必須帶時區位移**
  /// （例：`2026-08-01T00:00:00.000+08:00`）。後端拿 `datetime.fromisoformat`
  /// 解析後與 `sessions.created_at`（timestamptz）比對：不帶位移的裸字串會被
  /// 當成 UTC，在 +08:00 的診間就是把一天切在早上八點——日曆上的「那一天」
  /// 會少掉清晨、多出前一天的傍晚。日界線由呼叫端的裝置時區決定。
  Future<SessionsPage> getSessionsPage({
    int? limit,
    String? patientId,
    String? status,
    String? dateFrom,
    String? dateTo,
    String? cursor,
    String? sortBy,
    String? sortOrder,
  }) async {
    final res = await _dio.get('/sessions', queryParameters: {
      'limit': ?limit,
      'patientId': ?patientId,
      'status': ?status,
      'dateFrom': ?dateFrom,
      'dateTo': ?dateTo,
      'cursor': ?cursor,
      'sortBy': ?sortBy,
      'sortOrder': ?sortOrder,
    });
    final data = res.data;
    final list = (data is Map ? data['data'] : data) as List? ?? const [];
    final pagination = (data is Map ? data['pagination'] : null) as Map?;
    return SessionsPage(
      sessions: list.map((e) => Session.fromJson(e as Map)).toList(),
      nextCursor: pagination?['nextCursor'] as String?,
      hasMore: (pagination?['hasMore'] as bool?) ?? false,
    );
  }

  /// 走完一個日期區間的**所有**場次（自動翻頁）。
  ///
  /// 日曆一次要看一整個月，而單頁上限是 100（後端 `Query(le=100)`）。
  /// [maxPages] 是保險絲：後端若因為某個 bug 一直回同一個游標，這裡不能變成
  /// 無限迴圈把 App 卡死；停下來時寧可少顯示幾場，也不要轉圈到天荒地老。
  Future<List<Session>> fetchRange({
    required String dateFrom,
    required String dateTo,
    int pageSize = 100,
    int maxPages = 10,
  }) async {
    final all = <Session>[];
    String? cursor;
    for (var page = 0; page < maxPages; page++) {
      final res = await getSessionsPage(
        limit: pageSize,
        dateFrom: dateFrom,
        dateTo: dateTo,
        cursor: cursor,
      );
      all.addAll(res.sessions);
      if (!res.hasMore || res.nextCursor == null || res.nextCursor == cursor) break;
      cursor = res.nextCursor;
    }
    return all;
  }

  /// 軟刪除整場問診（**只有 admin 有權限**，後端 `require_role("admin")`）。
  ///
  /// 後端做的是軟刪除：row 與逐字稿/報告/紅旗都留著，只是所有讀取路徑一律過濾掉。
  /// 前端不需要知道這件事——刪完就當它不存在（再 GET 會拿到 404）。
  Future<void> deleteSession(String sessionId) async {
    await _dio.delete('/sessions/$sessionId');
  }

  Future<Session> assignDoctor(String sessionId, String doctorId) async {
    final res = await _dio.post('/sessions/$sessionId/assign', data: {'doctorId': doctorId});
    return Session.fromJson(res.data as Map);
  }

  Future<Session> updateStatus(String sessionId, String status, {String? reason}) async {
    final res = await _dio.put('/sessions/$sessionId/status', data: {'status': status, 'reason': ?reason});
    return Session.fromJson(res.data as Map);
  }

  /// G35b：問診中切語言時，先用這支收掉當前場次（status → cancelled）並把使用者
  /// 偏好語言改成 [toLanguage]，下一場新 session 才會用新語言開場。
  ///
  /// 回應只有 `{id, status, previousStatus, updatedAt}`，呼叫端唯一需要的資訊是
  /// 「成功還是失敗」，所以不解析 body。失敗一律讓 DioException 往上拋：吞掉它
  /// 會讓前端切了語言、後端卻留下孤兒 in_progress 場次（仍以舊語言在跑）。
  /// 場次已在終態時後端冪等回 200；轉移表不允許 → cancelled 時回 409。
  Future<void> endSessionForLanguageSwitch(String sessionId, String toLanguage) async {
    // `toLanguage` 由 Dio 的 request interceptor 轉成 `to_language`（後端 schema
    // 的欄位名，alias 是 camel 版，populate_by_name 兩邊都收）。
    await _dio.post(
      '/sessions/$sessionId/end-for-language-switch',
      data: {'toLanguage': toLanguage},
    );
  }

  Future<List<ConversationTurn>> getConversations(String sessionId) async {
    final res = await _dio.get('/sessions/$sessionId/conversations');
    final data = res.data;
    final list = (data is Map ? data['data'] : data) as List? ?? const [];
    final turns = list.map((e) => ConversationTurn.fromJson(e as Map)).toList();
    turns.sort((a, b) => a.sequenceNumber.compareTo(b.sequenceNumber));
    return turns;
  }

  // Returns the resume checksum for WS ?resumeFrom, or null to start fresh.
  Future<String?> reconnectResumeToken(String sessionId) async {
    try {
      final res = await _dio.post('/sessions/$sessionId/reconnect');
      final data = res.data as Map;
      return (data['checksum'] ?? data['resumeToken']) as String?;
    } catch (_) {
      return null; // fall back to a fresh greeting
    }
  }
}
