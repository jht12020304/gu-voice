// 醫師 App（iOS）的 FCM 推播 client 邏輯。
//
// 這一層刻意**不** import firebase：所有 Firebase 呼叫都收斂在 [PushBackend] 介面後面，
// 真實實作由 `push_backend.dart` 的 conditional import 挑（native → firebase、web → no-op）。
// 兩個理由：
//   1. unit test 只餵 fake backend，完全不碰 platform channel；
//   2. web build 連 Firebase 的 Dart 程式碼都不會被編進去 —— kiosk 不該因為醫師 App 的
//      推播需求而多載一份 Firebase JS SDK（firebase_core_web 只在 `Firebase.initializeApp()`
//      被呼叫時才去 gstatic 抓 script，我們在 web 上永遠不呼叫它）。

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../data/api/case_convert.dart';
import '../../../data/api/notifications_api.dart';
import '../../../data/models/notification.dart';
import '../../../data/models/user.dart';

/// 後端 `DevicePlatform` enum（backend/app/models/enums.py）在 iOS 上的值。
const kPushPlatformIos = 'ios';

/// Firebase 與 App 邏輯之間的唯一接縫。
abstract class PushBackend {
  /// `Firebase.initializeApp()`，必須冪等（重複啟動不得拋 duplicate-app）。
  Future<void> initialize();

  /// 請求通知權限。回傳是否取得（含 provisional）。
  Future<bool> requestPermission();

  /// 取得 FCM registration token。**simulator 上沒有 APNS token 時會拋**，呼叫端必須容錯。
  Future<String?> getToken();

  /// FCM 主動輪替 token 時的通知流。
  Stream<String> get onTokenRefresh;

  /// App 在背景時使用者點推播 → data payload。
  Stream<Map<String, dynamic>> get onMessageOpenedApp;

  /// App 由推播冷啟動時的那一則（沒有則 null）。
  Future<Map<String, dynamic>?> getInitialMessage();

  /// 註冊到後端的裝置名稱（`device_name`，後端上限 200 字）。
  String? get deviceName;
}

/// 推播只在「醫師專用平台 × 醫護帳號」啟動。
///
/// 病患帳號沒有任何推播來源（後端只對 `session.doctor_id` 發），web kiosk 更不該初始化
/// Firebase。純函式，好在測試裡把兩個平台都表達出來（比照 route_guard）。
bool shouldEnablePush({required User? user, required bool doctorOnlyPlatform}) =>
    doctorOnlyPlatform && user != null && (user.isDoctor || user.isAdmin);

/// 推播 data payload → App 路由。
///
/// 對應規則的權威是 [AppNotification.route]（通知中心點擊用的是同一份），這裡只做兩件轉接：
///
/// 1. 推播 payload 是後端原樣的 snake_case（`session_id` / `alert_id` / `report_id`），
///    沒有經過 Dio 的 snakeToCamel interceptor，所以先轉一次再交給 route()。
/// 2. 只有紅旗推播帶 `type`（alert_service.py 的 notification_data）；
///    `report_ready` / `session_complete` 的 data 只有 `session_id`（+ `report_id`）
///    （notification_service.py）。少了 type，route() 會把報告推播判成 `/sessions/:id`。
///    因此有 `report_id` 就補上 `report_ready`，其餘留白讓 route() 走 sessionId 分支。
String? pushRouteFor(Map<String, dynamic> raw) {
  if (raw.isEmpty) return null;
  final data = snakeToCamel<Map>(raw);
  final declared = data['type'];
  final type = declared is String && declared.isNotEmpty
      ? declared
      : (data['reportId'] is String ? 'report_ready' : 'system');
  // 只借 route()；id/title/createdAt 在這條路上沒有意義。
  return AppNotification(id: '', type: type, title: '', createdAt: '', data: data).route();
}

typedef PushNavigate = void Function(String route);

