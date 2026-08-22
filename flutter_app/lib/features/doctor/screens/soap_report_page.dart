import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/reports_api.dart';
import '../../../data/api/sessions_api.dart';
import '../../../data/models/session.dart';
import '../../../data/models/soap_report.dart';
import '../../../shared/pdf_share.dart';
import '../../../shared/widgets/ui_kit.dart';

// `unknown` is the window before the Session has come back. It must be its own case:
// collapsing it into `clear` renders a red-flag session as "no red flag" for as long as
// that request takes, which is the exact failure the amber `loadFailed` state was
// introduced to prevent. (This hole predates the parallel load below — the page already
// painted before `getSession` resolved — but parallelising widens it, so it is fixed here.)
enum _RedFlagState { redFlag, loadFailed, clear, unknown }

/// 「重新產生報告」按鈕的閘門。與 `canGenerateSoapReport`（場次詳情頁的**首次**產生）
/// 分開：那條在 `generated` 時刻意不給按鈕（避免誤觸覆蓋），這條是醫師在報告頁上對著
/// 一份已產生／已失敗的報告主動要求重跑。
///
/// `generating` 一律不可按——重複派 Celery 任務會讓兩份結果互相覆蓋，而且後端會先把現有
/// 內容清空重置，中途再派一次等於把還沒寫回的那份也丟掉。UI 上是 disabled 而不是隱藏：
/// 按鈕消失跟「沒反應」在醫師眼裡無法區分。
bool canRegenerateSoapReport(String? reportStatus) =>
    reportStatus == 'generated' || reportStatus == 'failed';

// Port of SOAPReportPage.tsx (v1). Correctness-critical parts kept faithfully:
//  - the amber session-load TRI-STATE (a red-flag session whose Session failed to load
//    must NOT render as "no red flag")
//  - review gating (bar only when reviewStatus==pending && status==generated, re-checked
//    on submit; revision_needed requires notes)
//  - PDF export gated to status==generated
// The messy nested S/O/A/P is read defensively from report.raw (the normalizer).
class SoapReportPage extends StatefulWidget {
  const SoapReportPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  State<SoapReportPage> createState() => _SoapReportPageState();
}

class _SoapReportPageState extends State<SoapReportPage> {
  final _reportsApi = ReportsApi();
  SoapReport? _report;
  List<ConversationTurn> _turns = const [];
  bool _turnsFailed = false;
  Session? _session;
  bool _sessionLoadFailed = false;
  bool _sessionLoading = true;
  bool _turnsLoading = true;
  bool _loading = true;
  bool _error = false;
  bool _exporting = false;
  bool _regenerating = false;

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  /// Three independent fetches, started together.
  ///
  /// They used to run in series — report (itself two trips: list-by-session, then fetch
  /// by id), then the transcript, then the Session — and nothing was painted until the
  /// first two had both finished. That is four sequential round trips to Railway before
  /// the doctor's main screen shows anything but a line of grey text; at a 250-400 ms
  /// RTT it is most of a second, and on cellular considerably more.
  ///
  /// Only the report gates the render now. The transcript belongs to the second tab and
  /// the Session only feeds the red-flag banner, so neither has any business holding the
  /// first paint — as long as each has an honest "not back yet" state, which is what
  /// `_turnsLoading` and `_sessionLoading` are for.
  Future<void> _load() async {
    final sessions = SessionsApi();

    // Transcript for the second tab. Failure is non-fatal: the report is the point of
    // this page, so a transcript fetch error must not blank it out.
    final turns = sessions.getConversations(widget.sessionId).then((v) {
      if (mounted) setState(() { _turns = v; _turnsLoading = false; });
    }).catchError((_) {
      if (mounted) setState(() { _turnsFailed = true; _turnsLoading = false; });
    });

    // Session's failure drives the amber tri-state, NOT "no flag".
    final session = sessions.getSession(widget.sessionId).then((v) {
      if (mounted) setState(() { _session = v; _sessionLoadFailed = false; _sessionLoading = false; });
    }).catchError((_) {
      if (mounted) setState(() { _session = null; _sessionLoadFailed = true; _sessionLoading = false; });
    });

    try {
      final r = await _reportsApi.getReportBySession(widget.sessionId);
      if (mounted) setState(() { _report = r; _loading = false; _error = r == null; });
    } catch (_) {
      if (mounted) setState(() { _error = true; _loading = false; });
    }

    // Awaited only so callers (and tests) can wait for the screen to be fully settled;
    // both have already applied their own results above. Neither can throw — `catchError`
    // consumed it — so this cannot mask a failure.
    await Future.wait([turns, session]);
  }

