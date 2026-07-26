import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../shared/widgets/language_bar.dart';
import '../auth/auth_notifier.dart';

// Phase-1 landing placeholder: proves auth + i18n + theme + `/:lng` routing end-to-end.
// Real role dashboards (patient home / doctor dashboard / admin) land in later phases.
class RoleHomePage extends ConsumerWidget {
  const RoleHomePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authProvider).user;
    final theme = Theme.of(context);

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
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.check_circle, size: 48, color: theme.colorScheme.primary),
            const SizedBox(height: 16),
            Text(
              user?.name ?? '',
              style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 4),
            Text('${user?.role ?? ''} · ${user?.email ?? ''}'),
            const SizedBox(height: 24),
            if (user?.isPatient ?? false)
              FilledButton.icon(
                icon: const Icon(Icons.mic),
                label: Text(t('conversation.title')),
                onPressed: () => context.go(prefixLngToPath('/patient/start', currentLng)),
              ),
            const SizedBox(height: 32),
            const LanguageBar(),
          ],
        ),
      ),
    );
  }
}
