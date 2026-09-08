import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/exam_orders_api.dart';
import '../../../data/api/reports_api.dart';
import '../../../data/api/sessions_api.dart';
import '../../../data/models/exam_order.dart';
import '../../../data/models/session.dart';
import '../../../data/models/soap_report.dart';
import '../../../shared/widgets/ui_kit.dart';

/// 快速開單：摘要 → 勾選 AI 建議檢查 → 確認送出。
///
/// 2026-09-09 新增的**並行**流程，完整報告頁（SoapReportPage）與它的審閱流程一行
/// 都不動。醫師點「SOAP 報告已生成」的推播會直接落在這裡（notification.dart 的
/// `route()`），因為推播的當下醫師要做的決定通常只有一個：要不要開檢查。要看完整
/// S/O/A/P、逐字稿與 PDF 匯出，頁底有一條連到原本那頁。
///
/// 三個刻意的取捨：
///
/// 1. **預設一項都不勾。** 「快速」不能快到讓醫師在沒讀過的情況下開出檢查——
///    預先勾好等於把 AI 的建議變成預設醫囑。要全開有「全選」，一下就好。
/// 2. **空的送出是合法的。** 「看過摘要、這次不開任何檢查」與「還沒看」在臨床上
///    是兩件事，後端也照這個語意存（見 exam_order.py）。
/// 3. **上一張單裡、現在 AI 不再建議的項目仍然列出**（標記為先前開立）。報告可以
///    被重新生成，plan 會整個換掉；若只畫現在的 AI 清單，醫師會看不到自己上次開過
///    什麼，重送時就會無聲地把它取消掉。
class QuickOrdersPage extends StatefulWidget {
  const QuickOrdersPage({super.key, required this.sessionId});

  final String sessionId;

  @override
  State<QuickOrdersPage> createState() => _QuickOrdersPageState();
}

class _QuickOrdersPageState extends State<QuickOrdersPage> {
  final _reportsApi = ReportsApi();
  final _ordersApi = ExamOrdersApi();
  final _sessionsApi = SessionsApi();
  final _note = TextEditingController();

  SoapReport? _report;
  Session? _session;
  ExamOrder? _latestOrder;

  /// 畫面上的候選項目（AI 建議 ＋ 上一張單裡已不在 AI 清單的項目）。
  List<ExamOrderItem> _candidates = const [];
  final Set<String> _selected = {};

