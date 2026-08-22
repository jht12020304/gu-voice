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
  /// 只在真的收到 new_red_flag WS 事件時遞增。全域 toast（DoctorAlertWatcher）
  /// 鎖這個序號，不再鎖 unacknowledgedCount——計數會因「登入首載 0→N」與
  /// 「樂觀扣減後被伺服器真值收斂」而上下擺動，鎖它會在每個畫面誤鳴
  /// 「偵測到 N 筆新的紅旗警示」（2026-08-23 使用者實測回報）。
  final int newAlertSeq;
  final String? error;

  const AlertsState({
    this.alerts = const [],
    this.unacknowledgedCount = 0,
    this.newAlertSeq = 0,
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
    int? newAlertSeq,
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
        newAlertSeq: newAlertSeq ?? this.newAlertSeq,
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
      // 靜默收斂伺服器真值（toast 已改鎖 newAlertSeq，計數修正不會誤鳴）
      fetchUnacknowledgedCount();
    } catch (_) {
      state = state.copyWith(error: t('common.unknownError'));
    }
  }

  /// 一鍵確認全部（U1 全院視野後歷史積壓的收斂出口）。回傳實際確認筆數。
  Future<int> acknowledgeAll() async {
    try {
      final n = await _api.acknowledgeAll();
      await fetchAlerts();
      await fetchUnacknowledgedCount();
      return n;
    } catch (_) {
      state = state.copyWith(error: t('common.unknownError'));
      return 0;
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
      newAlertSeq: state.newAlertSeq + 1,
    );
  }

  void _ackFromWs(String? id, String? by) {
    if (id == null) return;
    // 回音去重（2026-08-23）：後端把 red_flag_acknowledged 廣播給**所有**儀表板，
    // 含確認者自己——自己已在 acknowledge() 樂觀扣過一次，再扣＝雙重扣減，
    // 之後 stats_updated 重抓真值時計數回彈、全域 toast 誤鳴「偵測到新警示」。
    // 判準：列上找得到且**還未確認**才算「別的醫師確認了它」；找不到（翻頁外/
    // 篩選外）不猜，交給伺服器真值收斂。
    final idx = state.alerts.indexWhere((a) => a.id == id);
    if (idx < 0) {
      fetchUnacknowledgedCount();
      return;
    }
    if (state.alerts[idx].acknowledged) return; // 自己樂觀處理過的回音
    final now = DateTime.now().toUtc().toIso8601String();
    if (state.filter == 'unacknowledged') {
      // 在「未處理」篩選下別的醫師確認 → 該列移出（否則停在此 tab 會看到
      // 一筆標著已確認的列，稽核 finding）。
      state = state.copyWith(
        alerts: [for (final a in state.alerts) if (a.id != id) a],
        totalCount: _clampNonNeg(state.totalCount - 1),
        unacknowledgedCount: _clampNonNeg(state.unacknowledgedCount - 1),
      );
      return;
    }
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
