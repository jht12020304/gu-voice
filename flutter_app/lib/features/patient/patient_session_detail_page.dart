import 'package:flutter/material.dart';

import '../../core/i18n/loc.dart';
import '../../data/api/reports_api.dart';
import '../../data/api/sessions_api.dart';
import '../../data/models/session.dart';
import '../../data/models/soap_report.dart';
import '../../shared/format.dart';
import '../../shared/widgets/status_badge.dart';
import '../../shared/widgets/ui_kit.dart';
import 'patient_facing_summary.dart';

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
      return const Scaffold(body: SkeletonList(rows: 4));
    }
    if (_error || _session == null) {
      return Scaffold(
        appBar: AppBar(),
        body: EmptyState(
            icon: Icons.search_off_outlined,
            title: t('session.patientDetail.notFound')),
      );
    }
    final s = _session!;
    final r = _report;
    final theme = Theme.of(context);

    // 病患摘要與衛教（SOAP summary + plan.patientEducation）——本頁唯一允許呈現給病患
    // 的「建議」。三件事：
    // 1. 語言。報告本體是中文病歷；非中文場次只有在後端備妥 patient_facing_localized
    //    且語言相符時才顯示在地化內容，否則退回通用訊息（見 patient_facing_summary.dart）。
    //    退回中文原文＝把讀不懂的病歷丟給病患。
    // 2. 空值防禦。型別是 List<String>，但來源是 LLM 產出 + 後端出口過濾，執行期
    //    可能是 null / 空陣列 / 含空字串的陣列（soap_report.dart 的 `edu is List ?
    //    edu.cast<String>()` 對非字串元素還會在**取值時**才丟 TypeError）。resolve 內
    //    把整段包在 try 內並濾掉空白項，任何非預期形狀都退回 adviceEmpty，不炸畫面。
    // 3. **不可**退回 r.reviewNotes——那是醫師的審閱備註（醫師向自由文字），
    //    退回去等於把醫師內部註記顯示給病患。後端這輪對 patientEducation 加了出口
    //    過濾，過濾後常態就是空陣列，舊寫法會讓這個洩漏從邊角情境變成常態。
    //    與 React PatientSessionDetailPage.tsx 一致。
    final view = resolvePatientFacingSummary(
      sessionLanguage: s.language,
      reportSummary: r?.summary,
      reportEducation: r?.patientEducation,
      localized: r?.patientFacingLocalized,
    );
    final advice = view.education.isEmpty
        ? t('session.patientDetail.adviceEmpty')
        : view.education.map((e) => '・$e').join('\n');
    // `??` 只擋 null；後端出口過濾把 summary 換成空字串時會渲染成空白區塊，故 resolve
    // 已把空字串正規化成 null（React 那份的 `||` 本來就有這個行為）。
    final summary = view.summary ??
        (view.useGenericNotice
            ? t('session.patientFacing.notice')
            : t('session.patientDetail.summaryEmpty'));

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
              // 綁真實狀態（2026-08-23 稽核：舊版寫死「已完成」，aborted_red_flag
              // 場次也印成完成）。StatusBadge 已含五種狀態的語意色與五語標籤。
              Row(children: [StatusBadge(s.status)]),
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
          _section(context, t('session.patientDetail.summaryHeading'), summary),
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
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      GroupHeader(heading),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          // 病患端閱讀內容：bodyLarge（讀者含年長病患，比預設大半級）
          child: SizedBox(
            width: double.infinity,
            child: Text(body, style: Theme.of(context).textTheme.bodyLarge),
          ),
        ),
      ),
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
