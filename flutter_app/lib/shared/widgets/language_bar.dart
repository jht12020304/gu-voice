import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';

// Language switch = navigate to the same route under a new lng (URL is the authority).
class LanguageBar extends StatelessWidget {
  const LanguageBar({super.key});

  @override
  Widget build(BuildContext context) {
    final path = GoRouterState.of(context).uri.path;
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
            onSelected: (_) => context.go(prefixLngToPath(path, lng)),
          ),
      ],
    );
  }
}
