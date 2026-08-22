import 'package:flutter/material.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/alerts_api.dart';
import '../../../data/models/alert.dart';
import '../../../shared/format.dart';
import '../../../shared/widgets/ui_kit.dart';

// Port of AlertDetailPage.tsx. Uses the alerts API directly with partial-response MERGE on
// acknowledge (never replace the whole alert). llmAnalysis renders string-or-object.
class AlertDetailPage extends StatefulWidget {
  const AlertDetailPage({super.key, required this.alertId});
  final String alertId;

  @override
  State<AlertDetailPage> createState() => _AlertDetailPageState();
}

class _AlertDetailPageState extends State<AlertDetailPage> {
  final _api = AlertsApi();
  final _action = TextEditingController();
  final _notes = TextEditingController();
  RedFlagAlert? _alert;
  bool _loading = true;
  bool _error = false;
  bool _submitting = false;
  String? _recordedActionTaken;

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  @override
  void dispose() {
    _action.dispose();
    _notes.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final a = await _api.get(widget.alertId);
      if (mounted) setState(() { _alert = a; _loading = false; });
    } catch (_) {
      if (mounted) setState(() { _error = true; _loading = false; });
    }
  }

  Future<void> _acknowledge() async {
    final a = _alert;
    if (a == null || a.acknowledged || _submitting) return;
    final action = _action.text.trim();
    final notes = _notes.text.trim();
    setState(() => _submitting = true);
    try {
      final resp = await _api.acknowledge(a.id, actionTaken: action.isEmpty ? null : action, notes: notes.isEmpty ? null : notes);
      final ackAt = resp['acknowledgedAt'] as String? ?? DateTime.now().toUtc().toIso8601String();
      if (!mounted) return;
      setState(() {
        _alert = a.mergeAck(
          acknowledgedAt: ackAt,
          acknowledgedBy: resp['acknowledgedBy'] as String?,
          acknowledgeNotes: notes.isEmpty ? null : notes,
          actionTaken: action.isEmpty ? null : action,
        );
        _recordedActionTaken = action.isEmpty ? null : action;
        _submitting = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t('dashboard.alert.detail.acknowledgeSuccess'))));
    } catch (_) {
      if (mounted) setState(() => _submitting = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t('dashboard.alert.detail.acknowledgeError'))));
    }
  }

  @override
  Widget build(BuildContext context) {
    // 三態都掛同一個標題，骨架/錯誤/內容切換時 AppBar 不跳動。
    if (_loading) {
      return Scaffold(
        appBar: AppBar(title: Text(t('dashboard.alert.detail.title'))),
        body: _loadingSkeleton(),
      );
    }
    if (_error || _alert == null) {
      return Scaffold(
        appBar: AppBar(title: Text(t('dashboard.alert.detail.title'))),
        body: ErrorState(
          message: t('dashboard.alert.detail.notFound'),
          retryLabel: t('common.retry'),
          onRetry: _load,
        ),
      );
    }
    final a = _alert!;
    final tk = Theme.of(context).extension<AppTokens>()!;
    final sevColor = switch (a.severity) {
      'critical' => tk.alertCritical,
      'high' => tk.alertHigh,
      _ => tk.alertMedium,
    };

    return Scaffold(
      appBar: AppBar(title: Text(t('dashboard.alert.detail.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            color: tk.alertCriticalBg,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text(a.title, style: TextStyle(color: sevColor, fontWeight: FontWeight.w700, fontSize: 18))),
                  const SizedBox(width: 8),
                  PillTag(a.severity.toUpperCase(), color: sevColor),
                ]),
                if (a.acknowledged)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: PillTag(t('dashboard.alert.detail.acknowledgedBadge'), color: tk.statusCompleted),
                  ),
                const SizedBox(height: 8),
                Text(a.triggerReason, style: TextStyle(color: sevColor)),
                const SizedBox(height: 8),
                Text('${t('dashboard.alert.detail.occurredAt')}: ${formatDateTime(a.createdAt)}',
                    style: Theme.of(context).textTheme.bodySmall),
                Text('${t('dashboard.alert.detail.sessionIdLabel')}: ${a.sessionId}',
                    style: Theme.of(context).textTheme.bodySmall),
              ]),
            ),
          ),
          const SizedBox(height: 12),
          _section(context, t('dashboard.alert.detail.triggerKeywords'),
              a.triggerKeywords.isEmpty
                  ? Text(t('dashboard.alert.detail.noKeywords'), style: TextStyle(color: tk.inkMuted))
                  : Wrap(spacing: 6, runSpacing: 6, children: [for (final k in a.triggerKeywords) Chip(label: Text('「$k」'))])),
          _section(context, t('dashboard.alert.detail.llmAnalysis'),
              a.llmAnalysisText.isEmpty
                  ? Text(t('dashboard.alert.detail.noLlmAnalysis'), style: TextStyle(color: tk.inkMuted))
                  : Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(color: Theme.of(context).colorScheme.surfaceContainerHighest, borderRadius: BorderRadius.circular(8)),
                      child: Text(a.llmAnalysisText, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
                    )),
          _section(context, t('dashboard.alert.detail.suggestedActions'),
              a.suggestedActions.isEmpty
                  ? Text(t('dashboard.alert.detail.noSuggestedActions'), style: TextStyle(color: tk.inkMuted))
                  : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      for (var i = 0; i < a.suggestedActions.length; i++)
                        _SuggestedActionRow(index: i + 1, text: a.suggestedActions[i]),
                    ])),
          const SizedBox(height: 8),
          if (a.acknowledged) _acknowledgedBox(context, a, tk) else _ackForm(context),
        ],
      ),
    );
  }

  Widget _acknowledgedBox(BuildContext context, RedFlagAlert a, AppTokens tk) {
    final recorded = _recordedActionTaken ?? a.actionTaken ?? '';
    return Card(
      color: tk.alertSuccessBg,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t('dashboard.alert.detail.acknowledgedHeading'), style: TextStyle(color: tk.alertSuccess, fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          Text('${t('dashboard.alert.detail.actionTakenLabel')}: ${recorded.isEmpty ? t('dashboard.alert.detail.noActionRecorded') : recorded}'),
        ]),
      ),
    );
  }

  Widget _ackForm(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          TextField(
            controller: _action,
            enabled: !_submitting,
            maxLines: 3,
            decoration: InputDecoration(
              labelText: t('dashboard.alert.detail.actionTakenLabel'),
              hintText: t('dashboard.alert.detail.actionTakenPlaceholder'),
            ),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _notes,
            enabled: !_submitting,
            maxLines: 2,
            decoration: InputDecoration(
              labelText: t('dashboard.alert.detail.notesLabel'),
              hintText: t('dashboard.alert.detail.notesPlaceholder'),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _submitting ? null : _acknowledge,
            child: Text(t(_submitting ? 'dashboard.alert.detail.acknowledging' : 'dashboard.alert.detail.acknowledgeButton')),
          ),
        ]),
      ),
    );
  }

  Widget _section(BuildContext context, String title, Widget body) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        body,
      ]),
    );
  }

  // 區塊骨架：外形貼近下方真實版面（橫幅卡＋三個區段），避免載入完成時整頁跳動。
  Widget _loadingSkeleton() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: const [
        SkeletonBox(width: double.infinity, height: 116, radius: 8),
        SizedBox(height: 20),
        SkeletonBox(width: 96, height: 14),
        SizedBox(height: 8),
        SkeletonBox(width: double.infinity, height: 32, radius: 8),
        SizedBox(height: 20),
        SkeletonBox(width: 96, height: 14),
        SizedBox(height: 8),
        SkeletonBox(width: double.infinity, height: 64, radius: 8),
        SizedBox(height: 20),
        SkeletonBox(width: double.infinity, height: 140, radius: 8),
      ],
    );
  }
}

// 建議行動的單列：編號圓點沿用 IconTile 同款 12% 底色語言，只是圖示換成序號。
class _SuggestedActionRow extends StatelessWidget {
  const _SuggestedActionRow({required this.index, required this.text});

  final int index;
  final String text;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final primary = Theme.of(context).colorScheme.primary;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 20,
          height: 20,
          alignment: Alignment.center,
          decoration: BoxDecoration(color: primary.withValues(alpha: 0.12), shape: BoxShape.circle),
          child: Text('$index', style: TextStyle(color: primary, fontSize: 11, fontWeight: FontWeight.w700)),
        ),
        const SizedBox(width: 10),
        Expanded(child: Text(text, style: TextStyle(color: tk.inkBody))),
      ]),
    );
  }
}
