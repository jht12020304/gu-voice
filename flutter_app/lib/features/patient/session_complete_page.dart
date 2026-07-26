import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../core/theme/app_tokens.dart';
import '../../data/api/reports_api.dart';
import '../../data/api/sessions_api.dart';
import '../../data/models/session.dart';
import '../../data/models/soap_report.dart';
import '../../shared/format.dart';

// Port of SessionCompletePage.tsx — the reviewable post-consult summary reached by tapping
// a completed session. Session fetch failure degrades gracefully (summary card hidden, rest
// still renders). SOAP generation is async (Celery), so the report card polls until ready.
class SessionCompletePage extends StatefulWidget {
  const SessionCompletePage({super.key, required this.sessionId});
  final String sessionId;

  @override
  State<SessionCompletePage> createState() => _SessionCompletePageState();
}

class _SessionCompletePageState extends State<SessionCompletePage> {
  Session? _session;
  SoapReport? _report;
  bool _loadingSession = true;
  bool _loadingReport = true;
  Timer? _pollTimer;
  int _attempts = 0;
  static const _maxAttempts = 12;

  @override
  void initState() {
    super.initState();
    Future.microtask(_loadSession);
    _loadReport();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }

  Future<void> _loadSession() async {
    try {
      final s = await SessionsApi().getSession(widget.sessionId);
      if (mounted) setState(() { _session = s; _loadingSession = false; });
    } catch (_) {
      if (mounted) setState(() => _loadingSession = false); // silent: hide summary card
    }
  }

  Future<void> _loadReport() async {
    _attempts++;
    try {
      final r = await ReportsApi().getReportBySession(widget.sessionId);
      if (!mounted) return;
      setState(() { _report = r; _loadingReport = false; });
      // Poll while the report is missing or still generating.
      final generating = r == null || r.status == 'generating';
      if (generating && _attempts < _maxAttempts) {
        _pollTimer = Timer(const Duration(seconds: 3), _loadReport);
      }
    } catch (_) {
      if (mounted) setState(() => _loadingReport = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loadingSession && _loadingReport) {
      return Scaffold(body: Center(child: Text(t('session.complete.loading'))));
    }
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(t('session.complete.title'))),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Center(
            child: Column(children: [
              Icon(Icons.check_circle, size: 48, color: theme.colorScheme.primary),
              const SizedBox(height: 8),
              Text(t('session.complete.subtitle'), style: theme.textTheme.bodyMedium),
            ]),
          ),
          const SizedBox(height: 24),
          if (_session != null) _summaryCard(context, _session!),
          const SizedBox(height: 16),
          _reportCard(context),
          const SizedBox(height: 16),
          _nextStepsCard(context),
          const SizedBox(height: 24),
          Row(children: [
            Expanded(
              child: FilledButton(
                onPressed: () => context.go(prefixLngToPath('/patient', currentLng)),
                child: Text(t('session.complete.actionHome')),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: OutlinedButton(
                onPressed: () => context.go(prefixLngToPath('/patient/history', currentLng)),
                child: Text(t('session.complete.actionHistory')),
              ),
            ),
          ]),
        ],
      ),
    );
  }

  Widget _summaryCard(BuildContext context, Session s) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final duration = s.durationSeconds != null
        ? t('session.complete.durationMinutes', args: {'minutes': durationMinutes(s.durationSeconds)})
        : t('session.complete.durationEmpty');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(t('session.complete.summaryTitle').toUpperCase(), style: Theme.of(context).textTheme.labelMedium),
            const SizedBox(height: 12),
            _row(t('session.complete.summaryChiefComplaint'), s.chiefComplaintText ?? '—'),
            _row(t('session.complete.summaryStartedAt'), formatDateTime(s.startedAt ?? s.createdAt)),
            _row(t('session.complete.summaryDuration'), duration),
            if (s.redFlag) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: tk.alertCriticalBg, borderRadius: BorderRadius.circular(8)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(t('session.complete.redFlagTitle'),
                      style: TextStyle(color: tk.alertCritical, fontWeight: FontWeight.w700)),
                  if (s.redFlagReason != null) Text(s.redFlagReason!, style: TextStyle(color: tk.alertCritical)),
                ]),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _reportCard(BuildContext context) {
    final theme = Theme.of(context);
    final tk = theme.extension<AppTokens>()!;
    final r = _report;
    Widget body;
    if (_loadingReport || (r != null && r.status == 'generating') || (r == null && _attempts < _maxAttempts)) {
      body = Row(children: [
        const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2)),
        const SizedBox(width: 12),
        Text(t('session.complete.reportAnalyzing')),
      ]);
    } else if (r != null && r.status == 'generated') {
      final (label, color) = switch (r.reviewStatus) {
        'approved' => (t('session.complete.reviewStatusApproved'), tk.statusCompleted),
        'revision_needed' => (t('session.complete.reviewStatusRevisionNeeded'), tk.alertCritical),
        _ => (t('session.complete.reviewStatusPending'), tk.alertMedium),
      };
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (r.summary != null) Text(r.summary!),
        if (r.icd10Codes.isNotEmpty) ...[
          const SizedBox(height: 12),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final c in r.icd10Codes)
              Chip(label: Text(c), visualDensity: VisualDensity.compact),
          ]),
        ],
        const SizedBox(height: 12),
        Row(children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(9999)),
            child: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w600, fontSize: 12)),
          ),
          if (r.aiConfidenceScore != null) ...[
            const SizedBox(width: 8),
            Text(t('session.complete.aiConfidence', args: {'percent': (r.aiConfidenceScore! * 100).round()}),
                style: theme.textTheme.bodySmall),
          ],
        ]),
      ]);
    } else {
      body = Text(t('session.complete.reportEmpty'));
    }
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t('session.complete.reportTitle').toUpperCase(), style: theme.textTheme.labelMedium),
          const SizedBox(height: 12),
          body,
        ]),
      ),
    );
  }

  Widget _nextStepsCard(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t('session.complete.nextStepsTitle').toUpperCase(), style: theme.textTheme.labelMedium),
          const SizedBox(height: 8),
          for (final k in const ['nextStep1', 'nextStep2', 'nextStep3'])
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text('— ${t('session.complete.$k')}'),
            ),
        ]),
      ),
    );
  }

  Widget _row(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 96, child: Text(label, style: const TextStyle(fontWeight: FontWeight.w500))),
          Expanded(child: Text(value)),
        ]),
      );
}
