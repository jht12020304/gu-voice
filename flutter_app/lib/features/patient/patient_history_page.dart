import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../core/theme/app_tokens.dart';
import '../../data/api/sessions_api.dart';
import '../../data/models/session.dart';
import '../../shared/format.dart';
import '../../shared/widgets/status_badge.dart';
import '../auth/auth_notifier.dart';
import '../../shared/widgets/language_action.dart';

// Port of PatientHistoryPage.tsx: patient-scoped list (limit 50) with client-side status
// filter tabs (all/completed/in_progress/cancelled). No pagination. Subtitle count = total,
// not filtered. Errors are silent (show empty state).
class PatientHistoryPage extends ConsumerStatefulWidget {
  const PatientHistoryPage({super.key});

  @override
  ConsumerState<PatientHistoryPage> createState() => _PatientHistoryPageState();
}

class _PatientHistoryPageState extends ConsumerState<PatientHistoryPage> {
  List<Session> _sessions = [];
  bool _loading = true;
  String _filter = 'all';

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  Future<void> _load() async {
    final user = ref.read(authProvider).user;
    try {
      final list = await SessionsApi().getSessions(limit: 50, patientId: user?.id);
      if (mounted) setState(() { _sessions = list; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _open(Session s) {
    if (s.status == 'completed' || s.status == 'aborted_red_flag') {
      context.go(prefixLngToPath('/patient/session/${s.id}/complete', currentLng));
    } else if (s.status == 'in_progress' || s.status == 'waiting') {
      context.go(prefixLngToPath('/conversation/${s.id}', currentLng), extra: s);
    }
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _filter == 'all' ? _sessions : _sessions.where((s) => s.status == _filter).toList();
    return Scaffold(
      appBar: AppBar(
        title: Text(t('common.patientLayout.history')),
        actions: const [LanguageAction()],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text(t('session.patientHistory.sessionCount', args: {'count': _sessions.length}),
                style: Theme.of(context).textTheme.bodySmall),
          ),
          _filterTabs(),
          Expanded(
            child: _loading
                ? Center(child: Text(t('session.patientHistory.loading')))
                : filtered.isEmpty
                    ? Center(child: Text(t(_filter == 'all'
                        ? 'session.patientHistory.emptyAll'
                        : 'session.patientHistory.emptyFiltered')))
                    : ListView(
                        padding: const EdgeInsets.all(16),
                        children: [for (final s in filtered) _row(context, s)],
                      ),
          ),
        ],
      ),
    );
  }

  Widget _filterTabs() {
    const filters = {
      'all': 'session.patientHistory.filters.all',
      'completed': 'session.patientHistory.filters.completed',
      'in_progress': 'session.patientHistory.filters.inProgress',
      'cancelled': 'session.patientHistory.filters.cancelled',
    };
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          for (final e in filters.entries)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                selected: _filter == e.key,
                label: Text(t(e.value)),
                onSelected: (_) => setState(() => _filter = e.key),
              ),
            ),
        ],
      ),
    );
  }

  Widget _row(BuildContext context, Session s) {
    final redFlagColor = Theme.of(context).extension<AppTokens>()!.statusRedFlag;
    final duration = s.durationSeconds != null
        ? ' · ${t('session.patientHistory.durationMinutes', args: {'minutes': durationMinutes(s.durationSeconds)})}'
        : '';
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        onTap: () => _open(s),
        leading: s.redFlag ? Container(width: 3, height: 40, color: redFlagColor) : null,
        title: Text(s.chiefComplaintText ?? t('common.patient.home.defaultComplaint')),
        subtitle: Text('${formatDateTime(s.createdAt)}$duration'),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [StatusBadge(s.status), const SizedBox(width: 4), const Icon(Icons.chevron_right)],
        ),
      ),
    );
  }
}
