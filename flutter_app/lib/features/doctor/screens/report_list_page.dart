import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/reports_api.dart';
import '../../../data/api/sessions_api.dart';
import '../../../data/models/soap_report.dart';

class _Meta {
  final String patientName;
  final String complaint;
  final bool redFlag;
  final String? sessionStatus;
  const _Meta(this.patientName, this.complaint, this.redFlag, this.sessionStatus);
}

// Port of ReportListPage.tsx: paginated review inbox + separate limit=100 summary counts +
// session-meta batch enrichment + client-side search. Nav param is sessionId.
class ReportListPage extends StatefulWidget {
  const ReportListPage({super.key});

  @override
  State<ReportListPage> createState() => _ReportListPageState();
}

class _ReportListPageState extends State<ReportListPage> {
  final _reportsApi = ReportsApi();
  final _sessionsApi = SessionsApi();
  final _scroll = ScrollController();

  List<SoapReport> _reports = [];
  List<SoapReport> _summary = [];
  final Map<String, _Meta> _meta = {};
  String? _cursor;
  bool _hasMore = true;
  bool _loading = true;
  String _reviewFilter = '';
  String _search = '';
  String _lastLng = currentLng;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 300) _fetchMore();
    });
    Future.microtask(() {
      _fetchReports(reset: true);
      _fetchSummary();
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  String? get _filterParam => _reviewFilter.isEmpty ? null : _reviewFilter;

  Future<void> _fetchReports({required bool reset}) async {
    setState(() => _loading = true);
    try {
      final page = await _reportsApi.list(cursor: reset ? null : _cursor, reviewStatus: _filterParam);
      setState(() {
        _reports = reset ? page.data : [..._reports, ...page.data];
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
        _loading = false;
      });
      _loadMeta();
    } catch (_) {
      if (mounted) setState(() => _loading = false); // faithful: silent
    }
  }

  Future<void> _fetchMore() async {
    if (!_hasMore || _loading || _cursor == null) return;
    await _fetchReports(reset: false);
  }

  Future<void> _fetchSummary() async {
    try {
      final page = await _reportsApi.list(limit: 100);
      if (mounted) setState(() => _summary = page.data);
    } catch (_) {/* fall back to displayed reports */}
  }

  Future<void> _loadMeta() async {
    final missing = _reports.map((r) => r.sessionId).toSet().difference(_meta.keys.toSet());
    if (missing.isEmpty) return;
    await Future.wait(missing.map((id) async {
      try {
        final s = await _sessionsApi.getSession(id);
        _meta[id] = _Meta(s.patientName ?? s.id, s.chiefComplaintText ?? t('dashboard.reportList.complaintEmpty'), s.redFlag, s.status);
      } catch (_) {
        _meta[id] = _Meta(id, t('dashboard.reportList.complaintFetchFailed'), false, null);
      }
    }));
    if (mounted) setState(() {});
  }

  int _countByStatus(List<SoapReport> list, String status) => list.where((r) => r.reviewStatus == status).length;

  // Timestamp precedence generatedAt -> updatedAt -> createdAt (read from raw), grouped by
  // YYYY-MM-DD, newest day first (mirrors ReportListPage.tsx).
  String _ts(SoapReport r) =>
      (r.raw['generatedAt'] ?? r.raw['updatedAt'] ?? r.raw['createdAt'] ?? '') as String;

  List<MapEntry<String, List<SoapReport>>> _grouped(List<SoapReport> reports) {
    final sorted = [...reports]..sort((a, b) => _ts(b).compareTo(_ts(a)));
    final groups = <String, List<SoapReport>>{};
    for (final r in sorted) {
      final ts = _ts(r);
      groups.putIfAbsent(ts.length >= 10 ? ts.substring(0, 10) : 'unknown', () => []).add(r);
    }
    return groups.entries.toList();
  }

  List<SoapReport> get _filtered {
    final q = _search.trim().toLowerCase();
    if (q.isEmpty) return _reports;
    return _reports.where((r) {
      final m = _meta[r.sessionId];
      return '${m?.patientName ?? ''} ${m?.complaint ?? ''} ${r.sessionId}'.toLowerCase().contains(q);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    if (_lastLng != currentLng) {
      _lastLng = currentLng;
      _meta.clear();
      Future.microtask(() { _fetchReports(reset: true); _fetchSummary(); });
    }
    final overview = _summary.isNotEmpty ? _summary : _reports;
    final filtered = _filtered;

    return Scaffold(
      appBar: AppBar(title: Text(t('dashboard.sidebar.nav.soapReports'))),
      body: _loading && _reports.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              controller: _scroll,
              padding: const EdgeInsets.all(16),
              children: [
                _summaryCards(context, overview),
                const SizedBox(height: 12),
                _filterTabs(),
                TextField(
                  decoration: InputDecoration(prefixIcon: const Icon(Icons.search), hintText: t('dashboard.reportList.searchPlaceholder')),
                  onChanged: (v) => setState(() => _search = v),
                ),
                const SizedBox(height: 8),
                if (filtered.isEmpty)
                  Padding(
                    padding: const EdgeInsets.all(24),
                    child: Center(child: Text(t('dashboard.reportList.emptyTitle'))),
                  )
                else
                  for (final g in _grouped(filtered)) ...[
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: Text('${g.key}  ·  ${t('dashboard.reportList.groupCount', args: {'count': g.value.length})}',
                          style: Theme.of(context).textTheme.labelMedium),
                    ),
                    for (final r in g.value) _row(context, r),
                  ],
                if (_loading && _reports.isNotEmpty) const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator())),
                if (!_hasMore) Center(child: Padding(padding: const EdgeInsets.all(12), child: Text(t('common.pagination.allLoaded')))),
              ],
            ),
    );
  }

  Widget _summaryCards(BuildContext context, List<SoapReport> overview) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    Widget card(String label, int n, Color color) => Expanded(
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(children: [
                Text('$n', style: Theme.of(context).textTheme.titleLarge?.copyWith(color: color, fontWeight: FontWeight.w700)),
                Text(label, style: Theme.of(context).textTheme.bodySmall, textAlign: TextAlign.center),
              ]),
            ),
          ),
        );
    return Row(children: [
      card(t('dashboard.reportList.summaryTotal'), overview.length, tk.statusInProgress),
      const SizedBox(width: 8),
      card(t('dashboard.reportList.tabs.pending'), _countByStatus(overview, 'pending'), tk.alertMedium),
      const SizedBox(width: 8),
      card(t('dashboard.reportList.tabs.approved'), _countByStatus(overview, 'approved'), tk.statusCompleted),
      const SizedBox(width: 8),
      card(t('dashboard.reportList.tabs.revisionNeeded'), _countByStatus(overview, 'revision_needed'), tk.alertCritical),
    ]);
  }

  Widget _filterTabs() {
    const filters = {
      '': 'dashboard.reportList.tabs.all',
      'pending': 'dashboard.reportList.tabs.pending',
      'approved': 'dashboard.reportList.tabs.approved',
      'revision_needed': 'dashboard.reportList.tabs.revisionNeeded',
    };
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(children: [
        for (final e in filters.entries)
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              selected: _reviewFilter == e.key,
              label: Text(t(e.value)),
              onSelected: (_) {
                setState(() => _reviewFilter = e.key);
                _fetchReports(reset: true);
              },
            ),
          ),
      ]),
    );
  }

  Widget _row(BuildContext context, SoapReport r) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final m = _meta[r.sessionId];
    final (badgeLabel, badgeColor) = switch (r.reviewStatus) {
      'approved' => (t('dashboard.reportList.tabs.approved'), tk.statusCompleted),
      'revision_needed' => (t('dashboard.reportList.tabs.revisionNeeded'), tk.alertCritical),
      _ => (t('dashboard.reportList.tabs.pending'), tk.alertMedium),
    };
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: InkWell(
        onTap: () => context.go(prefixLngToPath('/reports/${r.sessionId}', currentLng)),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Text(m?.patientName ?? r.sessionId, style: const TextStyle(fontWeight: FontWeight.w600))),
              if (m?.redFlag ?? false) ...[
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(color: tk.alertCriticalBg, borderRadius: BorderRadius.circular(9999)),
                  child: Text(t('dashboard.reportList.redFlagBadge'),
                      style: TextStyle(color: tk.alertCritical, fontSize: 11, fontWeight: FontWeight.w600)),
                ),
                const SizedBox(width: 6),
              ],
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(color: badgeColor.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(9999)),
                child: Text(badgeLabel, style: TextStyle(color: badgeColor, fontSize: 12, fontWeight: FontWeight.w600)),
              ),
            ]),
            if (m != null) Text(t('dashboard.reportList.chiefComplaintLabel', args: {'value': m.complaint}), style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 4),
            Text(r.summary ?? t('dashboard.reportList.summaryEmpty'), maxLines: 3, overflow: TextOverflow.ellipsis),
            if (r.icd10Codes.isNotEmpty) ...[
              const SizedBox(height: 6),
              Wrap(spacing: 6, children: [for (final c in r.icd10Codes.take(3)) Chip(label: Text(c), visualDensity: VisualDensity.compact)]),
            ],
            if (r.aiConfidenceScore != null)
              Text(t('dashboard.reportList.aiConfidence', args: {'percent': (r.aiConfidenceScore! * 100).round()}), style: Theme.of(context).textTheme.bodySmall),
            if (r.reviewStatus == 'revision_needed' && r.reviewNotes != null) ...[
              const SizedBox(height: 6),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(color: tk.alertCriticalBg, borderRadius: BorderRadius.circular(6)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(t('dashboard.reportList.revisionReason'), style: TextStyle(color: tk.alertCritical, fontWeight: FontWeight.w600, fontSize: 12)),
                  Text(r.reviewNotes!, style: TextStyle(color: tk.alertCritical)),
                ]),
              ),
            ],
          ]),
        ),
      ),
    );
  }
}
