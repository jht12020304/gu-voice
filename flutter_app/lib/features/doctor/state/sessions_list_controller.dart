import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../data/api/sessions_api.dart';
import '../../../data/models/session.dart';
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
  const SessionsListState({this.sessions = const [], this.isLoading = true, this.hasError = false});

  SessionsListState copyWith({List<Session>? sessions, bool? isLoading, bool? hasError}) => SessionsListState(
    sessions: sessions ?? this.sessions,
    isLoading: isLoading ?? this.isLoading,
    hasError: hasError ?? this.hasError,
  );
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
    if (ws == null) return const SessionsListState(isLoading: false);
    ws.ensureConnected();
    ref.onDispose(() => _refreshTimer?.cancel());
    // Register once (ref-stable); the handler always calls the freshest reload().
    bindWsEvents(ref, ws, _reloadEvents, _onEvent);
    Future.microtask(() async {
      if (lifecycle.mounted && !ws.isDisposed) await reload();
    });
    return const SessionsListState();
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
      final data = await _api.getSessions(limit: 50);
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
