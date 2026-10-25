import 'package:dio/dio.dart';

import '../../core/config/env.dart';
import '../../core/router/lng.dart';
import 'case_convert.dart';
import 'token_store.dart';

// Dio instance porting frontend/src/services/api/client.ts:
//  - Bearer access token on every request
//  - Accept-Language from the URL-authoritative lng segment (currentLng)
//  - camelCase -> snake_case on request body/params, snake_case -> camelCase on responses
//  - single shared 401 -> /auth/refresh -> retry once; only rejected credentials log out
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
  late final Dio _refreshDio;
  final _tokens = TokenStore.instance;

  // Set by the app so a terminal 401 can redirect to /login.
  OnAuthCleared? onAuthCleared;

  Future<String>? _refreshInFlight;
  int? _refreshEpoch;
  static const _sessionEpoch = '_sessionEpoch';

  void init({Dio? refreshDio}) {
    dio = Dio(
      BaseOptions(
        baseUrl: Env.apiBase,
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 30),
        headers: {'Content-Type': 'application/json'},
      ),
    );
    // Separate client prevents the refresh request from entering its own interceptor.
    _refreshDio = refreshDio ?? Dio(BaseOptions(
      baseUrl: Env.apiBase,
      connectTimeout: const Duration(seconds: 30),
      receiveTimeout: const Duration(seconds: 30),
      sendTimeout: const Duration(seconds: 30),
    ));

    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          options.extra.putIfAbsent(_sessionEpoch, () => _tokens.sessionEpoch);
          if (options.extra[_sessionEpoch] != _tokens.sessionEpoch) {
            return handler.reject(_sessionChanged(options));
          }
          final token = _tokens.accessToken;
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          } else {
            options.headers.remove('Authorization');
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
          if (response.requestOptions.extra[_sessionEpoch] != _tokens.sessionEpoch) {
            return handler.reject(_sessionChanged(response.requestOptions));
          }
          // Skip binary responses (e.g. PDF bytes) — only convert JSON.
          if (response.requestOptions.responseType == ResponseType.json &&
              (response.data is Map || response.data is List)) {
            response.data = snakeToCamel(response.data);
          }
          handler.next(response);
        },
        onError: (e, handler) async {
          final req = e.requestOptions;
          if (req.extra[_sessionEpoch] != _tokens.sessionEpoch) {
            return handler.reject(_sessionChanged(req));
          }
          if (e.response?.statusCode == 401 &&
              req.extra['_retry'] != true &&
              req.extra[skipAuthRefresh] != true &&
              _tokens.accessToken != null) {
            req.extra['_retry'] = true;
            final epoch = _tokens.sessionEpoch;
            try {
              // A concurrent request may already have rotated the token.
              final current = _tokens.accessToken!;
              final newToken = req.headers['Authorization'] == 'Bearer $current'
                  ? await _refresh()
                  : current;
              req.headers['Authorization'] = 'Bearer $newToken';
            } on DioException catch (refreshError) {
              // Propagate transport/5xx errors as themselves, so bootstrap can retry.
              return handler.reject(refreshError);
            } catch (error, stack) {
              return handler.reject(DioException(requestOptions: req, error: error, stackTrace: stack));
            }
            try {
              return handler.resolve(await dio.fetch(req));
            } on DioException catch (retryError) {
              // A resource's 403 is a permission error, not a rejected session.
              if (retryError.response?.statusCode == 401) await _rejectSession(epoch);
              return handler.reject(retryError);
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

  DioException _sessionChanged(RequestOptions request) => DioException(
    requestOptions: request,
    type: DioExceptionType.cancel,
    message: 'Session changed',
  );

  Future<void> _rejectSession(int epoch) async {
    if (epoch != _tokens.sessionEpoch) return;
    final clearedEpoch = epoch + 1;
    try {
      await _tokens.clear();
    } catch (_) {
      // In-memory credentials were already cleared; storage failure must not hang
      // the rejected HTTP request or prevent the app from leaving this session.
    } finally {
      if (_tokens.sessionEpoch == clearedEpoch) onAuthCleared?.call();
    }
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
    final epoch = _tokens.sessionEpoch;
    if (_refreshEpoch == epoch && _refreshInFlight != null) return _refreshInFlight!;
    _refreshEpoch = epoch;
    return _refreshInFlight = () async {
      final request = RequestOptions(path: '/auth/refresh');
      try {
        final stored = await _tokens.readRefresh();
        if (epoch != _tokens.sessionEpoch) throw _sessionChanged(request);
        if (stored == null) {
          throw DioException(requestOptions: request,
            response: Response(requestOptions: request, statusCode: 401),
            type: DioExceptionType.badResponse);
        }
        final res = await _refreshDio.post(
          '/auth/refresh',
          data: {'refresh_token': stored},
        );
        if (epoch != _tokens.sessionEpoch) throw _sessionChanged(request);
        final data = res.data as Map;
        final access = data['access_token'] as String;
        await _tokens.save(access: access, refresh: data['refresh_token'] as String?, newSession: false);
        if (epoch != _tokens.sessionEpoch) throw _sessionChanged(request);
        return access;
      } on DioException catch (error) {
        if (epoch != _tokens.sessionEpoch) throw _sessionChanged(request);
        if (error.response?.statusCode == 401 || error.response?.statusCode == 403) {
          await _rejectSession(epoch);
        }
        rethrow;
      } finally {
        if (_refreshEpoch == epoch) _refreshInFlight = null;
      }
    }();
  }
}