  _RedFlagState get _redFlagState {
    if (_session?.redFlag == true) return _RedFlagState.redFlag;
    if (_sessionLoadFailed) return _RedFlagState.loadFailed;
    if (_sessionLoading) return _RedFlagState.unknown;
    return _RedFlagState.clear;
  }

  // ---- defensive raw readers (the normalizer) ----
  static Map _map(dynamic v) => v is Map ? v : const {};
  static String _s(dynamic v) => v == null ? '' : v.toString();
  static List<String> _arr(dynamic v) {
    if (v is List) return [for (final e in v) if (e != null && '$e'.trim().isNotEmpty) '$e'];
    if (v is String && v.trim().isNotEmpty) return [v];
    return [];
  }

  Future<void> _exportPdf() async {
    final r = _report;
    if (r == null || r.status != 'generated' || _exporting) return;
    setState(() => _exporting = true);
    try {
      final bytes = await _reportsApi.getPdf(r.id);
      await sharePdfBytes(bytes, 'soap-report-${r.id}.pdf');
      if (mounted) _toast(t('soap.export.success'));
    } catch (_) {
      if (mounted) _toast(t('soap.export.error'));
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _regenerate() async {
    final r = _report;
    // 第二道防線：閘門在 UI 已判過一次，這裡再判一次（dialog 開著時狀態可能已變）。
    if (r == null || _regenerating || !canRegenerateSoapReport(r.status)) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(t('soap.regenerate.title')),
        content: Text(t('soap.regenerate.description')),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(t('soap.regenerate.cancel')),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(t('soap.regenerate.confirm')),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _regenerating = true);
    try {
      // 後端會把現有 row 重置為 generating 並回傳它——直接吃回傳值，按鈕隨即因狀態
      // 變成 generating 而 disabled，不需要另外樂觀更新。
      final updated = await _reportsApi.generateReport(widget.sessionId);
      if (!mounted) return;
      setState(() { _report = updated; _regenerating = false; });
      _toast(t('soap.regenerate.success'));
    } catch (_) {
      if (!mounted) return;
      setState(() => _regenerating = false);
      _toast(t('soap.regenerate.error'));
    }
  }

  Future<void> _review(String action) async {
    final r = _report;
    if (r == null || r.status != 'generated') return; // second line of defense
    final result = await showDialog<({String status, String? notes})>(
      context: context,
      builder: (_) => _ReviewDialog(action: action),
    );
    if (result == null) return;
    try {
      final updated = await _reportsApi.review(r.id, result.status, notes: result.notes);
      if (mounted) setState(() => _report = updated);
      _toast(t('soap.review.actionEyebrow'));
    } catch (_) {
      _toast(t('soap.review.submitError'));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return Scaffold(appBar: AppBar(), body: const SkeletonList());
    if (_error || _report == null) {
      return Scaffold(
        appBar: AppBar(),
        body: EmptyState(icon: Icons.description_outlined, title: t('soap.page.notGenerated')),
      );
    }
    final r = _report!;
    final isReviewed = r.reviewStatus != 'pending';
    final showReviewBar = !isReviewed && r.status == 'generated';

    // Two tabs so the reviewing doctor can check the report against the patient's own
    // words before approving it. `soap.tabs.*` was already translated, unused (TODO §G).
    return DefaultTabController(
      length: 2,
      child: Scaffold(
      appBar: AppBar(
        title: Text(t('soap.page.title')),
        bottom: TabBar(tabs: [
          Tab(text: t('soap.tabs.report')),
          Tab(text: t('soap.tabs.transcript')),
        ]),
        actions: [
          IconButton(
            icon: _exporting
                ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.picture_as_pdf),
            tooltip: t('soap.export.button'),
            onPressed: r.status == 'generated' ? _exportPdf : null,
          ),
          // failed 的報告在這頁是唯一的重跑入口（場次詳情頁的產生按鈕只在還沒有報告或
          // 產生失敗時出現，且醫師通常是從通知直接進到這頁）。
          IconButton(
            icon: _regenerating
                ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.refresh),
            tooltip: t(_regenerating ? 'soap.regenerate.loading' : 'soap.regenerate.button'),
            onPressed: (_regenerating || !canRegenerateSoapReport(r.status)) ? null : _regenerate,
          ),
        ],
      ),
      body: TabBarView(children: [
        ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _metaHeader(context),
            _badges(context, r),
            _redFlagCard(context),
            const SizedBox(height: 16),
            _summaryCard(context, r),
            _icd10Card(context, r),
            ..._soapSections(context, r),
            if (r.reviewNotes != null && r.reviewNotes!.isNotEmpty)
              _card(context, t('soap.reviewNotesCard.title'), Text(r.reviewNotes!)),
          ],
        ),
        _transcriptTab(context),
      ]),
      bottomNavigationBar: showReviewBar ? _reviewBar(context) : null,
      ),
    );
  }

  Widget _transcriptTab(BuildContext context) {
    if (_turnsFailed) {
      return EmptyState(icon: Icons.error_outline, title: t('session.doctor.detail.loadError'));
    }
    // The transcript no longer blocks the first paint, so the tab can be opened while it
    // is still in flight. Without this case the empty-state text claims the consultation
    // had no turns, which for a doctor reading a report is a factual statement about the
    // patient, not a loading artefact.
    if (_turnsLoading) {
      return const SkeletonList();
    }
    if (_turns.isEmpty) {
      return EmptyState(icon: Icons.forum_outlined, title: t('session.doctor.detail.conversationsEmpty'));
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _turns.length,
      itemBuilder: (context, i) => _bubble(context, _turns[i]),
    );
  }

  /// Same bubble shape as the session detail page (patient right, AI left, system centred).
  Widget _bubble(BuildContext context, ConversationTurn c) {
    final isPatient = c.role == 'patient';
    final isSystem = c.role == 'system';
    final scheme = Theme.of(context).colorScheme;
    return Align(
      alignment: isSystem
          ? Alignment.center
          : (isPatient ? Alignment.centerRight : Alignment.centerLeft),
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
        decoration: BoxDecoration(
          color: isSystem
              ? scheme.surfaceContainerHighest
              : (isPatient ? scheme.primaryContainer : scheme.secondaryContainer),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Text(c.contentText),
      ),
    );
  }

  // Patient/session context + cross-navigation for the reviewing doctor.
  Widget _metaHeader(BuildContext context) {
    final s = _session;
    if (s == null) return const SizedBox.shrink();
    final patient = (s.patientName?.isNotEmpty ?? false) ? s.patientName! : t('dashboard.alert.detail.unknownPatient');
    final complaint = s.chiefComplaintText ?? t('common.doctor.patient.noComplaint');
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('$patient · $complaint', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 4),
        Wrap(spacing: 8, children: [
          OutlinedButton.icon(
            icon: const Icon(Icons.forum_outlined, size: 16),
            label: Text(t('soap.actions.viewSession')),
            onPressed: () => context.go(prefixLngToPath('/sessions/${s.id}', currentLng)),
          ),
        ]),
      ]),
    );
  }

  Widget _badges(BuildContext context, SoapReport r) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final (statusLabel, statusColor) = switch (r.status) {
      'generated' => (t('soap.reportStatus.generated'), tk.statusCompleted),
      'generating' => (t('soap.reportStatus.generating'), tk.alertMedium),
      _ => (t('soap.reportStatus.failed'), tk.alertCritical),
    };
    final (reviewLabel, reviewColor) = switch (r.reviewStatus) {
      'approved' => (t('soap.reviewStatus.approved'), tk.statusCompleted),
      'revision_needed' => (t('soap.reviewStatus.revisionNeeded'), tk.alertCritical),
      _ => (t('soap.reviewStatus.pending'), tk.alertMedium),
    };
    return Wrap(spacing: 8, runSpacing: 8, children: [
      PillTag(statusLabel, color: statusColor),
      PillTag(reviewLabel, color: reviewColor),
      if (r.aiConfidenceScore != null)
        PillTag(t('session.complete.aiConfidence', args: {'percent': (r.aiConfidenceScore! * 100).round()}), color: tk.statusInProgress),
    ]);
  }

  Widget _redFlagCard(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    switch (_redFlagState) {
      case _RedFlagState.redFlag:
        return _banner(tk.alertCritical, tk.alertCriticalBg, t('soap.redFlag.title'),
            _session?.redFlagReason ?? t('soap.redFlag.defaultReason'));
      case _RedFlagState.loadFailed:
        return _banner(tk.alertHigh, tk.alertHighBg, t('soap.redFlag.loadFailedTitle'),
            t('soap.redFlag.loadFailedDescription'));
      case _RedFlagState.unknown:
        // Neutral and explicitly provisional — never `SizedBox.shrink()`, which is what
        // "this session has no red flag" looks like. Same box height as the two real
        // banners so resolving it does not shove the report down the page.
        return _banner(tk.inkMuted, tk.chatBg, t('common.loading'), '');
      case _RedFlagState.clear:
        return const SizedBox.shrink();
    }
  }

  Widget _banner(Color fg, Color bg, String title, String body) => Container(
        width: double.infinity,
        margin: const EdgeInsets.only(top: 12),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: TextStyle(color: fg, fontWeight: FontWeight.w700)),
          Text(body, style: TextStyle(color: fg)),
        ]),
      );

  Widget _summaryCard(BuildContext context, SoapReport r) {
    final assessment = _map(r.raw['assessment']);
    final summary = r.summary ?? _s(assessment['clinicalImpression']);
    return _card(context, t('soap.page.clinicalSummaryEyebrow'),
        Text(summary.isEmpty ? t('soap.page.noSummary') : summary));
  }

  Widget _icd10Card(BuildContext context, SoapReport r) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return _card(context, t('soap.diagnosis.title'), Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (r.icd10Codes.isEmpty)
        Text(t('soap.diagnosis.empty'))
      else
        Wrap(spacing: 6, runSpacing: 6, children: [for (final c in r.icd10Codes) Chip(label: Text(c), visualDensity: VisualDensity.compact)]),
      // Amber only when explicitly false (absent/undefined does NOT warn).
      if (r.icd10Verified == false) ...[
        const SizedBox(height: 6),
        Text(t('soap.diagnosis.unverified'), style: TextStyle(color: tk.alertMedium, fontSize: 12)),
      ],
    ]));
  }

  List<Widget> _soapSections(BuildContext context, SoapReport r) {
    // Order A, P, S, O (assessment/plan surfaced first) to match the web.
    return [
      _assessment(context, _map(r.raw['assessment'])),
      _plan(context, _map(r.raw['plan'])),
      _subjective(context, _map(r.raw['subjective'])),
      _objective(context, _map(r.raw['objective'])),
    ];
  }

  Widget _subjective(BuildContext context, Map s) {
    final cc = _s(s['chiefComplaint'] ?? s['chief_complaint']);
    final hpi = _map(s['hpi']);
    final pmh = _map(s['pastMedicalHistory'] ?? s['past_medical_history']);
    final meds = _map(s['medicationHistory'] ?? s['medication_history'] ?? s['medications']);
    final sysReview = _map(s['systemReview'] ?? s['system_review'] ?? s['reviewOfSystems'] ?? s['review_of_systems']);
    final social = _map(s['socialHistory'] ?? s['social_history']);
    return _card(context, t('soap.section.subjective.title'), Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (cc.isNotEmpty) _kv(t('soap.subjective.chiefComplaint'), cc),
      for (final f in const ['onset', 'location', 'duration', 'severity', 'characteristics', 'timing', 'context'])
        if (_s(hpi[f]).isNotEmpty) _kv(t('soap.subjective.hpi.$f'), _s(hpi[f])),
      _tagRow(context, t('soap.subjective.hpi.aggravatingFactors'), _arr(hpi['aggravatingFactors'] ?? hpi['aggravating_factors'])),
      _tagRow(context, t('soap.subjective.hpi.relievingFactors'), _arr(hpi['relievingFactors'] ?? hpi['relieving_factors'])),
      _tagRow(context, t('soap.subjective.hpi.associatedSymptoms'), _arr(hpi['associatedSymptoms'] ?? hpi['associated_symptoms'])),
      _tagRow(context, t('soap.subjective.pastMedicalHistory.conditions'), _arr(pmh['conditions'])),
      _tagRow(context, t('soap.subjective.pastMedicalHistory.surgeries'), _arr(pmh['surgeries'])),
      _tagRow(context, t('soap.subjective.pastMedicalHistory.hospitalizations'), _arr(pmh['hospitalizations'])),
      _tagRow(context, t('soap.subjective.medicationHistory.current'), _arr(meds['current'])),
      _tagRow(context, t('soap.subjective.medicationHistory.past'), _arr(meds['past'])),
      _tagRow(context, t('soap.subjective.medicationHistory.otc'), _arr(meds['otc'])),
      // Review of systems + social history: dynamic key/value maps.
      for (final e in sysReview.entries)
        if (_s(e.value).isNotEmpty) _kv(_fieldLabel(e.key.toString()), _s(e.value)),
      for (final e in social.entries)
        if (_s(e.value).isNotEmpty) _kv(_fieldLabel(e.key.toString()), _s(e.value)),
    ]));
  }

  // fieldLabels.<key> with fallback to the raw key (matches resolveFieldLabel).
  String _fieldLabel(String key) {
    final label = t('soap.fieldLabels.$key');
    return label == 'soap.fieldLabels.$key' ? key : label;
  }

  Widget _objective(BuildContext context, Map o) {
    final vitals = _map(o['vitalSigns'] ?? o['vital_signs']);
    final physical = _map(o['physicalExam'] ?? o['physical_exam']);
    final labs = o['labResults'] ?? o['lab_results'];
    final tk = Theme.of(context).extension<AppTokens>()!;
    bool abn(Map lab) => (lab['isAbnormal'] ?? lab['is_abnormal']) == true;
    return _card(context, t('soap.section.objective.title'), Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final key in const ['bloodPressure', 'heartRate', 'respiratoryRate', 'temperature', 'spo2'])
        if (vitals[key] != null)
          _kv(t('soap.objective.vitalSigns.labels.$key'), '${_s(vitals[key])} ${t('soap.objective.vitalSigns.units.$key')}'.trim()),
      // Physical exam: dynamic key/value.
      if (physical.isNotEmpty) ...[
        const SizedBox(height: 4),
        Text(t('soap.objective.physicalExam.title'), style: const TextStyle(fontWeight: FontWeight.w600)),
        for (final e in physical.entries)
          if (_s(e.value).isNotEmpty) _kv(_fieldLabel(e.key.toString()), _s(e.value)),
      ],
      if (labs is List && labs.isNotEmpty) ...[
        const SizedBox(height: 4),
        Text(t('soap.objective.labResults.title'), style: const TextStyle(fontWeight: FontWeight.w600)),
        for (final lab in labs)
          if (lab is Map)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(children: [
                Expanded(child: Text(_s(lab['testName'] ?? lab['test_name']))),
                if (_s(lab['referenceRange'] ?? lab['reference_range']).isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 6),
                    child: Text(_s(lab['referenceRange'] ?? lab['reference_range']),
                        style: Theme.of(context).textTheme.bodySmall),
                  ),
                Text(_s(lab['result']),
                    style: TextStyle(color: abn(lab) ? tk.alertCritical : null, fontWeight: abn(lab) ? FontWeight.w700 : null)),
              ]),
            ),
      ],
    ]));
  }

  Widget _assessment(BuildContext context, Map a) {
    final impression = _s(a['clinicalImpression'] ?? a['clinical_impression']);
    final ddx = a['differentialDiagnoses'] ?? a['differential_diagnoses'];
    final tk = Theme.of(context).extension<AppTokens>()!;
    Color probColor(String p) => switch (p) { 'high' => tk.alertCritical, 'medium' => tk.alertMedium, _ => tk.statusWaiting };
    return _card(context, t('soap.section.assessment.title'), Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (impression.isNotEmpty) Text(impression),
      if (ddx is List)
        for (var i = 0; i < ddx.length; i++)
          if (ddx[i] is Map)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${i + 1}. '),
                  Expanded(child: Text(_s(ddx[i]['diagnosis']))),
                  if (_s(ddx[i]['icd10']).isNotEmpty) Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 6),
                    child: Text(_s(ddx[i]['icd10']), style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
                  ),
                  Builder(builder: (_) {
                    final p = () {
                      final raw = _s(ddx[i]['probability'] ?? ddx[i]['likelihood']);
                      return raw == 'moderate' ? 'medium' : (raw.isEmpty ? 'low' : raw);
                    }();
                    return Text(t('soap.assessment.probability.$p'), style: TextStyle(color: probColor(p), fontSize: 12));
                  }),
                ]),
                if (_s(ddx[i]['reasoning']).isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(left: 18, top: 2),
                    child: Text(_s(ddx[i]['reasoning']), style: Theme.of(context).textTheme.bodySmall),
                  ),
              ]),
            ),
    ]));
  }

  Widget _plan(BuildContext context, Map p) {
    final reasoning = _s(p['diagnosticReasoning'] ?? p['diagnostic_reasoning']);
    final tests = p['recommendedTests'] ?? p['recommended_tests'];
    final treatments = p['treatments'];
    final followUp = _map(p['followUp'] ?? p['follow_up']);
    final edu = _arr(p['patientEducation'] ?? p['patient_education']);
    final referrals = _arr(p['referrals']);
    final tk = Theme.of(context).extension<AppTokens>()!;
    Color urgColor(String u) => switch (u) {
          'er_now' => tk.alertCritical,
          '24h' => tk.alertHigh,
          'this_week' => tk.alertMedium,
          _ => tk.statusWaiting,
        };
    return _card(context, t('soap.section.plan.title'), Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (reasoning.isNotEmpty) ...[
        _kv(t('soap.plan.diagnosticReasoning'), reasoning),
        const SizedBox(height: 4),
      ],
      if (tests is List)
        for (final test in tests)
          if (test is Map)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text(_s(test['testName'] ?? test['test_name']))),
                  Builder(builder: (_) {
                    final u = _s(test['urgency']).isEmpty ? 'routine' : _s(test['urgency']);
                    return Text(t('soap.plan.urgency.$u'), style: TextStyle(color: urgColor(u), fontSize: 12));
                  }),
                ]),
                if (_s(test['rationale']).isNotEmpty)
                  Text(_s(test['rationale']), style: Theme.of(context).textTheme.bodySmall),
              ]),
            ),
      // Treatments: {type, name, instruction, note?} (or a bare string).
      if (treatments is List && treatments.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text(t('soap.plan.treatments.title'), style: const TextStyle(fontWeight: FontWeight.w600)),
        for (final tr in treatments)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: tr is Map
                ? Text('• ${[_s(tr['type']), _s(tr['name']), _s(tr['instruction'])].where((x) => x.isNotEmpty).join(' — ')}')
                : Text('• ${_s(tr)}'),
          ),
      ],
      // Follow-up.
      if (_s(followUp['interval']).isNotEmpty || _s(followUp['reason']).isNotEmpty) ...[
        const SizedBox(height: 6),
        Text(t('soap.plan.followUp.title'), style: const TextStyle(fontWeight: FontWeight.w600)),
        if (_s(followUp['interval']).isNotEmpty) _kv(t('soap.plan.followUp.interval'), _s(followUp['interval'])),
        if (_s(followUp['reason']).isNotEmpty) _kv(t('soap.plan.followUp.reason'), _s(followUp['reason'])),
      ],
      if (edu.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text(t('soap.plan.patientEducation.title'), style: const TextStyle(fontWeight: FontWeight.w600)),
        for (final e in edu) Text('• $e'),
      ],
      if (referrals.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text(t('soap.plan.referrals.title'), style: const TextStyle(fontWeight: FontWeight.w600)),
        Wrap(spacing: 6, children: [for (final r in referrals) Chip(label: Text(r), visualDensity: VisualDensity.compact)]),
      ],
    ]));
  }

  Widget _reviewBar(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(children: [
          Expanded(
            child: FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Theme.of(context).extension<AppTokens>()!.statusCompleted),
              onPressed: () => _review('approved'),
              child: Text(t('soap.review.approveButton')),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: OutlinedButton(
              onPressed: () => _review('revision_needed'),
              child: Text(t('soap.review.rejectButton')),
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
            Text(title, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            body,
          ]),
        ),
      );

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: RichText(
          text: TextSpan(style: DefaultTextStyle.of(context).style, children: [
            TextSpan(text: '$k: ', style: const TextStyle(fontWeight: FontWeight.w600)),
            TextSpan(text: v),
          ]),
        ),
      );

  Widget _tagRow(BuildContext context, String label, List<String> items) {
    if (items.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
        Wrap(spacing: 6, runSpacing: 6, children: [for (final i in items) Chip(label: Text(i), visualDensity: VisualDensity.compact)]),
      ]),
    );
  }
}

