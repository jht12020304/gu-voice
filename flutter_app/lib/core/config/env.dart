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

  /// 測試建置的「帶入醫師帳密」鈕（2026-08-22 使用者拍板）。
  ///
  /// ⚠️ 與病患那組不同，這組**破例**內嵌醫師憑證——僅限 TestFlight 內測建置，
  /// 憑證是專用的「測試醫師（勿用真實資料）」帳號，且醫師登入後讀得到全部病歷
  /// （後端無 tenant 隔離）。**公開發佈的建置絕對不得帶這兩個 define**；
  /// `tool/build_vercel_output.sh` 對 web 公開版仍會拒絕任何 E2E 憑證。
  static const e2eDoctorEmail = String.fromEnvironment('E2E_DOCTOR_EMAIL');
  static const e2eDoctorPassword = String.fromEnvironment('E2E_DOCTOR_PASSWORD');

  static const hasE2eDoctorCredentials = e2eDoctorEmail != '' && e2eDoctorPassword != '';

  /// 冷啟動自動登入（2026-08-22 拆成獨立開關）。
  ///
  /// 帶入鈕與自動登入本來共用 E2E_EMAIL 的存在與否，結果「登入頁選角色」與
  /// 「冷啟動直進病患首頁」互相打架——自動登入一開，登入頁根本看不到。
  /// 現在：帶入鈕只看憑證存在；自動登入要**額外**帶 --dart-define=E2E_AUTO_LOGIN=true。
  static const e2eAutoLogin = bool.fromEnvironment('E2E_AUTO_LOGIN');

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
