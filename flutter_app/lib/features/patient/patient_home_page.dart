import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../data/api/sessions_api.dart';
import '../../data/models/session.dart';
import '../../shared/widgets/language_bar.dart';
import '../../shared/widgets/ui_kit.dart';
import '../auth/auth_notifier.dart';
import 'patient_session_tile.dart';

// Port of PatientHomePage.tsx: greeting + start-consultation CTA + recent 5 sessions.
class PatientHomePage extends ConsumerStatefulWidget {
  const PatientHomePage({super.key});

  @override
  ConsumerState<PatientHomePage> createState() => _PatientHomePageState();
}

class _PatientHomePageState extends ConsumerState<PatientHomePage> {
  List<Session> _recent = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  Future<void> _load() async {
    final user = ref.read(authProvider).user;
    try {
      final list = await SessionsApi().getSessions(limit: 5, patientId: user?.id);
      if (mounted) setState(() { _recent = list; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false); // silent: show empty state
    }
  }

  String _greeting() {
    final h = DateTime.now().hour;
    final key = h < 12 ? 'greetingMorning' : (h < 18 ? 'greetingAfternoon' : 'greetingEvening');
    return t('common.patient.home.$key');
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authProvider).user;
    final theme = Theme.of(context);
    final name = (user?.name.isNotEmpty ?? false) ? user!.name : t('common.patient.home.greetingFallback');

    return Scaffold(
      appBar: AppBar(
        title: Text(t('common.appTitle')),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: t('common.header.logout'),
            onPressed: () => ref.read(authProvider.notifier).logout(),
          ),
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text('${_greeting()}，$name',
                  style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              Text(t('common.patient.home.subtitle'), style: theme.textTheme.bodyMedium),
              const SizedBox(height: 24),
              _startCard(context),
              const SizedBox(height: 32),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  GroupHeader(t('common.patient.home.recent')),
                  if (_recent.isNotEmpty)
                    TextButton(
                      onPressed: () => context.go(prefixLngToPath('/patient/history', currentLng)),
                      child: Text(t('common.patient.home.viewAll')),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              if (_loading)
                const SizedBox(height: 220, child: SkeletonList(rows: 3))
              else if (_recent.isEmpty)
                _empty(context)
              else
                for (final s in _recent) PatientSessionTile(s, durationKey: 'common.patient.home.durationMinutes'),
              const SizedBox(height: 32),
              const LanguageBar(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _startCard(BuildContext context) {
    final theme = Theme.of(context);
    return InkWell(
      onTap: () => context.go(prefixLngToPath('/patient/start', currentLng)),
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: theme.colorScheme.primary,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(t('common.patient.home.startEyebrow').toUpperCase(),
                style: const TextStyle(color: Colors.white70, letterSpacing: 1.2, fontSize: 12)),
            const SizedBox(height: 8),
            Text(t('common.patient.home.startTitle'),
                style: theme.textTheme.titleLarge?.copyWith(color: Colors.white, fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(t('common.patient.home.startSubtitle'), style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                Text(t('common.patient.home.startCta'),
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
                const SizedBox(width: 4),
                const Icon(Icons.arrow_forward, color: Colors.white, size: 18),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _empty(BuildContext context) {
    return EmptyState(
      icon: Icons.forum_outlined,
      title: t('common.patient.home.empty'),
      message: t('common.patient.home.emptyHint'),
    );
  }

}
