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
  int _sessionEpoch = 0;
  int get sessionEpoch => _sessionEpoch;
  Future<void> _pendingStorage = Future.value();

  // Serialize writes so an old refresh cannot overwrite a newer login/logout.
  Future<void> _persist(Future<void> Function() write) {
    final operation = _pendingStorage.then((_) => write());
    _pendingStorage = operation.then((_) {}, onError: (Object _) {});
    return operation;
  }

  Future<void> load() async {
    final epoch = _sessionEpoch;
    final cached = accessToken;
    await _pendingStorage;
    final stored = await _storage.read(key: _access);
    if (epoch != _sessionEpoch || accessToken != cached) return;
    // Retrying bootstrap for the same session must join an in-flight refresh.
    if (stored != cached) _sessionEpoch++;
    accessToken = stored;
  }

  Future<void> save({required String access, String? refresh, bool newSession = true}) {
    if (newSession) _sessionEpoch++;
    accessToken = access;
    return _persist(() async {
      await _storage.write(key: _access, value: access);
      if (refresh != null) {
        await _storage.write(key: _refresh, value: refresh);
      } else if (newSession) {
        await _storage.delete(key: _refresh);
      }
    });
  }

  Future<String?> readRefresh() async {
    await _pendingStorage;
    return _storage.read(key: _refresh);
  }

  Future<void> clear() {
    _sessionEpoch++;
    accessToken = null;
    return _persist(() async {
      await _storage.delete(key: _access);
      await _storage.delete(key: _refresh);
    });
  }
}
