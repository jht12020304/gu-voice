import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/router/app_router.dart';
import 'core/router/lng.dart';
import 'core/theme/app_theme.dart';

Locale _toLocale(String tag) {
  final parts = tag.split('-');
  return Locale(parts[0], parts.length > 1 ? parts[1] : null);
}

class App extends ConsumerWidget {
  const App({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    // Rebuild when currentLng changes so Material/Cupertino localizations (DatePicker,
    // tooltips) follow the URL language authority. App text is driven by our own t();
    // per-page t() rebuild is handled by _lngKeyed() in app_router.
    return ValueListenableBuilder<String>(
      valueListenable: currentLngNotifier,
      builder: (context, lng, _) => MaterialApp.router(
        title: 'GU Voice',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        darkTheme: AppTheme.dark,
        themeMode: ThemeMode.system,
        routerConfig: router,
        locale: _toLocale(lng),
        supportedLocales: supportedLanguages.map(_toLocale),
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
      ),
    );
  }
}
