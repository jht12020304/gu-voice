import 'package:dio/dio.dart';

import '../../core/config/env.dart';
import '../../core/router/lng.dart';
import 'case_convert.dart';
import 'token_store.dart';

// Dio instance porting frontend/src/services/api/client.ts:
//  - Bearer access token on every request
//  - Accept-Language from the URL-authoritative lng segment (currentLng)
//  - camelCase -> snake_case on request body/params, snake_case -> camelCase on responses
//  - single shared 401 -> /auth/refresh -> retry-once -> else clear + signal logout
//
// Cross-site cookie/CSRF paths are dropped: local + native use the body-refresh path
// (refresh_token in the POST body), which the backend accepts without CSRF.

typedef OnAuthCleared = void Function();

class ApiClient {
  ApiClient._();
  static final instance = ApiClient._();

  /// `Options(extra: {ApiClient.skipAuthRefresh: true})` opts a request out of the
  /// 401 → refresh → retry branch. Needed by `/auth/logout`, which captures the
  /// refresh token before sending: a refresh mid-flight would rotate it and retry
  /// with the stale copy (see auth_api.logout).
  static const skipAuthRefresh = '_skipAuthRefresh';

  late final Dio dio;
  final _tokens = TokenStore.instance;

  // Set by the app so a terminal 401 can redirect to /login.
  OnAuthCleared? onAuthCleared;

  Future<String>? _refreshInFlight;

  void init() {
    dio = Dio(
      BaseOptions(
        baseUrl: Env.apiBase,
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 30),
        headers: {'Content-Type': 'application/json'},
      ),
    );

    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final token = _tokens.accessToken;
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          options.headers.putIfAbsent('Accept-Language', () => currentLng);

          if (options.data is Map || options.data is List) {
            options.data = camelToSnake(options.data);
          }
          if (options.queryParameters.isNotEmpty) {
            options.queryParameters =
                camelToSnake<Map>(options.queryParameters).cast<String, dynamic>();
          }
          handler.next(options);
        },
        onResponse: (response, handler) {
          // Skip binary responses (e.g. PDF bytes) — only convert JSON.
          if (response.requestOptions.responseType == ResponseType.json &&
              (response.data is Map || response.data is List)) {
            response.data = snakeToCamel(response.data);
          }
          handler.next(response);
        },
        onError: (e, handler) async {
          final req = e.requestOptions;
          if (e.response?.statusCode == 401 &&
              req.extra['_retry'] != true &&
              req.extra[skipAuthRefresh] != true) {
            req.extra['_retry'] = true;
            try {
              final newToken = await _refresh();
              req.headers['Authorization'] = 'Bearer $newToken';
              final clone = await dio.fetch(req);
              return handler.resolve(clone);
            } catch (_) {
              await _tokens.clear();
              onAuthCleared?.call();
              return handler.next(e);
            }
          }
          if (e.response?.data is Map || e.response?.data is List) {
            e.response!.data = snakeToCamel(e.response!.data);
          }
          handler.next(e);
        },
      ),
    );
  }

  // For the conversation WS 4001 handler: refresh once, report success/failure.
  Future<bool> forceRefresh() async {
    try {
      await _refresh();
      return true;
    } catch (_) {
      return false;
    }
  }

  // Single shared refresh: concurrent 401s trigger /auth/refresh at most once
  // (backend rotates refresh tokens with reuse-detection — parallel refreshes get killed).
  Future<String> _refresh() {
    return _refreshInFlight ??= () async {
      try {
        final stored = await _tokens.readRefresh();
        // Bare Dio (no interceptors) to avoid recursing into this 401 branch.
        final bare = Dio(BaseOptions(
          baseUrl: Env.apiBase,
          connectTimeout: const Duration(seconds: 30),
          // Without these a single hung refresh never settles, and because every
          // concurrent 401 awaits the same `_refreshInFlight` future the whole app
          // deadlocks silently — no error, no spinner end (TODO G9).
          receiveTimeout: const Duration(seconds: 30),
          sendTimeout: const Duration(seconds: 30),
        ));
        final res = await bare.post(
          '/auth/refresh',
          data: stored != null ? {'refresh_token': stored} : {},
        );
        final data = res.data as Map;
        final access = data['access_token'] as String;
        await _tokens.save(access: access, refresh: data['refresh_token'] as String?);
        return access;
      } finally {
        _refreshInFlight = null;
      }
    }();
  }
}
