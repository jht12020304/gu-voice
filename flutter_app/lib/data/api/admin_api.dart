import '../models/user.dart';
import 'dio_client.dart';

typedef UserPage = ({List<User> data, String? nextCursor, bool hasMore, int totalCount});

// Port of frontend/src/services/api/admin.ts. Admin-only endpoints (RoleGuard enforces).
class AdminApi {
  final _dio = ApiClient.instance.dio;

  Future<UserPage> getUsers({String? cursor, int limit = 20, String? role, bool? isActive, String? search}) async {
    final res = await _dio.get('/admin/users', queryParameters: {
      'cursor': ?cursor,
      'limit': limit,
      'role': ?role,
      'isActive': ?isActive,
      'search': ?search,
    });
    final data = res.data as Map;
    final list = (data['data'] as List? ?? const []).map((e) => User.fromJson(e as Map)).toList();
    final p = (data['pagination'] as Map?) ?? const {};
    return (
      data: list,
      nextCursor: p['nextCursor'] as String?,
      hasMore: (p['hasMore'] ?? false) as bool,
      totalCount: (p['totalCount'] as num?)?.toInt() ?? list.length,
    );
  }

  Future<User> createUser(Map<String, dynamic> payload) async {
    final res = await _dio.post('/admin/users', data: payload);
    return User.fromJson(res.data as Map);
  }

  Future<User> updateUser(String id, Map<String, dynamic> payload) async {
    final res = await _dio.put('/admin/users/$id', data: payload);
    return User.fromJson(res.data as Map);
  }

  Future<bool> toggleUserActive(String id) async {
    final res = await _dio.put('/admin/users/$id/toggle-active');
    return ((res.data as Map)['isActive'] ?? false) as bool;
  }

  /// 管理員代為重設密碼，回傳一次性臨時密碼；同時撤銷該使用者所有 refresh token。
  ///
  /// ⚠️ `tempPassword` 是明文憑證且**只出現這一次**（後端只存 hash、不寫 log）。
  /// 不要寫進 localStorage、不要送進任何 log／錯誤追蹤。
  /// 存在理由：生產未設 email transport，忘記密碼的信寄不出去，前端引導使用者
  /// 「告知現場醫護或系統管理員」——這支就是讓那句話成真的途徑（TODO H1）。
  Future<({String email, String tempPassword})> resetUserPassword(String id) async {
    final res = await _dio.post('/admin/users/$id/reset-password');
    final d = res.data as Map;
    return (
      email: (d['email'] ?? '') as String,
      tempPassword: (d['tempPassword'] ?? '') as String,
    );
  }

  Future<Map> getSystemHealth() async {
    final res = await _dio.get('/admin/system/health');
    return res.data as Map;
  }

  Future<({List<Map> data, String? nextCursor, bool hasMore})> getAuditLogs({String? cursor, int limit = 30, String? action}) async {
    final res = await _dio.get('/admin/audit-logs', queryParameters: {'cursor': ?cursor, 'limit': limit, 'action': ?action});
    final data = res.data as Map;
    final list = (data['data'] as List? ?? const []).cast<Map>();
    final p = (data['pagination'] as Map?) ?? const {};
    return (data: list, nextCursor: p['nextCursor'] as String?, hasMore: (p['hasMore'] ?? false) as bool);
  }
}
