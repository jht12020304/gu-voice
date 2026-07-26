import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/i18n/locales_loader.dart';
import 'data/api/dio_client.dart';
import 'features/auth/auth_notifier.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  ApiClient.instance.init();
  await Locales.loadAll();

  final container = ProviderContainer();
  ApiClient.instance.onAuthCleared =
      () => container.read(authProvider.notifier).forceLoggedOut();
  await container.read(authProvider.notifier).bootstrap();

  runApp(UncontrolledProviderScope(container: container, child: const App()));
}
