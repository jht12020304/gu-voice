import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../data/api/patients_api.dart';
import '../../../data/models/patient.dart';
import '../../../shared/format.dart';
import '../../../shared/widgets/ui_kit.dart';

// Port of PatientListPage.tsx: month-scoped, cursor-paginated, date-grouped patient list
// with debounced search + infinite scroll. ponytail: responsive table/card split reduced
// to cards (mobile-first); month range math preserved (local midnight -> UTC ISO).
class PatientListPage extends StatefulWidget {
  const PatientListPage({super.key});

  @override
  State<PatientListPage> createState() => _PatientListPageState();
}

class _PatientListPageState extends State<PatientListPage> {
  final _api = PatientsApi();
  final _scroll = ScrollController();
  Timer? _debounce;

  List<Patient> _patients = [];
  String? _cursor;
  bool _hasMore = true;
  bool _loading = true;
  int _totalCount = 0;
  String _search = '';
  late String _month;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _month = '${now.year.toString().padLeft(4, '0')}-${now.month.toString().padLeft(2, '0')}';
    _scroll.addListener(() {
      if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 300) _fetchMore();
    });
    Future.microtask(() => _fetch(reset: true));
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  (String, String) _range(String month) {
    final p = month.split('-');
    final y = int.parse(p[0]), m = int.parse(p[1]);
    final first = DateTime(y, m, 1);
    final last = DateTime(y, m + 1, 0, 23, 59, 59, 999);
    return (first.toUtc().toIso8601String(), last.toUtc().toIso8601String());
  }

  Future<void> _fetch({required bool reset}) async {
    setState(() => _loading = true);
    final (from, to) = _range(_month);
    try {
      final page = await _api.list(
        cursor: reset ? null : _cursor,
        search: _search.trim().isEmpty ? null : _search.trim(),
        createdFrom: from,
        createdTo: to,
      );
      setState(() {
        _patients = reset ? page.data : [..._patients, ...page.data];
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
        _totalCount = page.totalCount;
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _fetchMore() async {
    if (!_hasMore || _loading || _cursor == null) return;
    await _fetch(reset: false);
  }

  void _onSearch(String q) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      setState(() => _search = q);
      _fetch(reset: true);
    });
  }

  void _shiftMonth(int delta) {
    final p = _month.split('-');
    final d = DateTime(int.parse(p[0]), int.parse(p[1]) + delta, 1);
    setState(() => _month = '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}');
    _fetch(reset: true);
  }

  /// 月份標籤走與儀表板同一支 monthFormat key（"2026-08" → 「2026 年 8 月」），
  /// 兩頁的 MonthStatsCard 標題格式才一致；統計格 label 也吃同一份格式化結果。
  String get _monthLabel {
    final parts = _month.split('-');
    final year = int.tryParse(parts[0]);
    final month = parts.length == 2 ? int.tryParse(parts[1]) : null;
    if (year == null || month == null) return _month;
    return t('common.doctor.dashboard.monthFormat', args: {'year': year, 'month': month});
  }

  List<MapEntry<String, List<Patient>>> get _groups {
    final groups = <String, List<Patient>>{};
    for (final p in _patients) {
      final key = (p.createdAt != null && p.createdAt!.length >= 10) ? p.createdAt!.substring(0, 10) : 'unknown';
      groups.putIfAbsent(key, () => []).add(p);
    }
    final entries = groups.entries.toList()..sort((a, b) => b.key.compareTo(a.key));
    return entries;
  }

  @override
  Widget build(BuildContext context) {
    final groups = _groups;
    return Scaffold(
      appBar: AppBar(title: Text(t('common.patientList.title'))),
      body: Column(
        children: [
          // ── 月份＋統計：步進器是卡片標題列，月份只在這裡出現 ──
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: MonthStatsCard(
              monthLabel: _monthLabel,
              prevTooltip: t('common.patientList.previousMonth'),
              nextTooltip: t('common.patientList.nextMonth'),
              onPrev: _loading ? null : () => _shiftMonth(-1),
              onNext: _loading ? null : () => _shiftMonth(1),
              cells: [
                StatCell(
                  label: t('common.patientList.newPatientsInMonth', args: {'month': _monthLabel}),
                  value: '$_totalCount',
                  loading: _loading,
                ),
                StatCell(
                  label: t('common.patientList.dateGroups'),
                  value: '${groups.length}',
                  loading: _loading,
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: TextField(
              decoration: InputDecoration(prefixIcon: const Icon(Icons.search), hintText: t('common.patientList.searchPlaceholder')),
              onChanged: _onSearch,
            ),
          ),
          Expanded(child: _body(context, groups)),
        ],
      ),
    );
  }

  Widget _body(BuildContext context, List<MapEntry<String, List<Patient>>> groups) {
    if (_loading && _patients.isEmpty) return const SkeletonList();
    if (_patients.isEmpty) {
      return EmptyState(
        icon: Icons.person_search_outlined,
        title: t('common.patientList.emptyTitle', args: {'month': _monthLabel}),
        message: t(_search.isEmpty ? 'common.patientList.emptyMonthMessage' : 'common.patientList.emptySearchMessage'),
      );
    }
    return ListView(
      controller: _scroll,
      padding: const EdgeInsets.all(16),
      children: [
        for (final g in groups) ...[
          GroupHeader('${g.key}  ·  ${t('common.patientList.patientCount', args: {'count': g.value.length})}'),
          for (final p in g.value) _row(context, p),
        ],
        if (_loading && _patients.isNotEmpty) const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator())),
      ],
    );
  }

  Widget _row(BuildContext context, Patient p) {
    final gender = p.gender != null ? t('common.gender.${p.gender}') : '';
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        onTap: () => context.go(prefixLngToPath('/patients/${p.id}', currentLng)),
        leading: CircleAvatar(child: Text(p.name.isNotEmpty ? p.name.characters.first : '?')),
        title: Text(p.name),
        subtitle: Text([
          if (p.medicalRecordNumber != null) p.medicalRecordNumber!,
          if (gender.isNotEmpty) gender,
          p.phone ?? t('common.patientList.noPhone'),
        ].join(' · ')),
        trailing: Text(formatDateTime(p.createdAt), style: Theme.of(context).textTheme.bodySmall),
      ),
    );
  }
}
