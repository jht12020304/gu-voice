import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/env.dart';
import '../../core/router/app_router.dart';
import '../auth/auth_notifier.dart';

/// Kiosk idle auto-logout (TODO G11) — port of the React `KioskIdleGuard`.
///
/// The deployment is a waiting-room kiosk: patients finish and walk away. Without this,
/// the previous patient's name and chief complaint sit on screen for whoever picks the
/// tablet up next.
///
/// Three guards, all copied from the React original because each one exists for a reason:
/// - **`patient` role only** — a doctor must not get logged out mid-report-review.
/// - **never on `/conversation`** — during voice intake the patient may not touch the
///   screen for minutes at a time. Consultation idleness is the backend's job
///   (`SESSION_IDLE_TIMEOUT`); logging out here would kill a live consultation.
/// - **`Env.kioskIdleTimeoutSeconds == 0` disables it** — non-kiosk deployments
///   (a doctor on a laptop) should not inherit kiosk behaviour.
///
/// ⚠️ Known gap: the timer resets on pointer and key events, but on iOS/Android the
/// on-screen keyboard is drawn by the OS *above* the Flutter view, so taps on its keys
/// do not always arrive as either. A patient who spends the whole window typing without
/// touching the form itself could be logged out. 180s makes that unlikely, and the
/// `Focus` key handler catches it wherever the platform does deliver key events. If it
/// ever bites in the clinic, the fix is to also reset from the intake fields' onChanged
/// rather than to lengthen the window.
/// Whether the idle timer should be running, extracted so the three guards can be
/// tested without a widget tree. Each condition is a distinct failure mode:
/// wrong role → doctors logged out mid-review; missing /conversation exclusion →
/// live consultations killed; ignoring the env switch → non-kiosk deployments
/// inherit kiosk behaviour.
bool shouldArmKioskIdleTimer({
  required int timeoutSeconds,
  required bool isAuthenticated,
  required bool isPatient,
  required String location,
}) {
  if (timeoutSeconds <= 0) return false;
  if (!isAuthenticated || !isPatient) return false;
  return !location.contains('/conversation/');
}

class KioskIdleGuard extends ConsumerStatefulWidget {
  const KioskIdleGuard({super.key, required this.child});
  final Widget child;

  @override
  ConsumerState<KioskIdleGuard> createState() => _KioskIdleGuardState();
}

class _KioskIdleGuardState extends ConsumerState<KioskIdleGuard> {
  Timer? _timer;

  bool get _enabled => Env.kioskIdleTimeoutSeconds > 0;

  void _cancel() {
    _timer?.cancel();
    _timer = null;
  }

  /// Restart the countdown. Called on every interaction and on login.
  void _arm() {
    _cancel();
    _timer = Timer(Duration(seconds: Env.kioskIdleTimeoutSeconds), _onIdle);
  }

  /// The route is checked HERE rather than during build. `GoRouterState.of(context)`
  /// is unavailable in `MaterialApp.router`'s `builder` — that layer sits above the
  /// Navigator, so calling it there throws `GoError: There is no GoRouterState above
  /// the current context` and takes the whole app down (caught by actually running it
  /// on the simulator; analyze and 32 unit tests were all green). `GoRouter.state`
  /// needs no context.
  void _onIdle() {
    if (!mounted) return;
    final user = ref.read(authProvider).user;
    final location = ref.read(routerProvider).state.uri.path;
    if (!shouldArmKioskIdleTimer(
      timeoutSeconds: Env.kioskIdleTimeoutSeconds,
      isAuthenticated: user != null,
      isPatient: user?.isPatient ?? false,
      location: location,
    )) {
      // Not applicable right now (e.g. the patient walked into /conversation without
      // touching the screen again). Keep watching instead of logging anyone out.
      _arm();
      return;
    }
    ref.read(authProvider.notifier).logout();
  }

  @override
  void dispose() {
    _cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_enabled) return widget.child;

    // Role is the only thing checked during build — it needs no router context.
    // The /conversation exclusion is applied when the timer fires (see _onIdle).
    final user = ref.watch(authProvider.select((s) => s.user));
    final active = user != null && user.isPatient;

    // `build` must not start timers as a side effect; do it after the frame.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (active) {
        if (_timer == null) _arm();
      } else {
        _cancel();
      }
    });

    if (!active) return widget.child;

    return Listener(
      // translucent: observe every pointer without stealing hits from the UI below.
      behavior: HitTestBehavior.translucent,
      onPointerDown: (_) => _arm(),
      onPointerMove: (_) => _arm(),
      onPointerSignal: (_) => _arm(),
      child: Focus(
        canRequestFocus: false,
        onKeyEvent: (_, _) {
          _arm();
          return KeyEventResult.ignored; // never swallow input
        },
        child: widget.child,
      ),
    );
  }
}
