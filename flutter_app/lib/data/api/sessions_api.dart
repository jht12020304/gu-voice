import '../models/session.dart';
import '../models/soap_report.dart';
import 'dio_client.dart';

// Port of frontend/src/services/api/sessions.ts (subset). Request/response keys are
// converted camel<->snake by the Dio interceptors.
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
  Future<List<Session>> getSessions({int? limit, String? patientId, String? status}) async {
    final res = await _dio.get('/sessions', queryParameters: {
      'limit': ?limit,
      'patientId': ?patientId,
      'status': ?status,
    });
    final data = res.data;
    final list = (data is Map ? data['data'] : data) as List? ?? const [];
    return list.map((e) => Session.fromJson(e as Map)).toList();
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
