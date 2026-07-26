import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/i18n/locales_loader.dart';
import 'core/router/url_strategy.dart';
import 'data/api/dio_client.dart';
import 'features/auth/auth_notifier.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Web only: without path URL strategy Flutter serves routes behind a `#` fragment,
  // so `/vi-VN/patient` puts the lng segment OUTSIDE what the router parses — the URL
  // stops being the language authority and every existing deep link (password-reset
  // mail, kiosk bookmarks) loses its language (TODO G5). No-op on native.
  usePathUrlStrategyIfWeb();
  ApiClient.instance.init();
  await Locales.loadAll();

  final container = ProviderContainer();
  ApiClient.instance.onAuthCleared =
      () => container.read(authProvider.notifier).forceLoggedOut();
  await container.read(authProvider.notifier).bootstrap();

  runApp(UncontrolledProviderScope(container: container, child: const App()));
}
