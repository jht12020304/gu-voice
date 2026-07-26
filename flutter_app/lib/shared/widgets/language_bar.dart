import 'package:flutter/material.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import 'language_action.dart' show switchLanguage;

// Language switch = navigate to the same route under a new lng (URL is the authority).
// 實際的切換流程（含問診中先收場次的守衛）在 language_action.dart 的 switchLanguage，
// 兩個入口共用同一條路徑，才不會有一個有守衛、另一個沒有。
class LanguageBar extends StatelessWidget {
  const LanguageBar({super.key});

  @override
  Widget build(BuildContext context) {
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
            // 路由狀態在「點下去」時才讀，不在 build 讀：在 build 讀會讓這個 widget
            // 在沒有 GoRouter 祖先的地方直接爆掉（LanguageAction 的註解記過同一個坑）。
            // 順帶保留整段 URI，切語言不會吃掉 query params（TODO G6）。
            onSelected: (_) => switchLanguage(context, lng),
          ),
      ],
    );
  }
}
