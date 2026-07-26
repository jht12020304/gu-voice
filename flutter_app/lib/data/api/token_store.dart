import 'package:flutter_secure_storage/flutter_secure_storage.dart';

// Access + refresh tokens. Native: Keychain/Keystore. Web: backed by localStorage.
// Mirrors the web app's localStorage('access_token'/'refresh_token'); we use the
// body-refresh path (refresh_token in the POST body) so no cookie jar is needed
// and the flow is identical on web/iOS/Android.
class TokenStore {
  TokenStore._();
  static final instance = TokenStore._();

  final _storage = const FlutterSecureStorage();
  static const _access = 'access_token';
  static const _refresh = 'refresh_token';

  // In-memory cache so the Dio interceptor stays synchronous-friendly.
  String? accessToken;

  Future<void> load() async {
    accessToken = await _storage.read(key: _access);
  }

  Future<void> save({required String access, String? refresh}) async {
    accessToken = access;
    await _storage.write(key: _access, value: access);
    if (refresh != null) await _storage.write(key: _refresh, value: refresh);
  }

  Future<String?> readRefresh() => _storage.read(key: _refresh);

  Future<void> clear() async {
    accessToken = null;
    await _storage.delete(key: _access);
    await _storage.delete(key: _refresh);
  }
}
