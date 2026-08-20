import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/i18n/loc.dart';
import '../../core/theme/app_tokens.dart';
import '../auth/auth_notifier.dart';

// 醫師專用 App（原生 iOS）上，病患帳號唯一到得了的一頁。
// 這頁不含任何醫囑判斷，只做導引：問診在現場 kiosk 做，這支 App 是醫護看報告/通知用的。
class PatientUnsupportedPage extends ConsumerWidget {
  const PatientUnsupportedPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final tk = theme.extension<AppTokens>()!;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircleAvatar(
                      radius: 32,
                      backgroundColor: theme.colorScheme.primary.withValues(alpha: 0.12),
                      child: Icon(Icons.medical_information_outlined,
                          size: 34, color: theme.colorScheme.primary),
                    ),
                    const SizedBox(height: 24),
                    Text(
                      t('common.patientUnsupported.title'),
                      textAlign: TextAlign.center,
                      style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 16),
                    Text(
                      t('common.patientUnsupported.message'),
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodyLarge,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      t('common.patientUnsupported.kioskHint'),
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodyMedium?.copyWith(color: tk.inkSecondary),
                    ),
                    const SizedBox(height: 32),
                    FilledButton.icon(
                      icon: const Icon(Icons.logout),
                      label: Text(t('common.patientUnsupported.logoutAction')),
                      onPressed: () => ref.read(authProvider.notifier).logout(),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
