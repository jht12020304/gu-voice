import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../tool/prepare_vercel_output.dart';

void main() {
  test('Vercel output supports SPA routes and microphone access', () {
    final config = buildVercelConfig();
    final routes = config['routes']! as List<Object?>;
    final securityHeaders =
        (routes.first! as Map<String, Object>)['headers']!
            as Map<String, String>;

    expect(config['version'], 3);
    expect(
      routes.whereType<Map<Object?, Object?>>().any(
        (route) => route['handle'] == 'filesystem',
      ),
      isTrue,
    );
    expect((routes.last! as Map<String, Object>)['dest'], '/index.html');
    expect(securityHeaders['X-Frame-Options'], 'DENY');
    expect(
      securityHeaders['Permissions-Policy'],
      contains('microphone=(self)'),
    );
    expect(
      securityHeaders['Content-Security-Policy'],
      contains('wss://*.railway.app'),
    );
  });

  test('web bootstrap does not register a service worker', () {
    final bootstrap = File('web/flutter_bootstrap.js').readAsStringSync();

    expect(bootstrap, contains('_flutter.loader.load();'));
    expect(bootstrap, isNot(contains('_flutter.loader.load({')));
  });
}
