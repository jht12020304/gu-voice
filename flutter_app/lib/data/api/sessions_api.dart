import '../models/session.dart';
import '../models/soap_report.dart';
import 'dio_client.dart';

// Port of frontend/src/services/api/sessions.ts (subset). Request/response keys are
// converted camel<->snake by the Dio interceptors.
class SessionsApi {
  final _dio = ApiClient.instance.dio;

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
