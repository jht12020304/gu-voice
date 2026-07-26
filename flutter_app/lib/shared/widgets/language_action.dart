import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';

/// Compact language switcher for an `AppBar`'s `actions`.
///
/// `LanguageBar` (the chip row) only appeared on 4 screens, so a patient who ended up in
/// the wrong language anywhere else had no way to change it (TODO §G medium). This is the
/// same authority — navigate to the current URI under a new lng, whole URI preserved so
/// query params survive.
///
/// ⚠️ Deliberately NOT added to `/conversation`: switching language mid-consultation needs
/// the in-progress-session guard (`POST /sessions/{id}/end-for-language-switch`), which the
/// backend does not have yet. Adding it there would leave orphaned `in_progress` sessions.
class LanguageAction extends StatelessWidget {
  const LanguageAction({super.key});

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<String>(
      icon: const Icon(Icons.language),
      tooltip: t('common.language.names.$currentLng'),
      // Router state is read at TAP time, not during build. Reading it in build makes the
      // widget unusable anywhere without a GoRouter ancestor — which broke the intake
      // widget tests, and is the same shape as the G11 crash
      // (`GoRouterState.of` above the Navigator). Same lesson: read it where it is needed.
      onSelected: (lng) {
        final uri = GoRouterState.of(context).uri;
        context.go(uri.replace(path: prefixLngToPath(uri.path, lng)).toString());
      },
      itemBuilder: (context) => [
        for (final lng in supportedLanguages)
          PopupMenuItem(
            value: lng,
            child: Row(children: [
              if (lng == currentLng) ...[
                const Icon(Icons.check, size: 16),
                const SizedBox(width: 6),
              ],
              Text(t('common.language.names.$lng') +
                  (betaLanguages.contains(lng) ? ' ${t('common.language.betaTag')}' : '')),
            ]),
          ),
      ],
    );
  }
}
