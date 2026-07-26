import 'package:flutter_secure_storage/flutter_secure_storage.dart';

// Access + refresh tokens. Native: Keychain/Keystore. Web: backed by localStorage.
// Mirrors the web app's localStorage('access_token'/'refresh_token'); we use the
// body-refresh path (refresh_token in the POST body) so no cookie jar is needed
// and the flow is identical on web/iOS/Android.
class TokenStore {
  TokenStore._();
  static final instance = TokenStore._();

  // On web, flutter_secure_storage is AES over localStorage with the key kept in the
  // SAME localStorage — so XSS can decrypt it, and a 7-day refresh token would sit there
  // across browser sessions. `useSessionStorage` scopes it to the tab instead, which also
  // matches the kiosk model: the patient walks away, the session should not outlive them.
  // No effect on iOS/Android (Keychain / Keystore).
  final _storage = const FlutterSecureStorage(
    webOptions: WebOptions(useSessionStorage: true),
  );
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
