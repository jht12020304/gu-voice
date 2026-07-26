import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../data/api/sessions_api.dart';
import '../../../data/models/session.dart';
import '../services/dashboard_ws.dart';

// These dashboard events mean "something changed, refetch over HTTP" — the payloads are
// NOT merged into the list.
const _reloadEvents = ['initial_state', 'queue_updated', 'session_created', 'session_status_changed', 'report_generated'];

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
    return const SessionsListState();
  }

  void _onEvent(dynamic payload, Map message) => reload();

  Future<void> reload() async {
    try {
      final data = await _api.getSessions(limit: 50);
      state = state.copyWith(sessions: data, isLoading: false, hasError: false);
    } catch (_) {
      // A failed background reload must NOT wipe an already-loaded list.
      state = state.copyWith(isLoading: false, hasError: true);
    }
  }
}

final sessionsListProvider = NotifierProvider<SessionsListController, SessionsListState>(SessionsListController.new);