class _ReviewDialog extends StatefulWidget {
  const _ReviewDialog({required this.action});
  final String action; // 'approved' | 'revision_needed'

  @override
  State<_ReviewDialog> createState() => _ReviewDialogState();
}

class _ReviewDialogState extends State<_ReviewDialog> {
  final _notes = TextEditingController();
  String? _error;

  @override
  void dispose() {
    _notes.dispose();
    super.dispose();
  }

  void _confirm() {
    final notes = _notes.text.trim();
    if (widget.action == 'revision_needed' && notes.isEmpty) {
      setState(() => _error = t('soap.review.notesRequiredError'));
      return;
    }
    Navigator.pop(context, (status: widget.action, notes: notes.isEmpty ? null : notes));
  }

  @override
  Widget build(BuildContext context) {
    final approve = widget.action == 'approved';
    return AlertDialog(
      title: Text(t(approve ? 'soap.review.approveButton' : 'soap.review.rejectButton')),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        Text(t(approve ? 'soap.review.approveDescription' : 'soap.review.rejectDescription')),
        const SizedBox(height: 8),
        TextField(
          controller: _notes,
          maxLines: 3,
          decoration: InputDecoration(
            hintText: t(approve ? 'soap.review.approveNotesPlaceholder' : 'soap.review.rejectNotesPlaceholder'),
            errorText: _error,
          ),
        ),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: Text(t('soap.common.cancel'))),
        FilledButton(onPressed: _confirm, child: Text(t('soap.common.confirm'))),
      ],
    );
  }
}
