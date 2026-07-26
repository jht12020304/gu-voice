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
      await _dio.post('/auth/logout', data: {'refreshToken': refresh});
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
