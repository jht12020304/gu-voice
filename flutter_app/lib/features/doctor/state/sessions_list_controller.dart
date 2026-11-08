import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../data/api/sessions_api.dart';
import '../../../data/models/session.dart';
import '../screens/session_calendar_view.dart' show isoWithOffset;
import '../services/dashboard_ws.dart';

// These dashboard events mean "something changed, refetch over HTTP" — the payloads are
// NOT merged into the list.
const _reloadEvents = ['initial_state', 'queue_updated', 'session_created', 'session_status_changed', 'report_generated'];

class SessionsListState {
  final List<Session> sessions;
  final bool isLoading;
  final bool hasError;

  /// 篩選的那一天（裝置本地 00:00）；null＝不限日期（最新 50 筆）。預設今天。
  final DateTime? day;
  const SessionsListState({this.sessions = const [], this.isLoading = true, this.hasError = false, this.day});

  SessionsListState copyWith({List<Session>? sessions, bool? isLoading, bool? hasError}) => SessionsListState(
        sessions: sessions ?? this.sessions,
        isLoading: isLoading ?? this.isLoading,
        hasError: hasError ?? this.hasError,
        day: day,
      );
}

DateTime _today() {
  final now = DateTime.now();
  return DateTime(now.year, now.month, now.day);
}

class SessionsListController extends Notifier<SessionsListState> {
  final _api = SessionsApi();

  @override
  SessionsListState build() {
    final ws = ref.read(dashboardWsProvider)..ensureConnected();
    // Register once (ref-stable); the handler always calls the freshest reload().
    for (final e in _reloadEvents) {
      ws.on(e, _onEvent);
    }
    ref.onDispose(() {
      for (final e in _reloadEvents) {
        ws.off(e, _onEvent);
      }
    });
    Future.microtask(reload);
    return SessionsListState(day: _today());
  }

  int _seq = 0;

  /// 換日期：清掉舊清單再重抓。
  void setDay(DateTime? day) {
    state = SessionsListState(day: day);
    unawaited(reload());
  }

  void _onEvent(dynamic payload, Map message) => reload();

  Future<void> reload() async {
    final request = ++_seq;
    try {
      final day = state.day;
      // ponytail: 一天上限 100 筆（後端 limit 上限）
      final data = day == null
          ? await _api.getSessions(limit: 50)
          : await _api.getSessions(
              limit: 100,
              dateFrom: isoWithOffset(day),
              dateTo: isoWithOffset(DateTime(day.year, day.month, day.day + 1).subtract(const Duration(microseconds: 1))),
            );
      if (request != _seq) return;
      state = state.copyWith(sessions: data, isLoading: false, hasError: false);
    } catch (_) {
      if (request != _seq) return;
      // A failed background reload must NOT wipe an already-loaded list.
      state = state.copyWith(isLoading: false, hasError: true);
    }
  }
}

final sessionsListProvider = NotifierProvider<SessionsListController, SessionsListState>(SessionsListController.new);
