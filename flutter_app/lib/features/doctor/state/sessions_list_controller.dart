import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../data/api/sessions_api.dart';
import '../../../data/models/session.dart';
import '../screens/session_calendar_view.dart' show isoWithOffset;
import '../services/dashboard_ws.dart';
import 'request_seq.dart';

// These dashboard events mean "something changed, refetch over HTTP" — the payloads are
// NOT merged into the list.
const _reloadEvents = [
  'initial_state',
  'queue_updated',
  'session_created',
  'session_status_changed',
  'report_generated',
];

class SessionsListState {
  final List<Session> sessions;
  final bool isLoading;
  final bool hasError;

  /// 篩選的那一天（裝置本地 00:00）；null＝不限日期（最新 50 筆）。
  /// 預設是今天——醫師一登入要先看到「今天有哪些病人」（2026-11-08 需求）。
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
  Timer? _refreshTimer;
  final _seq = RequestSeq();
  int _inFlight = 0;
  bool _pending = false;

  @override
  SessionsListState build() {
    _seq.next();
    _refreshTimer?.cancel();
    _refreshTimer = null;
    _inFlight = 0;
    _pending = false;
    final lifecycle = ref;
    final ws = ref.watch(dashboardWsProvider);
    // build() 只在登入身分（WS）換掉時重跑，所以每次登入都回到「今天」。
    if (ws == null) return SessionsListState(isLoading: false, day: _today());
    ws.ensureConnected();
    ref.onDispose(() => _refreshTimer?.cancel());
    // Register once (ref-stable); the handler always calls the freshest reload().
    bindWsEvents(ref, ws, _reloadEvents, _onEvent);
    Future.microtask(() async {
      if (lifecycle.mounted && !ws.isDisposed) await reload();
    });
    return SessionsListState(day: _today());
  }

  /// 換日期：清掉舊清單（避免把前一天的病人誤當這天的），再重抓。
  void setDay(DateTime? day) {
    state = SessionsListState(day: day);
    unawaited(reload());
  }

  void _onEvent(dynamic payload, Map message) {
    _pending = true;
    _refreshTimer ??= Timer(const Duration(milliseconds: 100), () {
      _refreshTimer = null;
      if (_inFlight == 0) unawaited(reload());
    });
  }

  Future<void> reload() async {
    final lifecycle = ref;
    final ws = ref.read(dashboardWsProvider);
    if (ws == null || ws.isDisposed) return;
    final request = _seq.next();
    ++_inFlight;
    _pending = false;
    try {
      final day = state.day;
      // 日界線用裝置時區（帶位移），同日曆檢視；後端比對 sessions.created_at。
      // ponytail: 一天上限 100 筆（後端 limit 上限），超過再改走游標翻頁。
      final data = day == null
          ? await _api.getSessions(limit: 50)
          : await _api.getSessions(
              limit: 100,
              dateFrom: isoWithOffset(day),
              dateTo: isoWithOffset(DateTime(day.year, day.month, day.day + 1).subtract(const Duration(microseconds: 1))),
            );
      if (!lifecycle.mounted || ws.isDisposed || _seq.isStale(request)) return;
      state = state.copyWith(sessions: data, isLoading: false, hasError: false);
    } catch (_) {
      if (!lifecycle.mounted || ws.isDisposed || _seq.isStale(request)) return;
      // A failed background reload must NOT wipe an already-loaded list.
      state = state.copyWith(isLoading: false, hasError: true);
    } finally {
      if (lifecycle.mounted && !ws.isDisposed) {
        --_inFlight;
        if (_inFlight == 0 && _pending && _refreshTimer == null) {
          unawaited(reload());
        }
      }
    }
  }
}

final sessionsListProvider = NotifierProvider<SessionsListController, SessionsListState>(SessionsListController.new);
