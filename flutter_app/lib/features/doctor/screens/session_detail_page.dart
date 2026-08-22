import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/reports_api.dart';
import '../../../data/api/sessions_api.dart';
import '../../../data/models/session.dart';
import '../../../data/models/soap_report.dart';
import '../../../shared/format.dart';
import '../../../shared/widgets/status_badge.dart';
import '../../../shared/widgets/ui_kit.dart';
import '../../auth/auth_notifier.dart';

// Port of SessionDetailPage.tsx — status-gated actions (assign / complete / cancel /
// generate report) + read-only transcript ordered by sequenceNumber.
/// Whether the "generate report" action should be offered.
///
/// Extracted so the retry rule is testable. The old rule was "session completed AND no
/// report row exists", which made a **failed** generation a dead end: the row existed,
/// so the button vanished and nothing could re-trigger it (TODO §G medium).
///
/// `generating` deliberately does NOT offer the button — double-dispatching a queued
/// Celery task risks duplicate reports; the page shows an in-flight line instead.
bool canGenerateSoapReport({
  required String sessionStatus,
  required String? reportStatus,
}) {
  if (sessionStatus != 'completed') return false;
  return reportStatus == null || reportStatus == 'failed';
}

class SessionDetailPage extends ConsumerStatefulWidget {
  const SessionDetailPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  ConsumerState<SessionDetailPage> createState() => _SessionDetailPageState();
}

class _SessionDetailPageState extends ConsumerState<SessionDetailPage> {
  final _api = SessionsApi();
  Session? _session;
  List<ConversationTurn> _turns = [];
  /// null = 沒有報告；否則為 `generating` | `generated` | `failed`。
  String? _reportStatus;
  bool _loading = true;
  String? _error;
  bool _assigning = false;
  bool _generating = false;

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final results = await Future.wait([
        _api.getSession(widget.sessionId),
        _api.getConversations(widget.sessionId),
      ]);
      final session = results[0] as Session;
      final turns = results[1] as List<ConversationTurn>;
      // Keep the report's STATUS, not just whether one exists. `_hasReport` alone hid the
      // generate button whenever any row was present — including a `failed` one — so a
      // failed generation was a dead end with no way to retry (TODO §G medium).
      String? reportStatus;
      // `aborted_red_flag` is a terminal status that ALSO dispatches SOAP generation, so it
      // needs the same lookup as `completed` — gating on `completed` alone hid「查看報告」on
      // every red-flag session. `cancelled` never dispatches SOAP, so it is not queried.
      if (session.status == 'completed' || session.status == 'aborted_red_flag') {
        try {
          reportStatus = (await ReportsApi().getReportBySession(widget.sessionId))?.status;
        } catch (_) {
          reportStatus = null;
        }
      }
      if (mounted) {
        setState(() {
          _session = session;
          _turns = turns;
          _reportStatus = reportStatus;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() { _error = t('session.doctor.detail.loadError'); _loading = false; });
    }
  }

