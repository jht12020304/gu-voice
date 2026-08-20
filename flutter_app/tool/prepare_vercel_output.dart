import 'dart:convert';
import 'dart:io';

Map<String, Object> buildVercelConfig() => {
  'version': 3,
  'routes': [
    {
      'src': '/.*',
      'headers': {
        'X-Frame-Options': 'DENY',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(self), geolocation=()',
        'Content-Security-Policy':
            "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; img-src 'self' data: blob: https:; connect-src 'self' https://*.railway.app wss://*.railway.app https://fonts.googleapis.com https://fonts.gstatic.com; media-src 'self' data: blob:; worker-src 'self' blob:; frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'self'",
      },
      'continue': true,
    },
    {
      'src': '/canvaskit/.*',
      'headers': {'Cache-Control': 'public, max-age=31536000, immutable'},
      'continue': true,
    },
    {
      'src': '/assets/fonts/.*',
      'headers': {'Cache-Control': 'public, max-age=31536000, immutable'},
      'continue': true,
    },
    {
      'src': '/assets/.*',
      'headers': {'Cache-Control': 'public, max-age=3600, must-revalidate'},
      'continue': true,
    },
    {
      'src':
          '/(index.html|flutter_bootstrap.js|flutter.js|main.dart.js|manifest.json|version.json|flutter_service_worker.js)',
      'headers': {'Cache-Control': 'no-cache, no-store, must-revalidate'},
      'continue': true,
    },
    {'handle': 'filesystem'},
    {
      'src': '/.*',
      'dest': '/index.html',
      'headers': {'Cache-Control': 'no-cache, no-store, must-revalidate'},
    },
  ],
};

void main(List<String> args) {
  if (args.length != 1) {
    stderr.writeln(
      'usage: dart run tool/prepare_vercel_output.dart <config.json>',
    );
    exitCode = 64;
    return;
  }

  final configFile = File(args.single);
  configFile.parent.createSync(recursive: true);
  configFile.writeAsStringSync(
    const JsonEncoder.withIndent('  ').convert(buildVercelConfig()),
  );
  configFile.writeAsStringSync('\n', mode: FileMode.append);
}
