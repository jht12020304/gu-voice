import 'package:dio/dio.dart';

import '../models/user.dart';
import 'dio_client.dart';
import 'token_store.dart';

// Port of frontend/src/services/api/auth.ts. Request/response keys are converted
// camel<->snake by the Dio interceptors, so we speak camelCase here.
class AuthApi {
  final _dio = ApiClient.instance.dio;

  Future<({User user, String accessToken, String? refreshToken})> login(
    String email,
    String password,
  ) async {
    final res = await _dio.post('/auth/login', data: {'email': email, 'password': password});
    final data = res.data as Map;
    return (
      user: User.fromJson(data['user'] as Map),
      accessToken: data['accessToken'] as String,
      refreshToken: data['refreshToken'] as String?,
    );
  }

  Future<({User user, String accessToken, String? refreshToken})> register({
    required String email,
    required String password,
    required String name,
    String role = 'patient',
  }) async {
    final res = await _dio.post('/auth/register', data: {'email': email, 'password': password, 'name': name, 'role': role});
    final data = res.data as Map;
    return (
      user: User.fromJson(data['user'] as Map),
      accessToken: data['accessToken'] as String,
      refreshToken: data['refreshToken'] as String?,
    );
  }

  Future<void> logout() async {
    final refresh = await TokenStore.instance.readRefresh();
    try {
      await _dio.post(
        '/auth/logout',
        data: {'refreshToken': refresh},
        // Never let logout go through the 401-refresh branch. It would rotate the
        // refresh token and then retry with this ALREADY-CAPTURED old one, so the
        // backend blacklists the stale jti while the freshly minted token stays
        // valid for 7 days — the opposite of logging out (TODO G8).
        // A 401 here needs no recovery anyway: we clear locally regardless.
        options: Options(extra: {ApiClient.skipAuthRefresh: true}),
      );
    } catch (_) {
      // ignore logout API errors — local clear happens regardless
    }
  }

  Future<User> getMe() async {
    final res = await _dio.get('/auth/me');
    return User.fromJson(res.data as Map);
  }

  Future<User> updateMe(Map<String, dynamic> payload) async {
    final res = await _dio.put('/auth/me', data: payload);
    return User.fromJson(res.data as Map);
  }

  Future<void> changePassword(String currentPassword, String newPassword) =>
      _dio.post('/auth/change-password', data: {'currentPassword': currentPassword, 'newPassword': newPassword});

  /// 忘記密碼。
  ///
  /// `delivery` 由後端環境有無 email transport 決定（與帳號是否存在無關）：
  /// `'email'` = 信真的會寄出；`'onsite'` = 後端沒設 SENDGRID/SMTP，信不會寄出，
  /// 呼叫端要改成引導使用者找現場醫護／管理員，別謊稱已寄信。
  /// 與 React 版 `frontend/src/services/api/auth.ts` 同語意。
  Future<({String delivery})> forgotPassword(String email) async {
    final res = await _dio.post('/auth/forgot-password', data: {'email': email});
    final data = res.data;
    final delivery = data is Map ? data['delivery'] as String? : null;
    // 舊版後端沒有這個欄位 → 保守當 onsite（寧可多叫人問現場，不要謊稱已寄出）
    return (delivery: delivery == 'email' ? 'email' : 'onsite');
  }

  Future<void> resetPassword(String token, String newPassword) =>
      _dio.post('/auth/reset-password', data: {'token': token, 'newPassword': newPassword});
}
