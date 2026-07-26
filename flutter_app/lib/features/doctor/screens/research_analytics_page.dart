import 'dart:async';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/i18n/loc.dart';
import '../../../data/api/research_api.dart';
import '../../../data/models/research_analytics.dart';
import '../research/charts.dart' show researchPalette;
import '../research/research_figures.dart';
import '../services/dashboard_ws.dart';

const _refetchDebounceMs = 1500;
const _tnum = TextStyle(fontFeatures: [FontFeature.tabularFigures()]);

// Port of ResearchAnalyticsPage.tsx (v1). Journal-grade figures via CustomPainter
// primitives (boxplot / proportion+Wilson / forest) + fl_chart (weekly trend, histogram).
// Live refetch debounced 1.5s on dashboard WS report_generated / session_status_changed.
class ResearchAnalyticsPage extends ConsumerStatefulWidget {
  const ResearchAnalyticsPage({super.key});

  @override
  ConsumerState<ResearchAnalyticsPage> createState() => _ResearchAnalyticsPageState();
}

class _ResearchAnalyticsPageState extends ConsumerState<ResearchAnalyticsPage> {
  ResearchAnalytics? _data;
  bool _loading = true;
  bool _error = false;
  Timer? _debounce;
  static const _wsEvents = ['report_generated', 'session_status_changed'];

  @override
  void initState() {
    super.initState();
    final ws = ref.read(dashboardWsProvider)..ensureConnected();
    for (final e in _wsEvents) {
      ws.on(e, _onWs);
    }
    Future.microtask(_fetch);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    final ws = ref.read(dashboardWsProvider);
    for (final e in _wsEvents) {
      ws.off(e, _onWs);
    }
    super.dispose();
  }

