import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../auth/auth_notifier.dart';
import 'state/alerts_controller.dart';

/// App-level red-flag signal for doctors/admins, independent of the current route.
///
/// Why this exists (TODO G12): the unacknowledged badge only lived on `DoctorShell`'s
/// bottom nav, and half the doctor surface never renders that shell — `/patients`,
/// `/reports`, `/reports/:sessionId` (the SOAP review screen), `/research`, `/admin/*`,
/// and every detail page. So a critical red flag raised while a doctor was reviewing a
/// report produced **no signal at all**.
///
/// Worse, `alertsProvider` is only constructed when something reads it. A doctor who
/// logs in and goes straight to `/reports` never touched a shell tab, so the controller
/// was never created and `ensureConnected()` never ran — the dashboard WebSocket wasn't
/// even connected. Watching the provider here fixes that too: it is created as soon as
/// an authenticated doctor/admin exists, and stays alive (the provider is deliberately
/// not autoDispose).
///
/// Mirrors the React `DoctorAlertPoller` (PR #26).
class DoctorAlertWatcher extends ConsumerWidget {
  const DoctorAlertWatcher({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authProvider.select((s) => s.user));
    final isClinician = user != null && (user.isDoctor || user.isAdmin);

    // Only clinicians: patients have no alert feed, and subscribing would open a
    // dashboard WS that the backend rejects for their role (ws_manager treats 4003 as
    // a permanent close, so it would not retry — but there is no reason to try).
    if (!isClinician) return child;

    // `watch` (not `read`) so the controller is constructed and kept alive for the whole
    // authenticated session, which is what keeps the dashboard WS connected.
    ref.watch(alertsProvider.select((s) => s.newAlertSeq));

    // 2026-08-23：改鎖 newAlertSeq（只在真的收到 new_red_flag WS 事件時遞增），
    // 不再鎖 unacknowledgedCount——計數會因「登入首載 0→N（U1 全院視野後 N 很大）」
    // 與「樂觀扣減後被 stats_updated 真值收斂回彈」而上下擺動，鎖它等於在每個
    // 畫面誤鳴「偵測到 N 筆新的紅旗警示」（使用者實測回報：查看完按不掉、
    // 到處都在跳）。序號單調遞增，收斂/首載永遠安靜。
    ref.listen(alertsProvider.select((s) => s.newAlertSeq), (prev, next) {
      if (prev == null || next <= prev) return;
      final messenger = ScaffoldMessenger.maybeOf(context);
      if (messenger == null) return;

      messenger.hideCurrentSnackBar();
      messenger.showSnackBar(
        SnackBar(
          // Long, but not indefinite: a clinician may be mid-sentence on another screen.
          duration: const Duration(seconds: 8),
          backgroundColor: Theme.of(context).colorScheme.error,
          content: Text(
            t('dashboard.alerts.newAlertToast', args: {'count': '${next - prev}'}),
            style: TextStyle(color: Theme.of(context).colorScheme.onError),
          ),
          action: SnackBarAction(
            label: t('dashboard.alerts.newAlertToastAction'),
            textColor: Theme.of(context).colorScheme.onError,
            onPressed: () => context.go(prefixLngToPath('/alerts', currentLng)),
          ),
        ),
      );
    });

    return child;
  }
}
