import 'package:flutter/material.dart';

import '../../core/i18n/loc.dart';
import '../../core/theme/app_tokens.dart';
import '../../data/api/reports_api.dart';
import '../../data/api/sessions_api.dart';
import '../../data/models/session.dart';
import '../../data/models/soap_report.dart';
import '../../shared/format.dart';

// Port of PatientSessionDetailPage.tsx — patient-friendly read-only view: summary + advice
// derived from the SOAP report (no S/O/A/P detail, no transcript, no ICD-10/confidence).
// getSession failure -> error screen; getReportBySession failure -> report stays null.
class PatientSessionDetailPage extends StatefulWidget {
  const PatientSessionDetailPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  State<PatientSessionDetailPage> createState() => _PatientSessionDetailPageState();
}

class _PatientSessionDetailPageState extends State<PatientSessionDetailPage> {
  Session? _session;
  SoapReport? _report;
  bool _loading = true;
  bool _error = false;

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  Future<void> _load() async {
    try {
      final s = await SessionsApi().getSession(widget.sessionId);
      SoapReport? r;
      try {
        r = await ReportsApi().getReportBySession(widget.sessionId);
      } catch (_) {
        r = null; // report absent -> still render with empty summary/advice
      }
      if (mounted) setState(() { _session = s; _report = r; _loading = false; });
    } catch (_) {
      if (mounted) setState(() { _error = true; _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return Scaffold(body: Center(child: Text(t('session.patientDetail.loading'))));
    }
    if (_error || _session == null) {
      return Scaffold(
        appBar: AppBar(),
        body: Center(child: Text(t('session.patientDetail.notFound'))),
      );
    }
    final s = _session!;
    final r = _report;
    final tk = Theme.of(context).extension<AppTokens>()!;
    final theme = Theme.of(context);

    final advice = (r != null && r.patientEducation.isNotEmpty)
        ? r.patientEducation.join('；')
        : (r?.reviewNotes ?? t('session.patientDetail.adviceEmpty'));

    return Scaffold(
      appBar: AppBar(title: Text(t('session.patientDetail.title'))),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(t('session.patientDetail.recordId', args: {'id': s.id}), style: theme.textTheme.bodySmall),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: theme.colorScheme.primary.withValues(alpha: 0.06),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Icon(Icons.check_circle, size: 18, color: tk.statusCompleted),
                const SizedBox(width: 6),
                Text(t('session.patientDetail.statusCompleted'),
                    style: TextStyle(color: tk.statusCompleted, fontWeight: FontWeight.w600)),
              ]),
              const SizedBox(height: 8),
              Text(formatDateTime(s.createdAt), style: theme.textTheme.bodySmall),
              const SizedBox(height: 8),
              Text(
                t('session.patientDetail.chiefComplaint', args: {
                  'value': s.chiefComplaintText ?? t('session.patientDetail.chiefComplaintEmpty'),
                }),
                style: theme.textTheme.titleMedium,
              ),
            ]),
          ),
          const SizedBox(height: 20),
          _section(context, t('session.patientDetail.summaryHeading'),
              r?.summary ?? t('session.patientDetail.summaryEmpty')),
          const SizedBox(height: 16),
          _section(context, t('session.patientDetail.adviceHeading'), advice),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: _meta(context, t('session.patientDetail.doctorLabel'),
                s.doctorId ?? t('session.patientDetail.doctorUnassigned'))),
            Expanded(child: _meta(context, t('session.patientDetail.durationLabel'),
                s.durationSeconds != null
                    ? t('session.complete.durationMinutes', args: {'minutes': durationMinutes(s.durationSeconds)})
                    : t('session.patientDetail.durationEmpty'))),
          ]),
        ],
      ),
    );
  }

  Widget _section(BuildContext context, String heading, String body) {
    final theme = Theme.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(heading, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
      const SizedBox(height: 6),
      Text(body),
    ]);
  }

  Widget _meta(BuildContext context, String label, String value) {
    final theme = Theme.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: theme.textTheme.bodySmall),
      const SizedBox(height: 2),
      Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
    ]);
  }
}