  void _onWs(dynamic p, Map m) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: _refetchDebounceMs), _fetch);
  }

  Future<void> _fetch() async {
    try {
      final d = await ResearchApi().getAnalytics();
      if (mounted) setState(() { _data = d; _loading = false; _error = false; });
    } catch (_) {
      if (mounted) setState(() { _loading = false; _error = _data == null; });
    }
  }

  String _pct(double? v) => v == null ? '—' : '${(v * 100).toStringAsFixed(1)}%';
  String _iqr(NumericSummary s, {double Function(double)? tf}) {
    if (s.median == null) return '—';
    final t = tf ?? (v) => v;
    String f(double? v) => v == null ? '—' : (t(v).abs() >= 100 ? t(v).toStringAsFixed(0) : t(v).toStringAsFixed(1));
    return '${f(s.median)} (${f(s.p25)}–${f(s.p75)})';
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return Scaffold(appBar: AppBar(title: Text(t('research.page.title'))), body: Center(child: Text(t('research.page.loading'))));
    if (_error || _data == null) return Scaffold(appBar: AppBar(title: Text(t('research.page.title'))), body: Center(child: Text(t('research.page.error'))));
    final d = _data!;

    return Scaffold(
      appBar: AppBar(title: Text(t('research.page.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(t('research.page.subtitle'), style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          _kpis(context, d),
          const SizedBox(height: 12),
          _table1(context, d),
          _figure(context, t('research.fig.one'), t('research.cohort.title'), _weeklyTrend(context, d)),
          _figure(context, t('research.fig.two'), t('research.efficiency.title'), _boxplots(context, d)),
          _figure(context, t('research.fig.three'), t('research.hpi.title'), _hpiRows(context, d)),
          _figure(context, t('research.fig.four'), t('research.safety.title'), _safety(context, d)),
          _figure(context, t('research.fig.five'), t('research.safety.urgencyTitle'), _urgencyLayer(context, d)),
          _figure(context, t('research.fig.six'), t('research.stt.title'), _stt(context, d)),
          _figure(context, t('research.fig.seven'), t('research.documentation.title'), _documentation(context, d)),
          _figure(context, t('research.fig.eight'), t('research.forest.title'), _forest(context, d)),
        ],
      ),
    );
  }

  Widget _figure(BuildContext context, String label, String title, Widget child) => Card(
        margin: const EdgeInsets.symmetric(vertical: 8),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label.toUpperCase(), style: Theme.of(context).textTheme.labelSmall),
            Text(title, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            child,
          ]),
        ),
      );

  Widget _kpis(BuildContext context, ResearchAnalytics d) {
    final tiles = <(String, String)>[
      (t('research.kpi.sessions'), '${d.totalSessions}'),
      (t('research.kpi.completionRate'), _pct(d.completion.value)),
      (t('research.kpi.redFlagRate'), _pct(d.alertSession.value)),
      (t('research.kpi.medianDuration'), _iqr(d.durationSeconds, tf: (v) => v / 60)),
      (t('research.kpi.hpiCompleteness'), _pct(d.meanHpiCompleteness)),
      (t('research.kpi.agreementRate'), _pct(d.physicianAgreement.value)),
    ];
    return Wrap(spacing: 8, runSpacing: 8, children: [
      for (final tile in tiles)
        SizedBox(
          width: 160,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tile.$1, style: Theme.of(context).textTheme.bodySmall),
                Text(tile.$2, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700).merge(_tnum)),
              ]),
            ),
          ),
        ),
    ]);
  }

  Widget _table1(BuildContext context, ResearchAnalytics d) {
    Color c(int i) => researchPalette[i % researchPalette.length];
    return _figure(context, 'Table 1', t('research.demographics.title'), Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('${t('research.demographics.age')}: ${_iqr(d.ageYears)}', style: _tnum),
      if (d.ageYears.mean != null)
        Text('${t('research.demographics.ageMeanSd')}: '
            '${d.ageYears.mean!.toStringAsFixed(1)} ± ${(d.ageYears.sd ?? 0).toStringAsFixed(1)}', style: _tnum),
      const SizedBox(height: 8),
      Text(t('research.demographics.ageBands')),
      StackedShareBar(items: [for (var i = 0; i < d.ageBandDistribution.length; i++) (label: d.ageBandDistribution[i].key, count: d.ageBandDistribution[i].count, color: c(i))]),
      const SizedBox(height: 8),
      StackedShareBar(items: [for (var i = 0; i < d.genderDistribution.length; i++) (label: _genderLabel(d.genderDistribution[i].key), count: d.genderDistribution[i].count, color: c(i))]),
      const SizedBox(height: 8),
      Text(t('research.demographics.caseMix')),
      Wrap(spacing: 6, runSpacing: 6, children: [for (final b in d.chiefComplaintDistribution.take(8)) Chip(label: Text('${b.key} · ${b.count}'), visualDensity: VisualDensity.compact)]),
    ]));
  }

  String _genderLabel(String k) => switch (k) {
        'male' => t('research.demographics.gender.male'),
        'female' => t('research.demographics.gender.female'),
        _ => t('research.demographics.gender.other'),
      };

  Widget _weeklyTrend(BuildContext context, ResearchAnalytics d) {
    if (d.weeklyTrend.isEmpty) return Text(t('research.page.empty'));
    final items = d.weeklyTrend;
    final maxY = items.fold<int>(1, (m, w) => [m, w.sessions, w.completed].reduce((a, b) => a > b ? a : b));
    return SizedBox(
      height: 200,
      child: LineChart(LineChartData(
        maxY: maxY.toDouble(),
        minY: 0,
        gridData: const FlGridData(show: true, drawVerticalLine: false),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 28)),
          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 22,
              getTitlesWidget: (v, meta) {
                final i = v.toInt();
                if (i < 0 || i >= items.length) return const SizedBox.shrink();
                final ws = items[i].weekStart;
                return Text(ws.length >= 5 ? ws.substring(5) : ws, style: const TextStyle(fontSize: 9));
              },
            ),
          ),
        ),
        lineBarsData: [
          LineChartBarData(spots: [for (var i = 0; i < items.length; i++) FlSpot(i.toDouble(), items[i].sessions.toDouble())], color: const Color(0xFF2563EB), barWidth: 2, isCurved: false),
          LineChartBarData(spots: [for (var i = 0; i < items.length; i++) FlSpot(i.toDouble(), items[i].completed.toDouble())], color: const Color(0xFF16A34A), barWidth: 2, isCurved: false),
        ],
      )),
    );
  }

  Widget _boxRow(BuildContext context, String label, NumericSummary s, {double Function(double)? tf, String unit = ''}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          SizedBox(width: 110, child: Text('$label\nn=${s.n}', style: Theme.of(context).textTheme.bodySmall)),
          Expanded(child: BoxPlotRowChart(summary: s, transform: tf, unit: unit)),
        ]),
      );

  Widget _boxplots(BuildContext context, ResearchAnalytics d) {
    if (d.durationSeconds.n == 0) return Text(t('research.page.empty'));
    return Column(children: [
      _boxRow(context, t('research.efficiency.duration'), d.durationSeconds, tf: (v) => v / 60, unit: 'min'),
      _boxRow(context, t('research.efficiency.turns'), d.patientTurns),
      _boxRow(context, t('research.efficiency.chars'), d.patientTurnChars),
    ]);
  }

  Widget _propRow(BuildContext context, String label, Proportion p, {Color color = const Color(0xFF2563EB)}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          SizedBox(width: 110, child: Text(label, style: Theme.of(context).textTheme.bodySmall, overflow: TextOverflow.ellipsis)),
          Expanded(child: ProportionRowChart(prop: p, color: color)),
        ]),
      );

  Widget _hpiRows(BuildContext context, ResearchAnalytics d) {
    if (d.reportsAnalyzed == 0) return Text(t('research.page.empty'));
    return Column(children: [
      for (final f in d.hpiFieldFillRates)
        _propRow(context, t('research.hpi.fields.${f.field}'), Proportion(numerator: f.filled, denominator: f.total, value: f.rate)),
    ]);
  }

  // Semantic (ordinal) colors + translated labels for the categorical distributions —
  // replaces the raw enum keys + index palette regression the audit flagged.
  Color _severityColor(String k) => switch (k) {
        'critical' => const Color(0xFFDC2626),
        'high' => const Color(0xFFEA580C),
        _ => const Color(0xFFD97706),
      };
  Color _urgencyColor(String k) => switch (k) {
        'er_now' => const Color(0xFFDC2626),
        '24h' => const Color(0xFFEA580C),
        'this_week' => const Color(0xFFD97706),
        _ => const Color(0xFF64748B),
      };
  String _labelOr(String path, String rawKey) {
    final v = t(path);
    return v == path ? rawKey : v;
  }

  Widget _safety(BuildContext context, ResearchAnalytics d) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _propRow(context, t('research.safety.alertRate'), d.alertSession),
      _propRow(context, t('research.safety.ackRate'), d.acknowledged),
      const SizedBox(height: 8),
      // Median (IQR) latency tiles (Figure 4).
      Text('${t('research.safety.timeToFirstAlert')}: ${_iqr(d.timeToFirstAlertSeconds, tf: (v) => v / 60)} · '
          '${t('research.safety.ackLatency')}: ${_iqr(d.ackLatencySeconds, tf: (v) => v / 60)}', style: _tnum),
      const SizedBox(height: 8),
      Text(t('research.safety.severityTitle')),
      StackedShareBar(items: [
        for (final b in d.severityDistribution)
          (label: _labelOr('research.safety.severity.${b.key}', b.key), count: b.count, color: _severityColor(b.key)),
      ]),
    ]);
  }

  Widget _urgencyLayer(BuildContext context, ResearchAnalytics d) {
    Color c(int i) => researchPalette[i % researchPalette.length];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(t('research.safety.urgencyTitle')),
      StackedShareBar(items: [
        for (final b in d.urgencyDistribution)
          (label: _labelOr('research.safety.urgency.${b.key}', b.key), count: b.count, color: _urgencyColor(b.key)),
      ]),
      const SizedBox(height: 8),
      Text(t('research.safety.layerTitle')),
      StackedShareBar(items: [
        for (var i = 0; i < d.layerDistribution.length; i++)
          (label: _labelOr('research.safety.layer.${d.layerDistribution[i].key}', d.layerDistribution[i].key),
              count: d.layerDistribution[i].count, color: c(i)),
      ]),
    ]);
  }

  Widget _stt(BuildContext context, ResearchAnalytics d) {
    if (d.turnsWithConfidence == 0) return Text(t('research.page.empty'));
    final buckets = d.sttHistogram;
    final maxC = buckets.fold<int>(1, (m, b) => b.count > m ? b.count : m);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('${t('research.stt.medianConfidence')}: ${_iqr(d.confidenceSummary)}  ·  ${t('research.stt.lowConfidence')}: ${_pct(d.lowConfidence.value)}  ·  ${t('research.stt.voiceShare')}: ${_pct(d.voiceTurnShare)}', style: _tnum),
      const SizedBox(height: 8),
      SizedBox(
        height: 160,
        child: BarChart(BarChartData(
          maxY: maxC.toDouble(),
          gridData: const FlGridData(show: false),
          borderData: FlBorderData(show: false),
          titlesData: const FlTitlesData(
            leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
            topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
            rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
            bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
          ),
          barGroups: [
            for (var i = 0; i < buckets.length; i++)
              BarChartGroupData(x: i, barRods: [BarChartRodData(toY: buckets[i].count.toDouble(), color: const Color(0xFF2563EB), width: 10, borderRadius: BorderRadius.circular(3))]),
          ],
        )),
      ),
    ]);
  }

  Widget _documentation(BuildContext context, ResearchAnalytics d) {
    Color c(int i) => researchPalette[i % researchPalette.length];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(t('research.documentation.outcomesTitle')),
      StackedShareBar(items: [for (var i = 0; i < d.reviewOutcomes.length; i++) (label: _outcomeLabel(d.reviewOutcomes[i].key), count: d.reviewOutcomes[i].count, color: i == 0 ? const Color(0xFF16A34A) : c(i))]),
      const SizedBox(height: 8),
      _propRow(context, t('research.documentation.agreement'), d.physicianAgreement),
      _propRow(context, t('research.documentation.icdVerified'), d.icd10Verified),
      Text('${t('research.documentation.aiConfidence')}: ${_iqr(d.aiConfidenceSummary)}', style: _tnum),
    ]);
  }

  String _outcomeLabel(String k) => switch (k) {
        'approved' => t('research.documentation.outcomes.approved'),
        'revision_needed' => t('research.documentation.outcomes.revision_needed'),
        _ => t('research.documentation.outcomes.pending'),
      };

  Widget _forest(BuildContext context, ResearchAnalytics d) {
    if (d.byLanguage.isEmpty) return Text(t('research.page.empty'));
    return ForestPlotChart(
      rows: [for (final l in d.byLanguage) (label: '${l.language} (n=${l.sessions})', prop: l.redFlagRate)],
      overall: d.alertSession.value,
      overallLabel: t('research.forest.overall'),
      xLabel: t('research.forest.xLabel'),
    );
  }
}