/// 推播生命週期：啟動註冊 → token 輪替重註冊 → 點擊導頁 → 登出反註冊。
///
/// 每一步都是 best-effort：推播是附加價值，任何失敗都不得讓 App 掛掉或擋住登出。
class PushService {
  PushService({
    required PushBackend backend,
    required PushNavigate navigate,
    NotificationsApi? api,
  })  : _backend = backend,
        _navigate = navigate,
        _api = api ?? NotificationsApi();

  final PushBackend _backend;
  final PushNavigate _navigate;
  final NotificationsApi _api;

  StreamSubscription<String>? _refreshSub;
  StreamSubscription<Map<String, dynamic>>? _openedSub;

  /// 目前已成功註冊到後端的 token；登出時要 DELETE 的就是它。
  String? _registeredToken;
  bool _started = false;

  @visibleForTesting
  String? get registeredToken => _registeredToken;

  Future<void> start() async {
    if (_started) return;
    _started = true;

    try {
      await _backend.initialize();
    } catch (e) {
      // 設定檔缺失／plist 沒進 bundle 都會落在這裡。沒有推播能力就整段放棄，App 照跑。
      debugPrint('[push] Firebase 初始化失敗，推播停用：$e');
      return;
    }

    // 使用者拒絕權限也照樣往下走：token 仍然拿得到，通知中心（站內）不受影響，
    // 而且使用者之後在系統設定打開就會直接生效，不必重登。
    try {
      await _backend.requestPermission();
    } catch (e) {
      debugPrint('[push] 通知權限請求失敗：$e');
    }

    await _syncToken();

    _refreshSub = _backend.onTokenRefresh.listen(
      _register,
      onError: (Object e) => debugPrint('[push] onTokenRefresh 錯誤：$e'),
    );
    _openedSub = _backend.onMessageOpenedApp.listen(
      _handleOpened,
      onError: (Object e) => debugPrint('[push] onMessageOpenedApp 錯誤：$e'),
    );

    // 由推播冷啟動的那一則：串流不會補送，只能主動撈。
    try {
      final initial = await _backend.getInitialMessage();
      if (initial != null) _handleOpened(initial);
    } catch (e) {
      debugPrint('[push] getInitialMessage 失敗：$e');
    }
  }

  /// 停止監聽（登出／離開醫師身分）。不打後端 —— 反註冊走 [unregister]。
  void stop() {
    _refreshSub?.cancel();
    _refreshSub = null;
    _openedSub?.cancel();
    _openedSub = null;
    _started = false;
  }

  /// 登出前的反註冊。**必須在 access token 還有效時呼叫**（見 AuthNotifier.preLogoutHooks）。
  /// 失敗一律吞掉：反註冊不得擋住登出。
  Future<void> unregister() async {
    final token = _registeredToken;
    _registeredToken = null;
    if (token == null) return;
    try {
      await _api.removeFcmToken(token);
    } catch (e) {
      debugPrint('[push] token 反註冊失敗（不影響登出）：$e');
    }
  }

  Future<void> _syncToken() async {
    String? token;
    try {
      token = await _backend.getToken();
    } catch (e) {
      // simulator 幾乎必踩：沒有 APNS token 時 getToken() 直接拋
      // （`apns-token-not-set`）。這不是錯誤路徑，是模擬器的常態。
      debugPrint('[push] 取不到 FCM token（simulator 無 APNS token 屬正常）：$e');
      return;
    }
    if (token == null || token.isEmpty) return;
    await _register(token);
  }

  Future<void> _register(String token) async {
    if (token.isEmpty) return;
    try {
      await _api.registerFcmToken(
        token: token,
        platform: kPushPlatformIos,
        deviceName: _backend.deviceName,
      );
      _registeredToken = token;
    } catch (e) {
      // 網路/後端問題：下次 App 啟動或 token 輪替時會再試一次。
      debugPrint('[push] token 註冊失敗：$e');
    }
  }

  void _handleOpened(Map<String, dynamic> data) {
    final route = pushRouteFor(data);
    if (route == null) return; // 認不得的 payload：留在原地，不亂跳
    _navigate(route);
  }
}
