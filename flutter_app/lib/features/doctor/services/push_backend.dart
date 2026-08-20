// 依平台挑 PushBackend 實作。比照 lib/core/router/url_strategy.dart、
// lib/shared/pdf_download.dart 的既有寫法。
//
// `dart.library.io` 為真＝原生（含 iOS）；web 走 stub，Firebase 的 Dart 程式碼
// 連編都不會編進 web bundle。真正「要不要啟動」的判斷在 shouldEnablePush()。
export 'push_backend_stub.dart' if (dart.library.io) 'push_backend_firebase.dart';
