import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/router/app_router.dart';
import 'core/router/lng.dart';
import 'core/theme/app_theme.dart';
import 'features/auth/auth_notifier.dart';
import 'features/auth/boot_gate.dart';
import 'features/doctor/doctor_alert_watcher.dart';
import 'features/doctor/doctor_push_watcher.dart';
import 'features/patient/kiosk_idle_guard.dart';
import 'features/voice/state/settings_notifier.dart';

Locale _toLocale(String tag) {
  final parts = tag.split('-');
  return Locale(parts[0], parts.length > 1 ? parts[1] : null);
}

class App extends ConsumerWidget {
  const App({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // `bootOffline` counts as not-yet-booted for this decision. It means boot reached
    // the network and failed while stored tokens are still present: the router would
    // read `isAuthenticated == false`, redirect to /login, and ask a doctor whose
    // session is fine to type a password because the wifi blinked. BootGate offers a
    // retry instead. (Caught by boot_gate_test — the first version of this gated on
    // `booted` alone, which made the retry screen unreachable.)
    final showBootGate = ref.watch(
      authProvider.select((s) => !s.booted || s.bootOffline),
    );
    // Rebuild when currentLng changes so Material/Cupertino localizations (DatePicker,
    // tooltips) follow the URL language authority. App text is driven by our own t();
    // per-page t() rebuild is handled by _lngKeyed() in app_router.
    return ValueListenableBuilder<String>(
      valueListenable: currentLngNotifier,
      builder: (context, lng, _) => showBootGate
          ? _shell(ref, lng, home: const BootGate())
          : _routed(ref, lng),
    );
  }

  // Same MaterialApp configuration for both branches — theme, locale and delegates are
  // identical, so flipping `booted` swaps only what is below the app, not the app's look.
  MaterialApp _shell(WidgetRef ref, String lng, {required Widget home}) => MaterialApp(
        title: 'GU Voice',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        darkTheme: AppTheme.dark,
        themeMode: ref.watch(settingsProvider.select((v) => v.themeMode)),
        locale: _toLocale(lng),
        supportedLocales: supportedLanguages.map(_toLocale),
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: home,
      );

  // `routerProvider` is only read on this branch, so GoRouter — and therefore every
  // route's builder — is not constructed until boot has resolved. That ordering is
  // load-bearing, not cosmetic: bootstrap() is no longer awaited before runApp(), and a
  // deep-linked page building early would fire its API calls with no access token yet,
  // take a 401, and burn the refresh token racing bootstrap's own getMe().
  Widget _routed(WidgetRef ref, String lng) {
    final router = ref.watch(routerProvider);
    return MaterialApp.router(
      title: 'GU Voice',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      // Driven by the doctor settings page; defaults to system.
      themeMode: ref.watch(settingsProvider.select((v) => v.themeMode)),
      routerConfig: router,
      // Above the Navigator but below MaterialApp, so ScaffoldMessenger is in scope
      // and the red-flag toast survives route changes (TODO G12).
      builder: (context, child) => KioskIdleGuard(
        child: DoctorAlertWatcher(
          child: DoctorPushWatcher(child: child ?? const SizedBox.shrink()),
        ),
      ),
      locale: _toLocale(lng),
      supportedLocales: supportedLanguages.map(_toLocale),
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
    );
  }
}
