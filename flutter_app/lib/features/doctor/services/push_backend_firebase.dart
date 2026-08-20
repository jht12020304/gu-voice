// 原生平台的 PushBackend：唯一 import firebase 的檔案。
//
// iOS 設定來自 bundle 內的 GoogleService-Info.plist（ios/Runner/），所以
// `Firebase.initializeApp()` 不需要 DefaultFirebaseOptions —— 沒有 firebase_options.dart
// 要產、也沒有第二份設定要跟 plist 對齊。APNs token 交給 firebase_messaging 的
// method swizzling 處理，AppDelegate 維持乾淨。

import 'dart:async';
import 'dart:io';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import 'push_service.dart';

PushBackend createPushBackend() => FirebasePushBackend();

class FirebasePushBackend implements PushBackend {
  FirebaseMessaging get _messaging => FirebaseMessaging.instance;

  @override
  Future<void> initialize() async {
    // 冪等：重複 initializeApp 會拋 `duplicate-app`。App 生命週期內可能被啟動多次
    // （登出再登入、或熱重載），所以先看 apps 清單。
    if (Firebase.apps.isEmpty) {
      await Firebase.initializeApp();
    }
  }

  @override
  Future<bool> requestPermission() async {
    final settings = await _messaging.requestPermission();
    final status = settings.authorizationStatus;
    return status == AuthorizationStatus.authorized ||
        status == AuthorizationStatus.provisional;
  }

  @override
  Future<String?> getToken() => _messaging.getToken();

  @override
  Stream<String> get onTokenRefresh => _messaging.onTokenRefresh;

  @override
  Stream<Map<String, dynamic>> get onMessageOpenedApp =>
      FirebaseMessaging.onMessageOpenedApp.map((m) => m.data);

  @override
  Future<Map<String, dynamic>?> getInitialMessage() async =>
      (await _messaging.getInitialMessage())?.data;

  @override
  String? get deviceName {
    // device_info_plus 只為了一個字串不值得多一個依賴。iOS 的 localHostname 就是裝置
    // 名稱（simulator 上是宿主 Mac 的），足以在後端的裝置清單裡分辨。
    try {
      final host = Platform.localHostname.trim();
      final name = host.isEmpty ? Platform.operatingSystem : host;
      return name.length > 200 ? name.substring(0, 200) : name;
    } catch (_) {
      return null;
    }
  }
}
