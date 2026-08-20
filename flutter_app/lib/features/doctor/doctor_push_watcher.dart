import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/router/app_router.dart';
import '../../core/router/lng.dart';
import '../../core/router/route_guard.dart';
import '../../data/models/user.dart';
import '../auth/auth_notifier.dart';
import 'services/push_backend.dart';
import 'services/push_service.dart';

/// FCM 推播的掛載點，比照 [DoctorAlertWatcher]：掛在 MaterialApp.builder 底下，
/// 不綁任何一條路由，所以醫師從哪一頁進來都一樣會註冊。
///
/// 啟動條件是 [shouldEnablePush]（醫師專用平台 × 醫護帳號）——web kiosk 與病患帳號
/// 上這個 widget 只是把 child 原樣傳下去，Firebase 一行都不會跑。
///
/// **前景推播刻意不處理**：通知頁與分頁 badge 已經由 dashboard WebSocket 即時更新
/// （notifications_controller.dart 的 `_wsEvents`），而 App 在前景時 WS 本來就連著，
/// 再掛一條 `onMessage` 只會對同一件事重複 refetch。iOS 前景預設也不顯示系統橫幅，
/// 所以「什麼都不做」在使用者眼裡與現況完全一致。
class DoctorPushWatcher extends ConsumerStatefulWidget {
  const DoctorPushWatcher({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<DoctorPushWatcher> createState() => _DoctorPushWatcherState();
}

class _DoctorPushWatcherState extends ConsumerState<DoctorPushWatcher> {
  PushService? _service;

  @override
  void initState() {
    super.initState();
    // 冷啟動時使用者早就在 state 裡了（main() 先 bootstrap 才 runApp），ref.listen
    // 不會補一次舊值，所以第一幀後主動同步一次。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _sync(ref.read(authProvider).user);
    });
  }

  @override
  void dispose() {
    _stop();
    super.dispose();
  }

  void _sync(User? user) {
    if (shouldEnablePush(user: user, doctorOnlyPlatform: isDoctorOnlyPlatform)) {
      if (_service != null) return; // 已在跑（例如只是換語言重建）
      final service = PushService(backend: createPushBackend(), navigate: _navigate);
      _service = service;
      AuthNotifier.preLogoutHooks.add(service.unregister);
      unawaited(service.start());
    } else {
      _stop();
    }
  }

  void _stop() {
    final service = _service;
    if (service == null) return;
    _service = null;
    // 同一物件的 method tear-off 在 Dart 裡相等，所以移得掉。
    AuthNotifier.preLogoutHooks.remove(service.unregister);
    service.stop();
  }

  /// 用 router 而不是 `context.go`：這個 widget 坐在 Navigator 之上，而且推播可能在
  /// 任何時機進來（含冷啟動的 getInitialMessage），不保證有可用的 route context。
  void _navigate(String route) {
    if (!mounted) return;
    ref.read(routerProvider).go(prefixLngToPath(route, currentLng));
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(authProvider.select((s) => s.user), (_, next) => _sync(next));
    return widget.child;
  }
}