  bool _loading = true;
  bool _error = false;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = false;
    });

    // 場次只餵標題列的病患／主訴，失敗不致命——這頁的重點是報告與勾選。
    final session = _sessionsApi.getSession(widget.sessionId).then((v) {
      if (mounted) setState(() => _session = v);
    }).catchError((_) {});

    try {
      final results = await Future.wait([
        _reportsApi.getReportBySession(widget.sessionId),
        _ordersApi.getLatest(widget.sessionId).catchError((_) => null),
      ]);
      final report = results[0] as SoapReport?;
      final latest = results[1] as ExamOrder?;
      if (!mounted) return;
      setState(() {
        _report = report;
        _latestOrder = latest;
        _candidates = _buildCandidates(report, latest);
        _selected
          ..clear()
          ..addAll(latest?.items.map((i) => i.testName) ?? const <String>[]);
        _note.text = latest?.note ?? '';
        _loading = false;
        _error = report == null;
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = true;
        });
      }
    }

    await session;
  }

  /// AI 建議在前（維持報告裡的順序），上一張單裡多出來的接在後面。
  static List<ExamOrderItem> _buildCandidates(SoapReport? report, ExamOrder? latest) {
    final plan = report?.raw['plan'];
    final rawTests = plan is Map ? (plan['recommendedTests'] ?? plan['recommended_tests']) : null;
    final out = <ExamOrderItem>[];
    final seen = <String>{};
    if (rawTests is List) {
      for (final raw in rawTests) {
        final item = ExamOrderItem.fromPlanTest(raw);
        if (item != null && seen.add(item.testName)) out.add(item);
      }
    }
    for (final item in latest?.items ?? const <ExamOrderItem>[]) {
      if (seen.add(item.testName)) out.add(item);
    }
    return out;
  }

  bool _isAiSuggested(ExamOrderItem item) {
    final plan = _report?.raw['plan'];
    final rawTests = plan is Map ? (plan['recommendedTests'] ?? plan['recommended_tests']) : null;
    if (rawTests is! List) return false;
    return rawTests.any((raw) => ExamOrderItem.fromPlanTest(raw)?.testName == item.testName);
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    final items = [
      for (final c in _candidates)
        if (_selected.contains(c.testName)) c,
    ];
    try {
      final saved = await _ordersApi.submit(
        widget.sessionId,
        items: items,
        note: _note.text.trim().isEmpty ? null : _note.text.trim(),
        reportId: _report?.id,
      );
      if (!mounted) return;
      setState(() {
        _latestOrder = saved;
        _submitting = false;
      });
      _toast(t('soap.quickOrders.submitted'));
    } catch (_) {
      if (!mounted) return;
      setState(() => _submitting = false);
      _toast(t('soap.quickOrders.submitError'));
    }
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(t('soap.quickOrders.title'))),
      body: _body(context),
      bottomNavigationBar: _loading || _error ? null : _actionBar(context),
    );
  }

  Widget _body(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(t('soap.quickOrders.loadError'), textAlign: TextAlign.center),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: _load, child: Text(t('soap.quickOrders.retry'))),
        ]),
      );
    }
    final tk = Theme.of(context).extension<AppTokens>()!;
    final report = _report!;
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      children: [
        if (_session != null) _contextLine(context, tk),
        // 報告還在生成時，plan 是空的——照樣讓醫師進得來，但要說清楚為什麼沒有建議檢查。
        if (report.status == 'generating')
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: PillTag(t('soap.quickOrders.reportGenerating'), color: tk.statusInProgress),
          ),
        _summaryCard(context, report),
        const SizedBox(height: 8),
        _testsCard(context, tk),
        const SizedBox(height: 8),
        _noteCard(context),
        if (_latestOrder != null) ...[
          const SizedBox(height: 8),
          Text(
            t('soap.quickOrders.lastOrdered', args: {'time': _shortTime(_latestOrder!.createdAt)}),
            style: TextStyle(color: tk.inkMuted, fontSize: 12),
          ),
        ],
        const SizedBox(height: 4),
        Center(
          child: TextButton(
            onPressed: () => context.go(prefixLngToPath('/reports/${widget.sessionId}', currentLng)),
            child: Text(t('soap.quickOrders.viewFullReport')),
          ),
        ),
      ],
    );
  }

  Widget _contextLine(BuildContext context, AppTokens tk) {
    final bits = [
      if ((_session?.patientName ?? '').isNotEmpty) _session!.patientName!,
      if ((_session?.chiefComplaintText ?? '').isNotEmpty) _session!.chiefComplaintText!,
    ];
    if (bits.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(bits.join(' · '), style: TextStyle(color: tk.inkSecondary)),
    );
  }

  Widget _summaryCard(BuildContext context, SoapReport report) {
    final summary = (report.summary ?? '').trim();
    return _card(
      context,
      t('soap.quickOrders.summaryTitle'),
      Text(summary.isEmpty ? t('soap.quickOrders.noSummary') : summary),
    );
  }

  Widget _testsCard(BuildContext context, AppTokens tk) {
    Color urgColor(String? u) => switch (u) {
          'er_now' => tk.alertCritical,
          '24h' => tk.alertHigh,
          'this_week' => tk.alertMedium,
          _ => tk.statusWaiting,
        };

    if (_candidates.isEmpty) {
      return _card(context, t('soap.quickOrders.testsTitle'), Text(t('soap.quickOrders.noTests')));
    }

    final allSelected = _selected.length == _candidates.length;
    return _card(
      context,
      t('soap.quickOrders.testsTitle'),
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Align(
          alignment: AlignmentDirectional.centerEnd,
          child: TextButton(
            onPressed: () => setState(() {
              if (allSelected) {
                _selected.clear();
              } else {
                _selected
                  ..clear()
                  ..addAll(_candidates.map((c) => c.testName));
              }
            }),
            child: Text(t(allSelected ? 'soap.quickOrders.clearAll' : 'soap.quickOrders.selectAll')),
          ),
        ),
        for (final item in _candidates)
          CheckboxListTile(
            key: Key('exam-item-${item.testName}'),
            value: _selected.contains(item.testName),
            onChanged: _submitting
                ? null
                : (v) => setState(() {
                      if (v == true) {
                        _selected.add(item.testName);
                      } else {
                        _selected.remove(item.testName);
                      }
                    }),
            controlAffinity: ListTileControlAffinity.leading,
            contentPadding: EdgeInsets.zero,
            title: Row(children: [
              Expanded(child: Text(item.testName)),
              if (item.urgency != null)
                Text(
                  t('soap.plan.urgency.${item.urgency}'),
                  style: TextStyle(color: urgColor(item.urgency), fontSize: 12),
                ),
            ]),
            subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if ((item.rationale ?? '').isNotEmpty)
                Text(item.rationale!, style: Theme.of(context).textTheme.bodySmall),
              if (!_isAiSuggested(item))
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: PillTag(t('soap.quickOrders.previouslyOrdered'), color: tk.inkMuted),
                ),
            ]),
          ),
      ]),
    );
  }

  Widget _noteCard(BuildContext context) => _card(
        context,
        t('soap.quickOrders.noteTitle'),
        TextField(
          key: const Key('exam-order-note'),
          controller: _note,
          maxLines: 3,
          maxLength: 2000,
          enabled: !_submitting,
          decoration: InputDecoration(hintText: t('soap.quickOrders.noteHint')),
        ),
      );

  Widget _actionBar(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (_selected.isEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(
                t('soap.quickOrders.emptySelectionHint'),
                style: TextStyle(color: tk.inkMuted, fontSize: 12),
                textAlign: TextAlign.center,
              ),
            ),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              key: const Key('exam-order-submit'),
              onPressed: _submitting ? null : _submit,
              child: Text(t(_submitting
                  ? 'soap.quickOrders.submitting'
                  : 'soap.quickOrders.submit')),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _card(BuildContext context, String title, Widget body) => Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title,
                style: Theme.of(context)
                    .textTheme
                    .titleSmall
                    ?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            body,
          ]),
        ),
      );

  /// `2026-09-09T01:23:45Z` → `09-09 01:23`。解析不了就原樣顯示，不要吞掉。
  static String _shortTime(String iso) {
    final dt = DateTime.tryParse(iso)?.toLocal();
    if (dt == null) return iso;
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(dt.month)}-${two(dt.day)} ${two(dt.hour)}:${two(dt.minute)}';
  }
}
