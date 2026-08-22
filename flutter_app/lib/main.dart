import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/error_boundary.dart';
import 'core/i18n/locales_loader.dart';
import 'core/router/lng.dart';
import 'core/router/url_strategy.dart';
import 'data/api/dio_client.dart';
import 'features/auth/auth_notifier.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // First thing after the binding: everything below can throw, and until this is
  // installed a throw is a blank screen with no log (docs/TODO.md §V7).
  installErrorBoundary();
  // Web only: without path URL strategy Flutter serves routes behind a `#` fragment,
  // so `/vi-VN/patient` puts the lng segment OUTSIDE what the router parses — the URL
  // stops being the language authority and every existing deep link (password-reset
  // mail, kiosk bookmarks) loses its language (TODO G5). No-op on native.
  usePathUrlStrategyIfWeb();
  ApiClient.instance.init();

  // Resolve the language the first frame will render in the same way the router's
  // redirect will, then load only that language and whatever it falls back through.
  // Loading all 5 up front cost 50 sequential rootBundle round trips plus 50
  // json.decode calls on the main isolate, all of it before anything could paint.
  final seed = bootLanguage();
  setCurrentLng(seed);
  try {
    await Locales.loadForBoot(seed);
  } catch (e) {
    // Carry on with an empty string table rather than never reaching runApp(). `t()`
    // renders the raw key when a lookup misses, so the app comes up looking wrong but
    // navigable — and the error boundary has already logged why. Dying here instead
    // would be indistinguishable from the launch hang this whole boot path exists to
    // remove.
    debugPrint('[gu-voice:boot] locale load failed for $seed: $e');
  }

  final container = ProviderContainer();
  ApiClient.instance.onAuthCleared =
      () => container.read(authProvider.notifier).forceLoggedOut();

  // Deliberately NOT awaited. bootstrap() ends in getMe(), a round trip to Railway, and
  // until 2026-08-22 runApp() waited for it — so a cold launch on a slow network showed
  // the iOS launch image and then nothing at all, for as long as that call took. The app
  // now paints on the next frame; BootGate covers the tree until `booted` flips, and
  // App only builds the router once it has (see the comment on App._routed — a route
  // built before the token loads would 401 against bootstrap's own request).
  unawaited(container.read(authProvider.notifier).bootstrap());

  runApp(UncontrolledProviderScope(container: container, child: const App()));

  // The remaining languages, off the critical path.
  //
  // After the first frame AND after a further pause: on web each namespace is its own
  // HTTP GET, so warming four languages is 40 requests, and starting them the instant
  // the first frame lands puts them in the same window as the patient's first tap.
  // Nothing waits on this — `switchLanguage` awaits `Locales.ensure` for the language it
  // is switching to, so a switch during the pause is correct, just not instant.
  SchedulerBinding.instance.addPostFrameCallback((_) {
    unawaited(Future.delayed(const Duration(seconds: 2), Locales.warmRemaining));
  });
}
