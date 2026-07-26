import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/auth_api.dart';
import '../../data/api/token_store.dart';
import '../../data/models/user.dart';

// Port of frontend/src/stores/authStore.ts. `booted` gates the splash: the app
// bootstraps (loads token + getMe) before runApp, so the first frame already knows
// whether there is a session.
class AuthState {
  final User? user;
  final bool isLoading;
  final String? error;
  final bool booted;

  const AuthState({this.user, this.isLoading = false, this.error, this.booted = false});

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

  @override
  AuthState build() => const AuthState();

  Future<void> bootstrap() async {
    // `load()` must be inside the try. On web it reaches flutter_secure_storage, which
    // throws `UnsupportedError` outside a secure context (plain http:// — e.g. a clinic
    // LAN deployment). `main()` awaits bootstrap BEFORE runApp, so an escaping throw
    // meant a white screen with no way in at all, rather than just "not signed in".
    try {
      await TokenStore.instance.load();
      if (TokenStore.instance.accessToken == null) {
        state = const AuthState(booted: true);
        return;
      }
      final user = await _api.getMe();
      state = AuthState(user: user, booted: true);
    } catch (_) {
      // Best-effort cleanup; if storage itself is unavailable this throws too.
      try {
        await TokenStore.instance.clear();
      } catch (_) {/* storage unavailable — nothing to clear */}
      state = const AuthState(booted: true);
    }
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
