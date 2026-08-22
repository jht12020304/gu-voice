import 'dart:async';

import 'package:fl_chart/fl_chart.dart';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show RenderRepaintBoundary;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/i18n/loc.dart';
import '../../../shared/png_share.dart';
import '../../../shared/widgets/ui_kit.dart';
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

  // 存欄位而不是在 dispose() 裡 ref.read：Riverpod 禁止 unmount 中的 widget 碰 ref，
  // 會丟「Using "ref" when a widget is about to or has been unmounted is unsafe」。
  // 症狀是**離開這一頁**（切到任何其他分頁）時炸一次——2026-08-22 的手機版面走查
  // （mobile_layout_walkthrough_test）抓到的；在 web 上它一直存在，只是沒人看 console。
  late final DashboardWs _ws;

  @override
  void initState() {
    super.initState();
    _ws = ref.read(dashboardWsProvider)..ensureConnected();
    for (final e in _wsEvents) {
      _ws.on(e, _onWs);
    }
    Future.microtask(_fetch);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    for (final e in _wsEvents) {
      _ws.off(e, _onWs);
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
    if (_loading) {
      return Scaffold(
        appBar: AppBar(title: Text(t('research.page.title'))),
        body: const SkeletonList(),
      );
    }
    if (_error || _data == null) {
      return Scaffold(
        appBar: AppBar(title: Text(t('research.page.title'))),
        body: ErrorState(
          message: t('research.page.error'),
          retryLabel: t('common.retry'),
          onRetry: () => _fetch(),
        ),
      );
    }
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
          _figure(context, t('research.fig.one'), id: 'fig1', t('research.cohort.title'), _weeklyTrend(context, d),
              caption: t('research.cohort.subtitle'),
              // The model exposes cohort completion as a Proportion, not the individual
              // aborted/cancelled counts the web footnote lists, so report what we have:
              // total + completed. Adding the other two means widening the API payload.
              footnote: t('research.cohort.footnote', args: {
                'total': '${d.totalSessions}',
                'completed': '${d.completion.numerator}',
                'aborted': '—',
                'cancelled': '—',
              })),
          _figure(context, t('research.fig.two'), id: 'fig2', t('research.efficiency.title'), _boxplots(context, d),
              caption: t('research.efficiency.subtitle'),
              footnote: t('research.efficiency.footnote')),
          _figure(context, t('research.fig.three'), id: 'fig3', t('research.hpi.title'), _hpiRows(context, d),
              caption: t('research.hpi.subtitle'),
              footnote: t('research.hpi.footnote', args: {'count': '${d.reportsAnalyzed}'})),
          _figure(context, t('research.fig.four'), id: 'fig4', t('research.safety.title'), _safety(context, d),
              caption: t('research.safety.subtitle'),
              footnote: t('research.safety.footnote')),
          _figure(context, t('research.fig.five'), id: 'fig5', t('research.safety.urgencyTitle'), _urgencyLayer(context, d)),
          _figure(context, t('research.fig.six'), id: 'fig6', t('research.stt.title'), _stt(context, d),
              caption: t('research.stt.subtitle'),
              footnote: t('research.stt.footnote', args: {'count': '${d.turnsWithConfidence}'})),
          _figure(context, t('research.fig.seven'), id: 'fig7', t('research.documentation.title'), _documentation(context, d),
              caption: t('research.documentation.subtitle'),
              footnote: t('research.documentation.footnote', args: {'count': '${d.reportsAnalyzed}'})),
          _figure(context, t('research.fig.eight'), id: 'fig8', t('research.forest.title'), _forest(context, d),
              caption: t('research.forest.subtitle'),
              footnote: t('research.forest.footnote')),
          _byLanguageTable(context, d),
          _methodsCard(context),
        ],
      ),
    );
  }

  /// A journal-style figure: label, title, **caption**, chart, **footnote**, and a PNG
  /// export button.
  ///
  /// The caption/footnote strings (`<section>.subtitle` / `.footnote`) and the whole
  /// `table.*` and `methods.*` blocks were already in all five locale files — the page
  /// simply never rendered them, so what shipped was "the charts" rather than something
  /// submittable (TODO §G medium). Footnotes carry the denominators, which is exactly what
  /// SAMPL asks for and what a reader needs to judge a proportion.
  ///
  /// Export is PNG via `RepaintBoundary`, not SVG: the React page serialises inline SVG,
  /// which has no equivalent here. PNG at 3x is adequate for review; true vector output
  /// would mean re-drawing every chart into an SVG writer.
  /// Stable export keys, one per figure, created once and reused.
  ///
  /// `_figure` used to call `GlobalKey()` inside itself. A GlobalKey *identifies* an
  /// element, so a fresh one every build told Flutter this was a different widget: all
  /// nine figures were torn down and re-inflated on each rebuild, and because fl_chart
  /// animates on mount, they all replayed their entry animation. This page rebuilds on
  /// every dashboard WebSocket event, so in a clinic with patients coming and going the
  /// charts re-animated every second or so while the doctor was trying to read them.
  ///
  /// Keyed by a fixed id rather than the figure's label: labels come from `t()`, so
  /// keying on them would mint new keys on a language switch and bring the problem back
  /// in the one place it is most visible.
  final Map<String, GlobalKey> _figureKeys = {};

  Widget _figure(
    BuildContext context,
    String label,
    String title,
    Widget child, {
    required String id,
    String? caption,
    String? footnote,
  }) {
    final key = _figureKeys.putIfAbsent(id, GlobalKey.new);
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(label.toUpperCase(), style: Theme.of(context).textTheme.labelSmall),
                  Text(title,
                      style: Theme.of(context)
                          .textTheme
                          .titleSmall
                          ?.copyWith(fontWeight: FontWeight.w700)),
                  if (caption != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(caption, style: Theme.of(context).textTheme.bodySmall),
                    ),
                ]),
              ),
              IconButton(
                tooltip: t('research.page.exportPng'),
                icon: const Icon(Icons.download),
                onPressed: () => _exportFigure(key, label),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // Only the chart is captured — the export should not include the toolbar.
          RepaintBoundary(key: key, child: child),
          if (footnote != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(footnote, style: Theme.of(context).textTheme.bodySmall),
            ),
        ]),
      ),
    );
  }

  Future<void> _exportFigure(GlobalKey key, String label) async {
    try {
      final boundary = key.currentContext?.findRenderObject() as RenderRepaintBoundary?;
      if (boundary == null) return;
      final image = await boundary.toImage(pixelRatio: 3);
      final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
      if (bytes == null) return;
      final safe = label.replaceAll(RegExp(r'[^A-Za-z0-9]+'), '_');
      await sharePngBytes(bytes.buffer.asUint8List(), 'research_$safe.png');
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(t('research.page.exportFailed'))));
      }
    }
  }

  /// Full data table behind the forest plot — the numbers a reviewer needs to check the
  /// figure. `table.*` was already translated in all five locales, unused.
  Widget _byLanguageTable(BuildContext context, ResearchAnalytics d) {
    if (d.byLanguage.isEmpty) return const SizedBox.shrink();
    String pct(Proportion p) => p.value == null
        ? '—'
        : '${(p.value! * 100).toStringAsFixed(1)}%'
            '${p.ciLow == null ? '' : ' (${(p.ciLow! * 100).toStringAsFixed(1)}–${(p.ciHigh! * 100).toStringAsFixed(1)})'}';
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t('research.table.title'),
              style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
          Text(t('research.table.subtitle'), style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 8),
          // Wide table: scroll horizontally rather than squeezing columns unreadably.
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columns: [
                DataColumn(label: Text(t('research.table.language'))),
                DataColumn(label: Text(t('research.table.sessions'))),
                DataColumn(label: Text(t('research.table.completed'))),
                DataColumn(label: Text(t('research.table.medianDuration'))),
                DataColumn(label: Text(t('research.table.meanTurns'))),
                DataColumn(label: Text(t('research.table.medianConfidence'))),
                DataColumn(label: Text(t('research.table.redFlagRate'))),
              ],
              rows: [
                for (final l in d.byLanguage)
                  DataRow(cells: [
                    DataCell(Text(l.language)),
                    DataCell(Text('${l.sessions}')),
                    DataCell(Text('${l.completed}')),
                    DataCell(Text(l.medianDurationSeconds == null
                        ? '—'
                        : (l.medianDurationSeconds! / 60).toStringAsFixed(1))),
                    DataCell(Text(l.meanPatientTurns?.toStringAsFixed(2) ?? '—')),
                    DataCell(Text(l.meanSttConfidence?.toStringAsFixed(4) ?? '—')),
                    DataCell(Text(pct(l.redFlagRate))),
                  ]),
              ],
            ),
          ),
        ]),
      ),
    );
  }

  /// Methods crosswalk — which international framework each metric maps to. Needed when
  /// writing the paper's Methods section; `methods.*` was translated and unused.
  Widget _methodsCard(BuildContext context) {
    Widget item(String label, String body) => Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Text('• $label — $body', style: Theme.of(context).textTheme.bodySmall),
        );
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t('research.methods.title'),
              style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
          Text(t('research.methods.subtitle'), style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          item('DECIDE-AI', t('research.methods.decideAi')),
          item('AMIE (Nature 2025)', t('research.methods.amie')),
          item(t('research.methods.triageLabel'), t('research.methods.triage')),
          item('PDQI-9', t('research.methods.pdqi')),
          item(t('research.methods.statsLabel'), t('research.methods.stats')),
          const SizedBox(height: 4),
          Text(t('research.methods.disclaimer'), style: Theme.of(context).textTheme.bodySmall),
        ]),
      ),
    );
  }

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
              child: StatCell(label: tile.$1, value: tile.$2, compact: true),
            ),
          ),
        ),
    ]);
  }

  Widget _table1(BuildContext context, ResearchAnalytics d) {
    Color c(int i) => researchPalette[i % researchPalette.length];
    return _figure(context, 'Table 1', id: 'table1', t('research.demographics.title'), Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('${t('research.demographics.age')}: ${_iqr(d.ageYears)}', style: _tnum),
      if (d.ageYears.mean != null)
        Text('${t('research.demographics.ageMeanSd')}: '
            '${d.ageYears.mean!.toStringAsFixed(1)} ± ${(d.ageYears.sd ?? 0).toStringAsFixed(1)}', style: _tnum),
      GroupHeader(t('research.demographics.ageBands')),
      StackedShareBar(items: [for (var i = 0; i < d.ageBandDistribution.length; i++) (label: d.ageBandDistribution[i].key, count: d.ageBandDistribution[i].count, color: c(i))]),
      const SizedBox(height: 8),
      StackedShareBar(items: [for (var i = 0; i < d.genderDistribution.length; i++) (label: _genderLabel(d.genderDistribution[i].key), count: d.genderDistribution[i].count, color: c(i))]),
      GroupHeader(t('research.demographics.caseMix')),
      Wrap(spacing: 6, runSpacing: 6, children: [for (final b in d.chiefComplaintDistribution.take(8)) PillTag('${b.key} · ${b.count}', color: Theme.of(context).colorScheme.primary)]),
    ]));
  }

  String _genderLabel(String k) => switch (k) {
        'male' => t('research.demographics.gender.male'),
        'female' => t('research.demographics.gender.female'),
        _ => t('research.demographics.gender.other'),
      };

  Widget _weeklyTrend(BuildContext context, ResearchAnalytics d) {
    if (d.weeklyTrend.isEmpty) {
      return EmptyState(icon: Icons.show_chart_outlined, title: t('research.page.empty'));
    }
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
    if (d.durationSeconds.n == 0) {
      return EmptyState(icon: Icons.equalizer_outlined, title: t('research.page.empty'));
    }
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
    if (d.reportsAnalyzed == 0) {
      return EmptyState(icon: Icons.checklist_outlined, title: t('research.page.empty'));
    }
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
      GroupHeader(t('research.safety.severityTitle')),
      StackedShareBar(items: [
        for (final b in d.severityDistribution)
          (label: _labelOr('research.safety.severity.${b.key}', b.key), count: b.count, color: _severityColor(b.key)),
      ]),
    ]);
  }

  Widget _urgencyLayer(BuildContext context, ResearchAnalytics d) {
    Color c(int i) => researchPalette[i % researchPalette.length];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      GroupHeader(t('research.safety.urgencyTitle')),
      StackedShareBar(items: [
        for (final b in d.urgencyDistribution)
          (label: _labelOr('research.safety.urgency.${b.key}', b.key), count: b.count, color: _urgencyColor(b.key)),
      ]),
      GroupHeader(t('research.safety.layerTitle')),
      StackedShareBar(items: [
        for (var i = 0; i < d.layerDistribution.length; i++)
          (label: _labelOr('research.safety.layer.${d.layerDistribution[i].key}', d.layerDistribution[i].key),
              count: d.layerDistribution[i].count, color: c(i)),
      ]),
    ]);
  }

  Widget _stt(BuildContext context, ResearchAnalytics d) {
    if (d.turnsWithConfidence == 0) {
      return EmptyState(icon: Icons.graphic_eq_outlined, title: t('research.page.empty'));
    }
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
      GroupHeader(t('research.documentation.outcomesTitle')),
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
    if (d.byLanguage.isEmpty) {
      return EmptyState(icon: Icons.scatter_plot_outlined, title: t('research.page.empty'));
    }
    return ForestPlotChart(
      rows: [for (final l in d.byLanguage) (label: '${l.language} (n=${l.sessions})', prop: l.redFlagRate)],
      overall: d.alertSession.value,
      overallLabel: t('research.forest.overall'),
      xLabel: t('research.forest.xLabel'),
    );
  }
}
