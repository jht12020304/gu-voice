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

  /// Optional credentials for local/e2e login convenience.
  ///
  /// The login page only shows its fill button when both values are supplied
  /// through `--dart-define`. Credentials therefore never need to live in the
  /// repository. A public web build may intentionally supply a dedicated,
  /// patient-only test account; never use a doctor or administrator account.
  static const e2eEmail = String.fromEnvironment('E2E_EMAIL');
  static const e2ePassword = String.fromEnvironment('E2E_PASSWORD');

  static const hasE2eCredentials = e2eEmail != '' && e2ePassword != '';

  /// Kiosk idle auto-logout, in seconds. `0` disables it.
  ///
  /// 180s matches the value the React `KioskIdleGuard` documents as the kiosk setting.
  /// The window is a trade-off: shorter cuts patients off while they are filling in the
  /// intake form, longer defeats the point — the next patient walks up to the previous
  /// one's name and chief complaint still on screen.
  ///
  /// Only applies to `patient` sessions and never on `/conversation` (see
  /// KioskIdleGuard for why). Override with
  /// `--dart-define=KIOSK_IDLE_TIMEOUT_SECONDS=<n>`.
  static const kioskIdleTimeoutSeconds = int.fromEnvironment(
    'KIOSK_IDLE_TIMEOUT_SECONDS',
    defaultValue: 180,
  );
}
