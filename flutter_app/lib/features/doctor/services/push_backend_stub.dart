// web（與任何沒有 dart:io 的目標）的 PushBackend：整段 no-op。
//
// 正常情況下不會被建出來 —— shouldEnablePush() 在非 iOS 上就回 false。留一個安靜的
// no-op 而不是 throw，是為了讓「萬一被建出來」的代價是沒有推播，而不是 kiosk 白畫面。

import 'dart:async';

import 'push_service.dart';

PushBackend createPushBackend() => const NoopPushBackend();

class NoopPushBackend implements PushBackend {
  const NoopPushBackend();

  @override
  Future<void> initialize() async {}

  @override
  Future<bool> requestPermission() async => false;

  @override
  Future<String?> getToken() async => null;

  @override
  Stream<String> get onTokenRefresh => const Stream<String>.empty();

  @override
  Stream<Map<String, dynamic>> get onMessageOpenedApp =>
      const Stream<Map<String, dynamic>>.empty();

  @override
  Future<Map<String, dynamic>?> getInitialMessage() async => null;

  @override
  String? get deviceName => null;
}
