import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/dashboard_api.dart';
import '../../auth/auth_notifier.dart';
import '../research/charts.dart';

// Minimal doctor dashboard landing: month-scoped stat cards. The donut/daily-trend charts
// are Phase 6 (placeholder boxes here).
class DashboardPage extends ConsumerStatefulWidget {
  const DashboardPage({super.key});

  @override
  ConsumerState<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends ConsumerState<DashboardPage> {
  MonthlySummary? _summary;
  bool _loading = true;
  late DateTime _selected; // first-of-month anchor

  String get _month => '${_selected.year.toString().padLeft(4, '0')}-${_selected.month.toString().padLeft(2, '0')}';

  /// 月份標題：一律在前端依 URL 語系（currentLng）組出來，不用後端的 month_label——
  /// 那是硬寫中文，非中文語系的醫師會看到中英混雜的標題。
  ///
  /// 走 t('…monthFormat') 而不是 intl 的 DateFormat.yM：月份寫法在五語系都已定義在
  /// 共用的 i18next JSON（React 端同一支 key），用同一份模板兩邊輸出才一致，
  /// 也不必依賴 intl locale data 是否已初始化。
  String get _monthLabel {
    // 舊版後端沒回 month_key → 退回本地選中的月份，標題不能因此壞掉
    final key = _summary?.month ?? _month;
    final parts = key.split('-');
    final year = parts.length == 2 ? int.tryParse(parts[0]) : null;
    final month = parts.length == 2 ? int.tryParse(parts[1]) : null;
    if (year == null || month == null) return key; // 非預期格式就原樣顯示
    return t('common.doctor.dashboard.monthFormat', args: {'year': year, 'month': month});
  }

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _selected = DateTime(now.year, now.month, 1);
    Future.microtask(_load);
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final s = await DashboardApi().getMonthlySummary(_month);
      if (mounted) setState(() { _summary = s; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _shiftMonth(int delta) {
    setState(() => _selected = DateTime(_selected.year, _selected.month + delta, 1));
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final user = ref.watch(authProvider).user;
    final s = _summary;
    return Scaffold(
      appBar: AppBar(
        title: Text(t('common.appTitle')),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: t('common.header.logout'),
            onPressed: () => ref.read(authProvider.notifier).logout(),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(t('common.doctor.dashboard.eyebrow').toUpperCase(),
              style: Theme.of(context).textTheme.labelMedium),
          Text(t('common.doctor.dashboard.title'),
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text('${user?.name ?? ''} · $_monthLabel'),
          const SizedBox(height: 12),
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            IconButton(
              icon: const Icon(Icons.chevron_left),
              tooltip: t('common.doctor.dashboard.prevMonth'),
              onPressed: _loading ? null : () => _shiftMonth(-1),
            ),
            Text(_monthLabel, style: Theme.of(context).textTheme.titleMedium),
            IconButton(
              icon: const Icon(Icons.chevron_right),
              tooltip: t('common.doctor.dashboard.nextMonth'),
              onPressed: _loading ? null : () => _shiftMonth(1),
            ),
          ]),
          const SizedBox(height: 12),
          if (_loading)
            const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator()))
          else
            Row(children: [
              Expanded(child: _statCard(context, tk.alertCritical, t('common.doctor.dashboard.monthlyTotal', args: {'month': _monthLabel}), '${s?.totalSessions ?? 0}', t('common.doctor.dashboard.monthlyTotalHint'))),
              const SizedBox(width: 12),
              Expanded(child: _statCard(context, tk.alertMedium, t('common.doctor.dashboard.redFlagMetric'), '${s?.totalRedFlagAlerts ?? 0}', t('common.doctor.dashboard.redFlagMetricHint'))),
            ]),
          const SizedBox(height: 20),
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                icon: const Icon(Icons.group_outlined),
                label: Text(t('dashboard.sidebar.nav.patients')),
                onPressed: () => context.go(prefixLngToPath('/patients', currentLng)),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: OutlinedButton.icon(
                icon: const Icon(Icons.description_outlined),
                label: Text(t('dashboard.sidebar.nav.soapReports')),
                onPressed: () => context.go(prefixLngToPath('/reports', currentLng)),
              ),
            ),
          ]),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            icon: const Icon(Icons.bar_chart),
            label: Text(t('dashboard.sidebar.nav.research')),
            onPressed: () => context.go(prefixLngToPath('/research', currentLng)),
          ),
          if (user?.isAdmin ?? false) ...[
            const SizedBox(height: 20),
            Text(t('dashboard.sidebar.sections.admin').toUpperCase(), style: Theme.of(context).textTheme.labelMedium),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [
              _adminLink(context, Icons.group_outlined, t('dashboard.sidebar.nav.userManagement'), '/admin/users'),
              _adminLink(context, Icons.list_alt, t('dashboard.sidebar.nav.complaintTemplates'), '/admin/complaints'),
              _adminLink(context, Icons.health_and_safety_outlined, t('dashboard.sidebar.nav.systemHealth'), '/admin/health'),
              _adminLink(context, Icons.receipt_long, t('dashboard.sidebar.nav.auditLogs'), '/admin/audit-logs'),
            ]),
          ],
          const SizedBox(height: 20),
          if (s != null) ...[
            DonutCard(
              title: t('common.doctor.dashboard.chiefComplaintDistribution'),
              centerLabel: t('common.doctor.dashboard.sessions'),
              emptyLabel: t('common.doctor.dashboard.noCategoryData'),
              items: [for (final b in s.chiefComplaintDistribution) (label: _complaintLabel(b), count: b.count)],
            ),
            const SizedBox(height: 12),
            DailyTrendCard(
              title: t('common.doctor.dashboard.dailyTrend'),
              totalLabel: t('common.doctor.dashboard.totalSessions'),
              peakLabel: t('common.doctor.dashboard.peakDay'),
              days: [for (final day in s.dailyTrend) (label: day.label, sessions: day.sessions, redFlags: day.redFlags)],
            ),
          ],
        ],
      ),
    );
  }

  Widget _statCard(BuildContext context, Color accent, String title, String value, String hint) {
    return Card(
      child: Container(
        decoration: BoxDecoration(
          border: Border(top: BorderSide(color: accent, width: 3)),
          borderRadius: BorderRadius.circular(8),
        ),
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 8),
          Text(value, style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(hint, style: Theme.of(context).textTheme.bodySmall),
        ]),
      ),
    );
  }

  Widget _adminLink(BuildContext context, IconData icon, String label, String route) => OutlinedButton.icon(
        icon: Icon(icon, size: 16),
        label: Text(label),
        onPressed: () => context.go(prefixLngToPath(route, currentLng)),
      );

  static const _complaintKey = {
    'hematuria': 'complaintHematuria',
    'frequency': 'complaintFrequency',
    'voiding': 'complaintVoiding',
    'pain': 'complaintPain',
    'other': 'complaintOther',
  };

  String _complaintLabel(BucketItem b) =>
      _complaintKey[b.key] != null ? t('common.doctor.dashboard.${_complaintKey[b.key]}') : b.label;
}
