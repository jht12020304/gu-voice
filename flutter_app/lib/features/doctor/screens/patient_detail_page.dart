import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/patients_api.dart';
import '../../../data/models/patient.dart';
import '../../../data/models/session.dart';
import '../../../shared/format.dart';
import '../../../shared/widgets/status_badge.dart';
import '../../../shared/widgets/ui_kit.dart';

// Port of PatientDetailPage.tsx — parallel load of patient + sessions, history chips,
// delete-confirm modal. Visual pass (2026-08-22, design-taste-frontend): section
// titles moved out of their cards into GroupHeader (對齊 settings/patient-list 的寫法），
// history 標籤換成 PillTag，載入/錯誤/無場次換成骨架與有 icon 的狀態元件。
class PatientDetailPage extends StatefulWidget {
  const PatientDetailPage({super.key, required this.patientId});
  final String patientId;

  @override
  State<PatientDetailPage> createState() => _PatientDetailPageState();
}

class _PatientDetailPageState extends State<PatientDetailPage> {
  final _api = PatientsApi();
  Patient? _patient;
  List<Session> _sessions = [];
  bool _loading = true;
  bool _error = false;
  bool _deleting = false;

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([
        _api.get(widget.patientId),
        _api.getSessions(widget.patientId),
      ]);
      if (mounted) setState(() { _patient = results[0] as Patient; _sessions = results[1] as List<Session>; _loading = false; });
    } catch (_) {
      if (mounted) setState(() { _error = true; _loading = false; });
    }
  }

  Future<void> _confirmDelete() async {
    final p = _patient!;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(t('common.doctor.patient.deleteTitle')),
        content: Text(t('common.doctor.patient.deleteConfirm', args: {'name': p.name})),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(t('common.doctor.patient.cancelAction'))),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Theme.of(context).colorScheme.error),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(t('common.doctor.patient.confirmDelete')),
          ),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _deleting = true);
    try {
      await _api.delete(p.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t('common.doctor.patient.deleteSuccess'))));
      context.go(prefixLngToPath('/patients', currentLng));
    } catch (_) {
      if (mounted) {
        setState(() => _deleting = false);
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t('common.doctor.patient.deleteError'))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return Scaffold(appBar: AppBar(), body: const SkeletonList());
    if (_error) {
      return Scaffold(
        appBar: AppBar(),
        body: ErrorState(
          message: t('common.doctor.patient.loadError'),
          retryLabel: t('common.retry'),
          onRetry: _load,
        ),
      );
    }
    if (_patient == null) {
      return Scaffold(
        appBar: AppBar(),
        body: EmptyState(
          icon: Icons.person_off_outlined,
          title: t('common.doctor.patient.notFound'),
        ),
      );
    }
    final p = _patient!;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Text(t('common.doctor.patient.title')),
        actions: [
          // 醫師代病患語音問診（2026-08-22 拍板）：從這裡進的問診場次記在**本頁
          // 這位病患**名下（patientId 隨 URL 一路帶到 POST /sessions；後端只對
          // doctor/admin 放行任意 patientId）。醫師拿著裝置訪談，逐字稿/SOAP 都
          // 落在正確的病歷。
          IconButton(
            icon: const Icon(Icons.mic_none),
            tooltip: t('conversation.title'),
            onPressed: () => context.go(
              Uri(
                path: prefixLngToPath('/patient/start', currentLng),
                queryParameters: {'patientId': widget.patientId},
              ).toString(),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline),
            color: theme.colorScheme.error,
            tooltip: t('common.doctor.patient.delete'),
            onPressed: _deleting ? null : _confirmDelete,
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(children: [
                CircleAvatar(radius: 28, child: Text(p.name.isNotEmpty ? p.name.characters.first : '?')),
                const SizedBox(height: 8),
                Text(p.name.isNotEmpty ? p.name : t('common.doctor.patient.unnamed'), style: theme.textTheme.titleMedium),
                Text(p.phone ?? t('common.doctor.patient.noPhone')),
                const SizedBox(height: 12),
                _info(t('common.doctor.patient.labels.gender'), p.gender != null ? t('common.gender.${p.gender}') : '-'),
                _info(t('common.doctor.patient.labels.dateOfBirth'), p.dateOfBirth ?? '-'),
                _info(t('common.doctor.patient.labels.createdAt'), formatDateTime(p.createdAt)),
              ]),
            ),
          ),
          GroupHeader(t('common.doctor.patient.historyTitle')),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                _chips(t('common.doctor.patient.allergies'), p.allergens),
                _chips(t('common.doctor.patient.currentMedications'), p.medications),
                _chips(t('common.doctor.patient.medicalHistory'), p.conditions),
              ]),
            ),
          ),
          GroupHeader('${t('common.doctor.patient.recentSessions')} · ${t('common.doctor.patient.sessionCount', args: {'count': _sessions.length})}'),
          if (_sessions.isEmpty)
            EmptyState(
              icon: Icons.forum_outlined,
              title: t('common.doctor.patient.noSessions'),
              message: t('common.doctor.patient.noSessionsHint'),
            )
          else
            for (final s in _sessions) _sessionRow(context, s),
        ],
      ),
    );
  }

  // 標籤在左（inkSecondary）、值靠右（inkHeading 加粗），對齊 doctor_settings_page
  // 的 row() 寫法——這裡是同一種「小型資訊列」，不必再各自發明樣式。
  Widget _info(String label, String value) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(label, style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: tk.inkSecondary)),
        Text(value,
            style: Theme.of(context)
                .textTheme
                .bodyMedium
                ?.copyWith(fontWeight: FontWeight.w600, color: tk.inkHeading)),
      ]),
    );
  }

  Widget _chips(String label, List<String> items) {
    final primary = Theme.of(context).colorScheme.primary;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 4),
        items.isEmpty
            ? Text(t('common.doctor.patient.notRecorded'))
            : Wrap(spacing: 6, runSpacing: 6, children: [for (final i in items) PillTag(i, color: primary)]),
      ]),
    );
  }

  Widget _sessionRow(BuildContext context, Session s) => Card(
        margin: const EdgeInsets.symmetric(vertical: 4),
        child: ListTile(
          onTap: () => context.go(prefixLngToPath('/sessions/${s.id}', currentLng)),
          title: Text(s.chiefComplaintText ?? t('common.doctor.patient.noComplaint')),
          subtitle: Text(formatDateTime(s.createdAt)),
          trailing: StatusBadge(s.status),
        ),
      );
}
