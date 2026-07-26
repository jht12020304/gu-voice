import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/models/session.dart';
import '../../../shared/format.dart';
import '../../../shared/widgets/status_badge.dart';
import '../state/sessions_list_controller.dart';

// Port of SessionListPage.tsx — WS-driven reload, client-side status filter + search.
class SessionListPage extends ConsumerStatefulWidget {
  const SessionListPage({super.key});

  @override
  ConsumerState<SessionListPage> createState() => _SessionListPageState();
}

class _SessionListPageState extends ConsumerState<SessionListPage> {
  String _statusFilter = '';
  String _search = '';

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
      appBar: AppBar(title: Text(t('session.doctor.list.title'))),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
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

  Widget _filterTabs() {
    const filters = {
      '': 'session.doctor.list.tabAll',
      'in_progress': 'session.doctor.list.tabInProgress',
      'waiting': 'session.doctor.list.tabWaiting',
      'completed': 'session.doctor.list.tabCompleted',
    };
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(children: [
        for (final e in filters.entries)
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              selected: _statusFilter == e.key,
              label: Text(t(e.value)),
              onSelected: (_) => setState(() => _statusFilter = e.key),
            ),
          ),
      ]),
    );
  }

  Widget _body(BuildContext context, SessionsListState st, List<Session> visible) {
    if (st.isLoading && st.sessions.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (st.hasError && st.sessions.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(t('session.doctor.detail.loadError')),
          const SizedBox(height: 8),
          FilledButton(onPressed: () => ref.read(sessionsListProvider.notifier).reload(), child: Text(t('common.retry'))),
        ]),
      );
    }
    if (visible.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(t('session.doctor.list.emptyTitle'), style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(t('session.doctor.list.emptyMessage')),
        ]),
      );
    }
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [for (final s in visible) _card(context, s)],
    );
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
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
              decoration: BoxDecoration(color: tk.alertCriticalBg, borderRadius: BorderRadius.circular(4)),
              child: Text(t('session.doctor.list.redFlagBadge'),
                  style: TextStyle(color: tk.alertCritical, fontSize: 11)),
            ),
          ],
        ]),
        subtitle: Text('$name · ${s.durationSeconds != null ? '${durationMinutes(s.durationSeconds)} min' : formatDateTime(s.createdAt)}'),
        trailing: StatusBadge(s.status),
      ),
    );
  }
}
