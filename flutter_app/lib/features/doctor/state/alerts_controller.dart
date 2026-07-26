import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/i18n/loc.dart';
import '../../../data/api/alerts_api.dart';
import '../../../data/models/alert.dart';
import '../services/dashboard_ws.dart';

int _clampNonNeg(int v) => v < 0 ? 0 : v;

class AlertsState {
  final List<RedFlagAlert> alerts;
  final int unacknowledgedCount;
  final int totalCount;
  final int allTotalCount;
  final bool isLoading;
  final String? cursor;
  final bool hasMore;
  final String filter; // all | unacknowledged | acknowledged
  final String? error;

  const AlertsState({
    this.alerts = const [],
    this.unacknowledgedCount = 0,
    this.totalCount = 0,
    this.allTotalCount = 0,
    this.isLoading = false,
    this.cursor,
    this.hasMore = true,
    this.filter = 'all',
    this.error,
  });

  AlertsState copyWith({
    List<RedFlagAlert>? alerts,
    int? unacknowledgedCount,
    int? totalCount,
    int? allTotalCount,
    bool? isLoading,
    String? cursor,
    bool clearCursor = false,
    bool? hasMore,
    String? filter,
    String? error,
    bool clearError = false,
  }) =>
      AlertsState(
        alerts: alerts ?? this.alerts,
        unacknowledgedCount: unacknowledgedCount ?? this.unacknowledgedCount,
        totalCount: totalCount ?? this.totalCount,
        allTotalCount: allTotalCount ?? this.allTotalCount,
        isLoading: isLoading ?? this.isLoading,
        cursor: clearCursor ? null : (cursor ?? this.cursor),
        hasMore: hasMore ?? this.hasMore,
        filter: filter ?? this.filter,
        error: clearError ? null : (error ?? this.error),
      );
}

const _wsEvents = ['new_red_flag', 'red_flag_acknowledged', 'initial_state', 'stats_updated'];

class AlertsController extends Notifier<AlertsState> {
  final _api = AlertsApi();

  bool? _ackParam(String filter) => switch (filter) {
        'unacknowledged' => false,
        'acknowledged' => true,
        _ => null,
      };

  @override
  AlertsState build() {
    final ws = ref.read(dashboardWsProvider)..ensureConnected();
    for (final e in _wsEvents) {
      ws.on(e, _onEvent);
    }
    ref.onDispose(() {
      for (final e in _wsEvents) {
        ws.off(e, _onEvent);
      }
    });
    Future.microtask(() async {
      await fetchAlerts();
      await fetchUnacknowledgedCount();
    });
    return const AlertsState(isLoading: true);
  }

  Future<void> fetchAlerts() async {
    state = state.copyWith(isLoading: true, clearError: true, clearCursor: true);
    try {
      final page = await _api.list(acknowledged: _ackParam(state.filter));
      state = state.copyWith(
        alerts: page.data,
        cursor: page.nextCursor,
        hasMore: page.hasMore,
        totalCount: page.totalCount,
        allTotalCount: state.filter == 'all' ? page.totalCount : state.allTotalCount,
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
      final page = await _api.list(cursor: state.cursor, acknowledged: _ackParam(state.filter));
      state = state.copyWith(
        alerts: [...state.alerts, ...page.data],
        cursor: page.nextCursor,
        hasMore: page.hasMore,
        totalCount: page.totalCount,
        isLoading: false,
      );
    } catch (_) {
      state = state.copyWith(isLoading: false, error: t('common.unknownError'));
    }
  }

  void setFilter(String filter) {
    if (filter == state.filter) return;
    state = state.copyWith(filter: filter);
    fetchAlerts();
  }

  Future<void> acknowledge(String id, {String? actionTaken, String? notes}) async {
    try {
      final resp = await _api.acknowledge(id, actionTaken: actionTaken, notes: notes);
      final ackAt = resp['acknowledgedAt'] as String? ?? DateTime.now().toUtc().toIso8601String();
      final ackBy = resp['acknowledgedBy'] as String?;
      if (state.filter == 'unacknowledged') {
        state = state.copyWith(
          alerts: state.alerts.where((a) => a.id != id).toList(),
          totalCount: _clampNonNeg(state.totalCount - 1),
          unacknowledgedCount: _clampNonNeg(state.unacknowledgedCount - 1),
        );
      } else {
        state = state.copyWith(
          alerts: [
            for (final a in state.alerts)
              if (a.id == id)
                a.mergeAck(acknowledgedAt: ackAt, acknowledgedBy: ackBy, acknowledgeNotes: notes, actionTaken: actionTaken)
              else
                a
          ],
          unacknowledgedCount: _clampNonNeg(state.unacknowledgedCount - 1),
        );
      }
    } catch (_) {
      state = state.copyWith(error: t('common.unknownError'));
    }
  }

  Future<void> fetchUnacknowledgedCount() async {
    try {
      state = state.copyWith(unacknowledgedCount: await _api.unacknowledgedCount());
    } catch (_) {/* silent */}
  }

  // ---- WS ----

  void _onEvent(dynamic payload, Map message) {
    final p = payload is Map ? payload : const {};
    switch (message['type']) {
      case 'new_red_flag':
        _addNewAlert(p);
      case 'red_flag_acknowledged':
        _ackFromWs(p['alertId'] as String?, p['acknowledgedBy'] as String?);
      case 'initial_state':
        fetchAlerts();
        fetchUnacknowledgedCount();
      case 'stats_updated':
        fetchUnacknowledgedCount();
    }
  }

  void _addNewAlert(Map p) {
    final alert = RedFlagAlert(
      id: (p['alertId'] ?? '') as String,
      sessionId: (p['sessionId'] ?? '') as String,
      severity: (p['severity'] ?? 'medium') as String,
      title: (p['title'] ?? '') as String,
      description: p['description'] as String?,
      triggerReason: (p['description'] ?? '') as String,
      createdAt: DateTime.now().toUtc().toIso8601String(),
    );
    state = state.copyWith(
      alerts: [alert, ...state.alerts],
      unacknowledgedCount: state.unacknowledgedCount + 1,
      totalCount: state.totalCount + 1,
      allTotalCount: state.allTotalCount + 1,
    );
  }

  void _ackFromWs(String? id, String? by) {
    if (id == null) return;
    final now = DateTime.now().toUtc().toIso8601String();
    state = state.copyWith(
      alerts: [
        for (final a in state.alerts)
          if (a.id == id) a.mergeAck(acknowledgedAt: now, acknowledgedBy: by) else a
      ],
      unacknowledgedCount: _clampNonNeg(state.unacknowledgedCount - 1),
    );
  }
}

final alertsProvider = NotifierProvider<AlertsController, AlertsState>(AlertsController.new);
