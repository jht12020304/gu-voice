// App-wide config. Local-first: everything points at the backend on localhost.
// Override at build time with --dart-define=API_BASE=... / WS_BASE=...
class Env {
  // On Android emulator, localhost is the emulator itself — use 10.0.2.2 to reach the host.
  // ponytail: single default for dev; pass --dart-define for a device on the LAN.
  static const apiBase = String.fromEnvironment(
    'API_BASE',
    defaultValue: 'http://localhost:8000/api/v1',
  );

  static const wsBase = String.fromEnvironment(
    'WS_BASE',
    defaultValue: 'ws://localhost:8000/api/v1/ws',
  );
}
