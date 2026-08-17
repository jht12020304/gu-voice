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

    // 病患衛教（SOAP plan.patientEducation）——本頁唯一允許呈現給病患的「建議」。
    //
    // 兩件事：
    // 1. 空值防禦。型別是 List<String>，但來源是 LLM 產出 + 後端出口過濾，執行期
    //    可能是 null / 空陣列 / 含空字串的陣列（soap_report.dart 的 `edu is List ?
    //    edu.cast<String>()` 對非字串元素還會在**取值時**才丟 TypeError）。這裡把
    //    整段包在 try 內並濾掉空白項，任何非預期形狀都退回 adviceEmpty，不炸畫面。
    // 2. **不可**退回 r.reviewNotes——那是醫師的審閱備註（醫師向自由文字），
    //    退回去等於把醫師內部註記顯示給病患。後端這輪對 patientEducation 加了出口
    //    過濾，過濾後常態就是空陣列，舊寫法會讓這個洩漏從邊角情境變成常態。
    //    與 React PatientSessionDetailPage.tsx 一致。
    List<String> education;
    try {
      education = r == null
          ? const []
          : r.patientEducation.map((e) => e.trim()).where((e) => e.isNotEmpty).toList();
    } catch (_) {
      education = const [];
    }
    final advice = education.isEmpty
        ? t('session.patientDetail.adviceEmpty')
        : education.map((e) => '・$e').join('\n');

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
          // `??` 只擋 null；後端出口過濾把 summary 換成空字串時會渲染成空白區塊，
          // 故改用 trim 後判斷（React 那份的 `||` 本來就有這個行為）。
          _section(context, t('session.patientDetail.summaryHeading'),
              (r?.summary ?? '').trim().isEmpty
                  ? t('session.patientDetail.summaryEmpty')
                  : r!.summary!.trim()),
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
