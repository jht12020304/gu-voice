import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/auth_api.dart';
import '../../data/api/token_store.dart';
import '../../data/models/user.dart';

// Port of frontend/src/stores/authStore.ts. `booted` gates the splash: until it flips,
// `BootGate` covers the tree and the router's redirect stays out of the way, so no route
// is built before we know whether there is a session (and before there is a token for it
// to send). Unlike the React version this runs *after* runApp — see main().
class AuthState {
  final User? user;
  final bool isLoading;
  final String? error;
  final bool booted;

  /// Boot reached the network and the network lost. Distinct from "not signed in":
  /// the stored tokens are still here and probably still valid, so the right screen
  /// is a retry, not the login form. Only ever true while [user] is null.
  ///
  /// Set only by [AuthNotifier.bootstrap], and deliberately not carried by [copyWith] —
  /// every caller of `copyWith` is a post-boot action that only got to run because the
  /// network answered, so clearing it there is the correct default.
  final bool bootOffline;

  const AuthState({
    this.user,
    this.isLoading = false,
    this.error,
    this.booted = false,
    this.bootOffline = false,
  });

  bool get isAuthenticated => user != null;

  AuthState copyWith({User? user, bool? isLoading, String? error, bool? booted, bool clearError = false}) =>
      AuthState(
        user: user ?? this.user,
        isLoading: isLoading ?? this.isLoading,
        error: clearError ? null : (error ?? this.error),
        booted: booted ?? this.booted,
      );
}

class AuthNotifier extends Notifier<AuthState> {
  final _api = AuthApi();

  /// 登出前的 best-effort 收尾。目前唯一的使用者是 FCM token 反註冊
  /// （features/doctor/doctor_push_watcher.dart）。
  ///
  /// 為什麼是「登出**前**」：反註冊要打 `DELETE /notifications/fcm-token/{token}`，
  /// 而 `_api.logout()` 之後 access token 就作廢、TokenStore 也清了，那時再打只會 401。
  static final List<Future<void> Function()> preLogoutHooks = [];

  /// 逐一執行 hook，任何失敗都吞掉——推播收尾不得擋住登出這件事本身。
  /// 走複本疊代，讓 hook 自己在執行中移除自己也安全。
  static Future<void> runPreLogoutHooks() async {
    for (final hook in List.of(preLogoutHooks)) {
      try {
        await hook();
      } catch (_) {/* best-effort */}
    }
  }

  @override
  AuthState build() => const AuthState();

  /// How long boot waits for `getMe()` before showing a retry. Deliberately far below
  /// Dio's 30 s connect/receive timeout: 30 s of nothing-on-screen is indistinguishable
  /// from a hung app, and the retry costs one tap.
  static const bootProfileTimeout = Duration(seconds: 8);

  Future<void> bootstrap() async {
    // `load()` must be inside the try. On web it reaches flutter_secure_storage, which
    // throws `UnsupportedError` outside a secure context (plain http:// — e.g. a clinic
    // LAN deployment). An escaping throw here leaves `booted` false forever, and
    // BootGate would sit on the splash with no way in at all.
    try {
      await TokenStore.instance.load();
    } catch (_) {
      state = const AuthState(booted: true);
      return;
    }

    if (TokenStore.instance.accessToken == null) {
      state = const AuthState(booted: true);
      return;
    }

    try {
      final user = await _api.getMe().timeout(bootProfileTimeout);
      state = AuthState(user: user, booted: true);
    } catch (e) {
      // Only an actual rejection means the session is gone. Until 2026-08-22 every
      // failure took this branch and wiped the refresh token, so one flaky moment on
      // hospital wifi silently signed the doctor out and made them type a password
      // again — the tokens were fine, the network was not.
      if (_isSessionRejection(e)) {
        try {
          await TokenStore.instance.clear();
        } catch (_) {/* storage unavailable — nothing to clear */}
        state = const AuthState(booted: true);
      } else {
        state = const AuthState(booted: true, bootOffline: true);
      }
    }
  }

  /// Re-run the profile fetch after a `bootOffline` failure (the retry button).
  Future<void> retryBootstrap() async {
    state = const AuthState(booted: false);
    await bootstrap();
  }

  /// The way out of a `bootOffline` screen that retrying will not fix — a revoked
  /// account, a backend that is down for the evening, or simply wanting to sign in as
  /// somebody else. Without it, holding a stored token while the server is unreachable
  /// is a dead end: the login form sits behind the router, and the router is behind
  /// boot. Everything here is local, because the network is the thing that failed;
  /// `logout()` is not usable for this since it starts with a REST call.
  Future<void> abandonBootAndSignOut() async {
    try {
      await TokenStore.instance.clear();
    } catch (_) {/* storage unavailable — nothing to clear */}
    state = const AuthState(booted: true);
  }

  /// 401/403 = the server refused these credentials. Anything else — timeout, DNS,
  /// connection reset, 5xx, a Railway cold start — is transport, and transport is not
  /// a reason to destroy a session.
  ///
  /// Note a 401 usually never reaches here: the Dio interceptor refreshes and retries
  /// first, and only a failed refresh clears the store and calls `onAuthCleared`. This
  /// covers the case where it does (refresh token itself rejected).
  static bool _isSessionRejection(Object e) {
    if (e is! DioException) return false;
    final code = e.response?.statusCode;
    return code == 401 || code == 403;
  }

  Future<void> login(String email, String password) async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final r = await _api.login(email, password);
      await TokenStore.instance.save(access: r.accessToken, refresh: r.refreshToken);
      state = AuthState(user: r.user, booted: true);
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _errorMessage(e));
      rethrow;
    }
  }

  Future<void> register(String email, String password, String name) async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final r = await _api.register(email: email, password: password, name: name);
      await TokenStore.instance.save(access: r.accessToken, refresh: r.refreshToken);
      state = AuthState(user: r.user, booted: true);
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _errorMessage(e));
      rethrow;
    }
  }

  Future<void> logout() async {
    await runPreLogoutHooks();
    await _api.logout();
    await TokenStore.instance.clear();
    state = const AuthState(booted: true);
  }

  Future<void> updateProfile(Map<String, dynamic> payload) async {
    final user = await _api.updateMe(payload);
    state = state.copyWith(user: user);
  }

  // Called by the Dio interceptor when a 401 refresh fails.
  void forceLoggedOut() => state = const AuthState(booted: true);

  String _errorMessage(Object e) {
    if (e is DioException) {
      final data = e.response?.data;
      if (data is Map) {
        final err = data['error'];
        if (err is Map && err['message'] != null) return err['message'].toString();
        if (data['detail'] != null) return data['detail'].toString();
      }
    }
    return 'errorGeneric';
  }
}

final authProvider = NotifierProvider<AuthNotifier, AuthState>(AuthNotifier.new);
