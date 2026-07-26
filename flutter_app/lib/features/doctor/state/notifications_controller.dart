import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/i18n/loc.dart';
import '../../../data/api/notifications_api.dart';
import '../../../data/models/notification.dart';

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

class NotificationsController extends Notifier<NotifState> {
  final _api = NotificationsApi();

  @override
  NotifState build() {
    Future.microtask(() async {
      await fetch();
      await fetchUnreadCount();
    });
    return const NotifState(isLoading: true);
  }

  Future<void> fetch() async {
    state = state.copyWith(isLoading: true, clearError: true, clearCursor: true);
    try {
      final page = await _api.list();
      state = state.copyWith(
        notifications: page.data,
        cursor: page.nextCursor,
        hasMore: page.hasMore,
        isLoading: false,
      );
    } catch (_) {
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
      state = state.copyWith(unreadCount: await _api.unreadCount());
    } catch (_) {/* silent */}
  }
}

final notificationsProvider = NotifierProvider<NotificationsController, NotifState>(NotificationsController.new);
