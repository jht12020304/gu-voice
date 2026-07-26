import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/models/alert.dart';
import '../../../shared/format.dart';
import '../state/alerts_controller.dart';

const _severityRank = {'critical': 0, 'high': 1, 'medium': 2};

class AlertListPage extends ConsumerStatefulWidget {
  const AlertListPage({super.key});

  @override
  ConsumerState<AlertListPage> createState() => _AlertListPageState();
}

class _AlertListPageState extends ConsumerState<AlertListPage> {
  final _scroll = ScrollController();
  String _search = '';
  String _lastLng = currentLng;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 300) {
        ref.read(alertsProvider.notifier).fetchMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  List<RedFlagAlert> _visible(List<RedFlagAlert> all) {
    final q = _search.trim().toLowerCase();
    if (q.isEmpty) return all;
    return all.where((a) => '${a.title} ${a.description ?? ''} ${a.triggerReason}'.toLowerCase().contains(q)).toList();
  }

  // date -> sorted alerts, newest day first; within day: unacked-first, severity, newer.
  List<MapEntry<String, List<RedFlagAlert>>> _grouped(List<RedFlagAlert> alerts) {
    final sorted = [...alerts]..sort((a, b) => b.createdAt.compareTo(a.createdAt));
    final groups = <String, List<RedFlagAlert>>{};
    for (final a in sorted) {
      final key = a.createdAt.length >= 10 ? a.createdAt.substring(0, 10) : 'unknown';
      groups.putIfAbsent(key, () => []).add(a);
    }
    for (final list in groups.values) {
      list.sort((a, b) {
        if (a.acknowledged != b.acknowledged) return a.acknowledged ? 1 : -1;
        final sr = (_severityRank[a.severity] ?? 3).compareTo(_severityRank[b.severity] ?? 3);
        if (sr != 0) return sr;
        return b.createdAt.compareTo(a.createdAt);
      });
    }
    return groups.entries.toList();
  }

  @override
  Widget build(BuildContext context) {
    // Refetch on language change (backend localizes alert strings per Accept-Language).
    if (_lastLng != currentLng) {
      _lastLng = currentLng;
      Future.microtask(ref.read(alertsProvider.notifier).fetchAlerts);
    }
    final st = ref.watch(alertsProvider);
    final visible = _visible(st.alerts);
    final groups = _grouped(visible);

    return Scaffold(
      appBar: AppBar(title: Text(t('dashboard.sidebar.nav.redFlagAlerts'))),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: TextField(
              decoration: InputDecoration(prefixIcon: const Icon(Icons.search), hintText: t('dashboard.alertList.searchPlaceholder')),
              onChanged: (v) => setState(() => _search = v),
            ),
          ),
          _filterTabs(st.filter),
          Expanded(child: _body(context, st, groups)),
        ],
      ),
    );
  }

  Widget _filterTabs(String filter) {
    const filters = {
      'all': 'dashboard.alertList.filters.all',
      'unacknowledged': 'dashboard.alertList.filters.unacknowledged',
      'acknowledged': 'dashboard.alertList.filters.acknowledged',
    };
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(children: [
        for (final e in filters.entries)
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              selected: filter == e.key,
              label: Text(t(e.value)),
              onSelected: (_) => ref.read(alertsProvider.notifier).setFilter(e.key),
            ),
          ),
      ]),
    );
  }

  Widget _body(BuildContext context, AlertsState st, List<MapEntry<String, List<RedFlagAlert>>> groups) {
    if (st.isLoading && st.alerts.isEmpty) return const Center(child: CircularProgressIndicator());
    if (st.error != null && st.alerts.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(st.error!),
          const SizedBox(height: 8),
          FilledButton(onPressed: ref.read(alertsProvider.notifier).fetchAlerts, child: Text(t('common.retry'))),
        ]),
      );
    }
    if (groups.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(t('dashboard.alertList.emptyTitle'), style: Theme.of(context).textTheme.titleMedium),
          Text(t('dashboard.alertList.emptyMessage')),
        ]),
      );
    }
    return ListView(
      controller: _scroll,
      padding: const EdgeInsets.all(16),
      children: [
        for (final g in groups) ...[
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text('${g.key}  ·  ${t('dashboard.alertList.groupCount', args: {'count': g.value.length})}',
                style: Theme.of(context).textTheme.labelMedium),
          ),
          for (final a in g.value) _card(context, a),
        ],
        if (st.isLoading) const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator())),
        if (!st.hasMore) Center(child: Padding(padding: const EdgeInsets.all(12), child: Text(t('common.pagination.allLoaded')))),
      ],
    );
  }

  Widget _card(BuildContext context, RedFlagAlert a) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final sevColor = switch (a.severity) {
      'critical' => tk.alertCritical,
      'high' => tk.alertHigh,
      _ => tk.alertMedium,
    };
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: InkWell(
        onTap: () => context.go(prefixLngToPath('/alerts/${a.id}', currentLng)),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(color: sevColor.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(9999)),
                child: Text(a.severity.toUpperCase(), style: TextStyle(color: sevColor, fontSize: 11, fontWeight: FontWeight.w700)),
              ),
              const SizedBox(width: 8),
              Expanded(child: Text(a.title, style: const TextStyle(fontWeight: FontWeight.w600))),
              Text(a.acknowledged ? t('dashboard.alert.acknowledged') : t('dashboard.alert.pending'),
                  style: TextStyle(fontSize: 12, color: a.acknowledged ? tk.statusCompleted : tk.alertHigh)),
            ]),
            if (a.triggerReason.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(t('dashboard.alert.triggerLabel', args: {'value': a.triggerReason}),
                  style: Theme.of(context).textTheme.bodySmall),
            ],
            const SizedBox(height: 6),
            Row(children: [
              Text(formatDateTime(a.createdAt), style: Theme.of(context).textTheme.bodySmall),
              const Spacer(),
              if (!a.acknowledged)
                TextButton(
                  onPressed: () => ref.read(alertsProvider.notifier).acknowledge(a.id),
                  child: Text(t('dashboard.alert.acknowledge')),
                ),
            ]),
          ]),
        ),
      ),
    );
  }
}
