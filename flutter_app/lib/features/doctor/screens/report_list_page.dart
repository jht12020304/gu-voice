import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/reports_api.dart';
import '../../../data/api/sessions_api.dart';
import '../../../data/models/soap_report.dart';
import '../../../shared/widgets/ui_kit.dart';

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
  _Counts? _counts;
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

  /// The four numbers on the summary cards.
  ///
  /// This used to fetch `list(limit: 100)` and count the rows client-side, which was
  /// both the heaviest request on the screen — 100 full SOAP reports, each carrying its
  /// `summary` text and patient-facing JSON, downloaded to produce four integers — and
  /// silently wrong past 100 reports, because `limit` caps at 100 and the cards then
  /// under-counted a clinic's real backlog with no indication anything was truncated.
  ///
  /// `pagination.totalCount` is a server-side COUNT over the same filters, so asking for
  /// one row per status and reading the count is both smaller and correct at any size.
  /// The four run concurrently: one round trip of latency, four rows of payload.
  Future<void> _fetchSummary() async {
    try {
      final counts = await Future.wait([
        _reportsApi.list(limit: 1),
        _reportsApi.list(limit: 1, reviewStatus: 'pending'),
        _reportsApi.list(limit: 1, reviewStatus: 'approved'),
        _reportsApi.list(limit: 1, reviewStatus: 'revision_needed'),
      ]);
      if (!mounted) return;
      setState(() => _counts = (
            total: counts[0].totalCount,
            pending: counts[1].totalCount,
            approved: counts[2].totalCount,
            revisionNeeded: counts[3].totalCount,
          ));
    } catch (_) {/* cards fall back to counting what is loaded — see _summaryCards */}
  }

  /// Per-row patient name / chief complaint / red flag.
  ///
  /// The backend now ships these on the report itself (2026-08-22, `GET /reports`
  /// eager-loads the session), so in the normal case `missing` is empty and this makes
  /// no requests at all — where it used to make one per row, i.e. 20 on a full page,
  /// each one arriving late enough to visibly reflow the list.
  ///
  /// The per-row fetch is kept as the fallback, not deleted, because the two sides do
  /// not deploy together: the TestFlight build talks to production, and until that is
  /// redeployed every report comes back without the new fields. Rows that already have
  /// them are skipped, so a half-migrated backend costs only what it has to.
  Future<void> _loadMeta() async {
    final missing = _reports
        .where((r) => !r.hasSessionContext)
        .map((r) => r.sessionId)
        .toSet()
        .difference(_meta.keys.toSet());
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
      // `_metaFor`, not `_meta` — otherwise searching by patient name silently stops
      // matching for exactly the rows whose name came from the report itself, i.e. all
      // of them once the backend is deployed.
      final m = _metaFor(r);
      return '${m?.patientName ?? ''} ${m?.complaint ?? ''} ${r.sessionId}'.toLowerCase().contains(q);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    if (_lastLng != currentLng) {
      _lastLng = currentLng;
      // Only the per-row meta is localized (chief complaint text). The counts are
      // integers, so re-fetching them on a language switch was four requests buying
      // nothing.
      _meta.clear();
      Future.microtask(() => _fetchReports(reset: true));
    }
    final filtered = _filtered;

    return Scaffold(
      appBar: AppBar(title: Text(t('dashboard.sidebar.nav.soapReports'))),
      body: _loading && _reports.isEmpty
          ? const SkeletonList()
          : ListView(
              controller: _scroll,
              padding: const EdgeInsets.all(16),
              children: [
                _summaryCards(context),
                const SizedBox(height: 12),
                _filterTabs(),
                TextField(
                  decoration: InputDecoration(prefixIcon: const Icon(Icons.search), hintText: t('dashboard.reportList.searchPlaceholder')),
                  onChanged: (v) => setState(() => _search = v),
                ),
                const SizedBox(height: 8),
                if (filtered.isEmpty)
                  EmptyState(
                    icon: Icons.description_outlined,
                    title: t('dashboard.reportList.emptyTitle'),
                    message: t('dashboard.reportList.emptyMessage'),
                  )
                else
                  for (final g in _grouped(filtered)) ...[
                    GroupHeader('${g.key}  ·  ${t('dashboard.reportList.groupCount', args: {'count': g.value.length})}'),
                    for (final r in g.value) _row(context, r),
                  ],
                if (_loading && _reports.isNotEmpty) const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator())),
                if (!_hasMore) Center(child: Padding(padding: const EdgeInsets.all(12), child: Text(t('common.pagination.allLoaded')))),
              ],
            ),
    );
  }

  Widget _summaryCards(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    // Until the counts land (or if that request failed) fall back to counting the page
    // that is already on screen, so the cards show something truthful-for-what-is-loaded
    // rather than four zeroes.
    final c = _counts ??
        (
          total: _reports.length,
          pending: _countByStatus(_reports, 'pending'),
          approved: _countByStatus(_reports, 'approved'),
          revisionNeeded: _countByStatus(_reports, 'revision_needed'),
        );
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
      card(t('dashboard.reportList.summaryTotal'), c.total, tk.statusInProgress),
      const SizedBox(width: 8),
      card(t('dashboard.reportList.tabs.pending'), c.pending, tk.alertMedium),
      const SizedBox(width: 8),
      card(t('dashboard.reportList.tabs.approved'), c.approved, tk.statusCompleted),
      const SizedBox(width: 8),
      card(t('dashboard.reportList.tabs.revisionNeeded'), c.revisionNeeded, tk.alertCritical),
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

  /// The row's session context: straight off the report when the backend supplied it,
  /// otherwise from the per-row fallback fetch. Returns null only while that fallback is
  /// still in flight.
  _Meta? _metaFor(SoapReport r) {
    if (r.hasSessionContext) {
      return _Meta(
        r.patientName ?? r.sessionId,
        r.chiefComplaintText ?? t('dashboard.reportList.complaintEmpty'),
        r.sessionRedFlag ?? false,
        r.sessionStatus,
      );
    }
    return _meta[r.sessionId];
  }

  Widget _row(BuildContext context, SoapReport r) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final m = _metaFor(r);
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
                PillTag(t('dashboard.reportList.redFlagBadge'), color: tk.alertCritical),
                const SizedBox(width: 6),
              ],
              PillTag(badgeLabel, color: badgeColor),
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

typedef _Counts = ({int total, int pending, int approved, int revisionNeeded});