  void _toast(String msg) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));

  Future<void> _assignToMe() async {
    final user = ref.read(authProvider).user;
    if (_session == null || user == null) return;
    setState(() => _assigning = true);
    try {
      final updated = await _api.assignDoctor(_session!.id, user.id);
      if (!mounted) return;
      setState(() { _session = updated; _assigning = false; });
      _toast(t('session.doctor.detail.assignSuccess'));
    } catch (_) {
      if (mounted) setState(() => _assigning = false);
      _toast(t('session.doctor.detail.assignError'));
    }
  }

  Future<void> _changeStatus(String status) async {
    if (_session == null) return;
    Navigator.of(context).pop(); // close modal
    try {
      final updated = await _api.updateStatus(_session!.id, status);
      if (!mounted) return;
      setState(() => _session = updated);
      _toast(t(status == 'completed'
          ? 'session.doctor.detail.statusCompletedSuccess'
          : 'session.doctor.detail.statusCancelledSuccess'));
    } catch (_) {
      _toast(t('session.doctor.detail.statusUpdateError'));
    }
  }

  Future<void> _generateReport() async {
    if (_session == null) return;
    setState(() => _generating = true);
    try {
      await ReportsApi().generateReport(_session!.id);
      if (!mounted) return;
      setState(() { _generating = false; _reportStatus = 'generating'; });
      _toast(t('session.doctor.detail.generateReportSuccess'));
      // ponytail: doctor SOAP report page is Phase 5 — no /reports/:id route yet to open.
    } catch (_) {
      if (mounted) setState(() => _generating = false);
      _toast(t('session.doctor.detail.generateReportError'));
    }
  }

  void _confirmStatus(String status) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(t(status == 'completed'
            ? 'session.doctor.detail.markCompletedTitle'
            : 'session.doctor.detail.cancelSessionTitle')),
        content: Text(t(status == 'completed'
            ? 'session.doctor.detail.markCompletedConfirm'
            : 'session.doctor.detail.cancelSessionConfirm')),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(), child: Text(t('session.doctor.detail.cancelAction'))),
          FilledButton(onPressed: () => _changeStatus(status), child: Text(t('session.doctor.detail.confirm'))),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return Scaffold(appBar: AppBar(), body: const SkeletonList());
    if (_error != null || _session == null) {
      return Scaffold(
        appBar: AppBar(),
        body: ErrorState(
          message: _error ?? t('session.doctor.detail.notFound'),
          retryLabel: t('common.retry'),
          onRetry: () => _load(),
        ),
      );
    }
    final s = _session!;
    final user = ref.watch(authProvider).user;
    final tk = Theme.of(context).extension<AppTokens>()!;
    final isAssignedToMe = user != null && s.doctorId == user.id;
    final canCompleteOrCancel = s.status == 'waiting' || s.status == 'in_progress';
    final canGenerate = canGenerateSoapReport(
      sessionStatus: s.status,
      reportStatus: _reportStatus,
    );

    return Scaffold(
      appBar: AppBar(
        title: Text(t('session.doctor.detail.title')),
        actions: [StatusBadge(s.status), const SizedBox(width: 12)],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _infoGrid(context, s),
          if (s.redFlag) ...[
            const SizedBox(height: 12),
            Card(
              color: tk.alertCriticalBg,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(t('session.doctor.detail.redFlagTitle'),
                      style: TextStyle(color: tk.alertCritical, fontWeight: FontWeight.w700)),
                  if (s.redFlagReason != null) Text(s.redFlagReason!, style: TextStyle(color: tk.alertCritical)),
                ]),
              ),
            ),
          ],
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(t('session.doctor.detail.actionsTitle'), style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: 4),
                Text(isAssignedToMe
                    ? t('session.doctor.detail.assignedToMe')
                    : t('session.doctor.detail.actionsHint')),
                const SizedBox(height: 12),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  if (!isAssignedToMe)
                    FilledButton(
                      onPressed: (_assigning || user == null) ? null : _assignToMe,
                      child: Text(t(_assigning ? 'session.doctor.detail.assigning' : 'session.doctor.detail.assignToMe')),
                    ),
                  if (canCompleteOrCancel)
                    FilledButton(
                      onPressed: () => _confirmStatus('completed'),
                      child: Text(t('session.doctor.detail.markCompleted')),
                    ),
                  if (canCompleteOrCancel)
                    OutlinedButton(
                      onPressed: () => _confirmStatus('cancelled'),
                      child: Text(t('session.doctor.detail.cancelSession')),
                    ),
                  if (canGenerate)
                    FilledButton(
                      onPressed: _generating ? null : _generateReport,
                      child: Text(t(_generating ? 'session.doctor.detail.generatingReport' : 'session.doctor.detail.generateReport')),
                    ),
                  OutlinedButton(
                    onPressed: () => context.go(prefixLngToPath('/conversation/${s.id}', currentLng), extra: s),
                    child: Text(t('session.doctor.detail.enterConversation')),
                  ),
                  // Only a finished report is worth opening; `generating`/`failed` would
                  // land the doctor on an empty page.
                  if (_reportStatus == 'generated')
                    OutlinedButton(
                      onPressed: () => context.go(prefixLngToPath('/reports/${s.id}', currentLng)),
                      child: Text(t('session.doctor.detail.viewReport')),
                    ),
                ]),
                // Make an in-flight generation visible. Without this the doctor sees no
                // button and no explanation — indistinguishable from "nothing happened".
                if (_reportStatus == 'generating')
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(t('session.doctor.detail.generatingReport'),
                        style: Theme.of(context).textTheme.bodySmall),
                  ),
              ]),
            ),
          ),
          GroupHeader(t('session.doctor.detail.conversationsTitle')),
          if (_turns.isEmpty)
            EmptyState(
              icon: Icons.chat_bubble_outline,
              title: t('session.doctor.detail.conversationsEmpty'),
            )
          else
            for (final c in _turns) _bubble(context, c),
        ],
      ),
    );
  }

  Widget _infoGrid(BuildContext context, Session s) {
    Widget cell(String label, String value) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.bodySmall),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
        ]);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Wrap(spacing: 24, runSpacing: 12, children: [
          cell(t('session.doctor.detail.infoChiefComplaint'), s.chiefComplaintText ?? t('session.doctor.detail.infoChiefComplaintEmpty')),
          cell(t('session.doctor.detail.infoLanguage'), s.language),
          cell(t('session.doctor.detail.infoStartedAt'), s.startedAt != null ? formatDateTime(s.startedAt) : '-'),
          cell(t('session.doctor.detail.infoDuration'), s.durationSeconds != null ? '${durationMinutes(s.durationSeconds)} min' : '-'),
        ]),
      ),
    );
  }

  Widget _bubble(BuildContext context, ConversationTurn c) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final isPatient = c.role == 'patient';
    final isSystem = c.role == 'system';
    final align = isSystem ? Alignment.center : (isPatient ? Alignment.centerRight : Alignment.centerLeft);
    final bg = isSystem ? tk.chatBg : (isPatient ? tk.chatPatientBg : tk.chatAiBg);
    final roleLabel = isPatient ? t('common.roles.patient') : (isSystem ? t('common.roles.system') : t('common.roles.assistant'));
    return Align(
      alignment: align,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(16)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(roleLabel, style: Theme.of(context).textTheme.labelSmall),
          const SizedBox(height: 2),
          Text(c.contentText),
        ]),
      ),
    );
  }
}
