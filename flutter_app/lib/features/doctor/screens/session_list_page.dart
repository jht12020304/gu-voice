import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/models/session.dart';
import '../../../shared/format.dart';
import '../../../shared/widgets/status_badge.dart';
import '../../../shared/widgets/ui_kit.dart';
import '../state/sessions_list_controller.dart';
import 'session_calendar_view.dart';

// Port of SessionListPage.tsx — WS-driven reload, client-side status filter + search.
class SessionListPage extends ConsumerStatefulWidget {
  const SessionListPage({super.key});

  @override
  ConsumerState<SessionListPage> createState() => _SessionListPageState();
}

class _SessionListPageState extends ConsumerState<SessionListPage> {
  String _statusFilter = '';
  String _search = '';
  /// 清單 ↔ 日曆。預設清單（既有行為不變）；日曆是「場次一多就翻不到」時的入口，
  /// 由使用者自己切過去（2026-08-23 需求）。刻意不持久化：本來就是一個切換鈕，
  /// 記住它反而會讓下次開 App 的人納悶為什麼看不到熟悉的清單。
  bool _calendarMode = false;

  List<Session> _visible(List<Session> all) {
    final q = _search.trim().toLowerCase();
    return all.where((s) {
      if (_statusFilter.isNotEmpty && s.status != _statusFilter) return false;
      if (q.isEmpty) return true;
      final hay = '${s.patientName ?? ''} ${s.chiefComplaintText ?? ''}'.toLowerCase();
      return hay.contains(q);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final st = ref.watch(sessionsListProvider);
    final visible = _visible(st.sessions);

    return Scaffold(
      appBar: AppBar(
        title: Text(t('session.doctor.list.title')),
        actions: [
          IconButton(
            icon: Icon(_calendarMode ? Icons.view_list_outlined : Icons.calendar_month_outlined),
            tooltip: t(_calendarMode
                ? 'session.doctor.calendar.viewList'
                : 'session.doctor.calendar.viewCalendar'),
            onPressed: () => setState(() => _calendarMode = !_calendarMode),
          ),
        ],
      ),
      // 日曆模式自己管資料（依日期抓整個月），不吃清單的日期列／搜尋／狀態篩選——
      // 清單是「某一天（預設今天）或最新 50 筆」裡找，日曆是看整個月的分布。
      body: _calendarMode
          ? const SessionCalendarView()
          : Column(
              children: [
                _dayBar(context, st.day),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                  child: TextField(
                    decoration: InputDecoration(
                      prefixIcon: const Icon(Icons.search),
                      hintText: t('session.doctor.list.searchPlaceholder'),
                    ),
                    onChanged: (v) => setState(() => _search = v),
                  ),
                ),
                _filterTabs(),
                Expanded(child: _body(context, st, visible)),
              ],
            ),
    );
  }

  /// 日期列：‹ 前一天 ｜ 今天 · 11 月 8 日（日）（點了開日期選擇器）｜ 後一天 › ｜ 全部
  Widget _dayBar(BuildContext context, DateTime? day) {
    final ctrl = ref.read(sessionsListProvider.notifier);
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    String label;
    if (day == null) {
      label = t('session.doctor.list.allDates');
    } else {
      label = t('session.doctor.calendar.dayTitle', args: {
        'month': day.month,
        'day': day.day,
        'weekday': t('session.doctor.calendar.weekday.${const ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][day.weekday - 1]}'),
      });
      final diff = today.difference(day).inDays;
      if (diff == 0) label = '${t('session.doctor.list.today')} · $label';
      if (diff == 1) label = '${t('session.doctor.list.yesterday')} · $label';
    }
    Future<void> pick() async {
      final picked = await showDatePicker(
        context: context,
        initialDate: day ?? today,
        firstDate: DateTime(2024),
        lastDate: today,
      );
      if (picked != null) ctrl.setDay(DateTime(picked.year, picked.month, picked.day));
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 4, 12, 0),
      child: Row(children: [
        IconButton(
          key: const Key('session-day-prev'),
          icon: const Icon(Icons.chevron_left),
          tooltip: t('session.doctor.list.prevDay'),
          onPressed: day == null ? null : () => ctrl.setDay(DateTime(day.year, day.month, day.day - 1)),
        ),
        Expanded(
          child: TextButton.icon(
            key: const Key('session-day-pick'),
            icon: const Icon(Icons.event_outlined, size: 18),
            label: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
            onPressed: pick,
          ),
        ),
        IconButton(
          key: const Key('session-day-next'),
          icon: const Icon(Icons.chevron_right),
          tooltip: t('session.doctor.list.nextDay'),
          onPressed: day == null || !day.isBefore(today) ? null : () => ctrl.setDay(DateTime(day.year, day.month, day.day + 1)),
        ),
        ChoiceChip(
          key: const Key('session-day-all'),
          label: Text(t('session.doctor.list.allDatesShort')),
          showCheckmark: false,
          selected: day == null,
          onSelected: (_) => ctrl.setDay(day == null ? today : null),
        ),
      ]),
    );
  }

