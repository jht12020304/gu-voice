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

  Future<void> forgotPassword(String email) =>
      _dio.post('/auth/forgot-password', data: {'email': email});

  Future<void> resetPassword(String token, String newPassword) =>
      _dio.post('/auth/reset-password', data: {'token': token, 'newPassword': newPassword});
}
