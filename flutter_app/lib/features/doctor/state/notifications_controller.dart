import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/i18n/loc.dart';
import '../../../data/api/notifications_api.dart';
import '../../../data/models/notification.dart';
import '../services/dashboard_ws.dart';

int _clampNonNeg(int v) => v < 0 ? 0 : v;

class NotifState {
  final List<AppNotification> notifications;
  final int unreadCount;
  final bool isLoading;
  final String? cursor;
  final bool hasMore;
  final String? error;

  const NotifState({
    this.notifications = const [],
    this.unreadCount = 0,
    this.isLoading = false,
    this.cursor,
    this.hasMore = true,
    this.error,
  });

  NotifState copyWith({
    List<AppNotification>? notifications,
    int? unreadCount,
    bool? isLoading,
    String? cursor,
    bool clearCursor = false,
    bool? hasMore,
    String? error,
    bool clearError = false,
  }) =>
      NotifState(
        notifications: notifications ?? this.notifications,
        unreadCount: unreadCount ?? this.unreadCount,
        isLoading: isLoading ?? this.isLoading,
        cursor: clearCursor ? null : (cursor ?? this.cursor),
        hasMore: hasMore ?? this.hasMore,
        error: clearError ? null : (error ?? this.error),
      );
}

// Dashboard WS events that coincide with a doctor notification being created:
//   session_status_changed → SESSION_COMPLETE / RED_FLAG (terminal transitions)
//   report_generated       → REPORT_READY
//   new_red_flag           → RED_FLAG
// initial_state is the dashboard snapshot the backend sends on (re)connect; a second one
// means the socket reconnected, so anything missed while offline has to be re-fetched.
//
// 不變式 #27：這份清單是「手抄兩份」的其中一份，字串必須與後端實際廣播的一致。
// 核實來源：backend/app/websocket/conversation_handler.py（session_status_changed /
// new_red_flag）、app/tasks/report_queue.py（report_generated）、
// app/tasks/session_timeout.py（session_status_changed/cancelled）、
// app/websocket/dashboard_handler.py（initial_state）。
const _wsEvents = ['session_status_changed', 'report_generated', 'new_red_flag', 'initial_state'];

// `session_status_changed` also fires for `in_progress` (patient WS connected), which
// creates no notification. Only terminal transitions do. Payload key is camelCase.
const _terminalStatuses = {'completed', 'aborted_red_flag', 'cancelled'};

// Trailing debounce, for two reasons:
//  1. one terminal transition emits several of these events back-to-back
//     (session_status_changed + report_generated + new_red_flag) — one refetch is enough;
//  2. the backend publishes `report_generated` BEFORE the REPORT_READY row is committed
//     (report_queue.py: publish, then a second transaction for the notification), so an
//     instant refetch can legitimately race ahead of the row it came to collect.
const _defaultRefreshDebounce = Duration(milliseconds: 400);

class NotificationsController extends Notifier<NotifState> {
  NotificationsController({
    NotificationsApi? api,
    Duration refreshDebounce = _defaultRefreshDebounce,
  })  : _api = api ?? NotificationsApi(),
        _refreshDebounce = refreshDebounce;

  final NotificationsApi _api;
  final Duration _refreshDebounce;
  Timer? _refreshTimer;
  // Riverpod throws if `state` is written after dispose, and a refetch in flight when the
  // doctor logs out lands exactly there.
  bool _disposed = false;
  // build() already fetches, so the first initial_state (WS just connected) is redundant.
  bool _skipNextInitialState = true;

  @override
  NotifState build() {
    final ws = ref.read(dashboardWsProvider)..ensureConnected();
    for (final e in _wsEvents) {
      ws.on(e, _onEvent);
    }
    ref.onDispose(() {
      _disposed = true;
      _refreshTimer?.cancel();
      _refreshTimer = null;
      for (final e in _wsEvents) {
        ws.off(e, _onEvent);
      }
    });
    // Concurrent, not sequential. These are two independent endpoints writing disjoint
    // fields of the same state, and on iOS this is the landing screen — chaining them
    // put a second full round trip to Railway between the doctor and their inbox for
    // no reason. Neither throws (both swallow their own errors), so `Future.wait` here
    // cannot leave one half unapplied because the other failed.
    Future.microtask(() => Future.wait([fetch(), fetchUnreadCount()]));
    return const NotifState(isLoading: true);
  }

  Future<void> fetch() async {
    state = state.copyWith(isLoading: true, clearError: true, clearCursor: true);
    try {
      final page = await _api.list();
      if (_disposed) return;
      state = state.copyWith(
        notifications: page.data,
        cursor: page.nextCursor,
        hasMore: page.hasMore,
        isLoading: false,
      );
    } catch (_) {
      if (_disposed) return;
      state = state.copyWith(isLoading: false, error: t('common.unknownError'));
    }
  }

  Future<void> fetchMore() async {
    if (!state.hasMore || state.isLoading || state.cursor == null) return;
    state = state.copyWith(isLoading: true);
    try {
      final page = await _api.list(cursor: state.cursor);
      state = state.copyWith(
        notifications: [...state.notifications, ...page.data],
        cursor: page.nextCursor,
        hasMore: page.hasMore,
        isLoading: false,
      );
    } catch (_) {
      state = state.copyWith(isLoading: false, error: t('common.unknownError'));
    }
  }

  Future<void> markRead(String id) async {
    // optimistic
    final now = DateTime.now().toUtc().toIso8601String();
    state = state.copyWith(
      notifications: [
        for (final n in state.notifications)
          if (n.id == id && !n.isRead) n.copyWith(isRead: true, readAt: now) else n
      ],
      unreadCount: _clampNonNeg(state.unreadCount - 1),
    );
    try {
      await _api.markRead(id);
    } catch (_) {/* silent */}
  }

  Future<void> markAllRead() async {
    try {
      await _api.markAllRead();
      final now = DateTime.now().toUtc().toIso8601String();
      state = state.copyWith(
        notifications: [for (final n in state.notifications) n.copyWith(isRead: true, readAt: n.readAt ?? now)],
        unreadCount: 0,
      );
    } catch (_) {
      state = state.copyWith(error: t('common.unknownError'));
    }
  }

  Future<void> fetchUnreadCount() async {
    try {
      final count = await _api.unreadCount();
      if (_disposed) return;
      state = state.copyWith(unreadCount: count);
    } catch (_) {/* silent */}
  }

  // ---- WS ----

  void _onEvent(dynamic payload, Map message) {
    final p = payload is Map ? payload : const {};
    switch (message['type']) {
      case 'session_status_changed':
        if (_terminalStatuses.contains(p['status'])) _scheduleRefresh();
      case 'report_generated' || 'new_red_flag':
        _scheduleRefresh();
      case 'initial_state':
        if (_skipNextInitialState) {
          _skipNextInitialState = false;
        } else {
          _scheduleRefresh();
        }
    }
  }

  /// Collapses an event burst into a single list + unread-count refetch.
  void _scheduleRefresh() {
    _refreshTimer?.cancel();
    _refreshTimer = Timer(_refreshDebounce, () {
      _refreshTimer = null;
      unawaited(_refresh());
    });
  }

  Future<void> _refresh() async {
    // The tab badge reads `unreadCount` off this same state, so it moves with the list —
    // running both at once keeps that true and halves the time the badge lags the WS event.
    await Future.wait([fetch(), fetchUnreadCount()]);
  }
}

final notificationsProvider = NotifierProvider<NotificationsController, NotifState>(NotificationsController.new);