  Widget _filterTabs() {
    const filters = {
      '': 'session.doctor.list.tabAll',
      'in_progress': 'session.doctor.list.tabInProgress',
      'waiting': 'session.doctor.list.tabWaiting',
      'completed': 'session.doctor.list.tabCompleted',
    };
    return FilterChipBar<String>(
      options: {for (final e in filters.entries) e.key: t(e.value)},
      selected: _statusFilter,
      onSelected: (key) => setState(() => _statusFilter = key),
    );
  }

  Widget _body(BuildContext context, SessionsListState st, List<Session> visible) {
    if (st.isLoading && st.sessions.isEmpty) {
      return const SkeletonList();
    }
    if (st.hasError && st.sessions.isEmpty) {
      return ErrorState(
        message: t('session.doctor.detail.loadError'),
        retryLabel: t('common.retry'),
        onRetry: () => ref.read(sessionsListProvider.notifier).reload(),
      );
    }
    if (visible.isEmpty && st.day != null && _statusFilter.isEmpty && _search.trim().isEmpty) {
      return EmptyState(
        icon: Icons.event_available_outlined,
        title: t('session.doctor.calendar.emptyDayTitle'),
        message: t('session.doctor.list.emptyDayMessage'),
      );
    }
    if (visible.isEmpty) {
      return EmptyState(
        icon: Icons.forum_outlined,
        title: t('session.doctor.list.emptyTitle'),
        message: t('session.doctor.list.emptyMessage'),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: visible.length,
      itemBuilder: (context, i) => _card(context, visible[i]),
    );
  }

  /// 篩單日時：開始時間 + 時長；不限日期時維持原本（時長或日期時間）。
  String _when(Session s) {
    final minutes = s.durationSeconds != null ? '${durationMinutes(s.durationSeconds)} min' : null;
    if (ref.read(sessionsListProvider).day == null) return minutes ?? formatDateTime(s.createdAt);
    final start = sessionLocalStart(s);
    final clock = start == null ? '—' : '${start.hour.toString().padLeft(2, '0')}:${start.minute.toString().padLeft(2, '0')}';
    return minutes == null ? clock : '$clock · $minutes';
  }

  Widget _card(BuildContext context, Session s) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final name = (s.patientName?.isNotEmpty ?? false) ? s.patientName! : t('session.doctor.list.unknownPatient');
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        onTap: () => context.go(prefixLngToPath('/sessions/${s.id}', currentLng)),
        leading: CircleAvatar(
          backgroundColor: s.redFlag ? tk.alertCriticalBg : null,
          child: Text(name.characters.first, style: TextStyle(color: s.redFlag ? tk.alertCritical : null)),
        ),
        title: Row(children: [
          Flexible(child: Text(s.chiefComplaintText ?? t('session.doctor.list.chiefComplaintEmpty'))),
          if (s.redFlag) ...[
            const SizedBox(width: 6),
            PillTag(t('session.doctor.list.redFlagBadge'), color: tk.alertCritical),
          ],
        ]),
        subtitle: Text('$name · ${_when(s)}'),
        trailing: StatusBadge(s.status),
      ),
    );
  }
}
