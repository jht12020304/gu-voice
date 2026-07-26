import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';

// Language switch = navigate to the same route under a new lng (URL is the authority).
class LanguageBar extends StatelessWidget {
  const LanguageBar({super.key});

  @override
  Widget build(BuildContext context) {
    // Keep the whole URI: switching language must not drop query params (a reset-password
    // link or any future param would be silently eaten — same class of bug as TODO G6).
    final uri = GoRouterState.of(context).uri;
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      alignment: WrapAlignment.center,
      children: [
        for (final lng in supportedLanguages)
          ChoiceChip(
            selected: lng == currentLng,
            label: Text(
              t('common.language.names.$lng') +
                  (betaLanguages.contains(lng) ? ' ${t('common.language.betaTag')}' : ''),
            ),
            onSelected: (_) => context.go(
              uri.replace(path: prefixLngToPath(uri.path, lng)).toString(),
            ),
          ),
      ],
    );
  }
}
