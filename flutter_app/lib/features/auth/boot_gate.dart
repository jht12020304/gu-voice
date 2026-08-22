import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/i18n/loc.dart';
import 'auth_notifier.dart';

/// What is on screen between `runApp()` and the moment boot knows whether there is a
/// session.
///
/// Before 2026-08-22 this screen did not exist, because `main()` awaited
/// `bootstrap()` — including its `getMe()` round trip to Railway — *before* calling
/// `runApp()`. On the iOS build that meant the launch image, then a blank window for
/// however long the network took, with no spinner and no way to tell a slow launch
/// from a crashed one (this app has no `FlutterError.onError` and no Crashlytics, so a
/// real crash looks identical — see docs/TODO.md §V7).
///
/// Two deliberate choices here:
///  * the spinner is **delayed** by [_spinnerDelay]. A warm launch settles in well under
///    that, and a spinner that flashes for 80 ms reads as jank; showing nothing for a
///    beat reads as instant.
///  * a failed boot lands on a retry, not on the login form. `bootOffline` means the
///    tokens are still stored and probably still valid, and bouncing a doctor to a
///    password prompt because hospital wifi hiccuped is a worse outcome than one tap.
class BootGate extends ConsumerWidget {
  const BootGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final offline = ref.watch(authProvider.select((s) => s.bootOffline));
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: offline ? const _BootRetry() : const _BootSplash(),
        ),
      ),
    );
  }
}

const _spinnerDelay = Duration(milliseconds: 450);

class _BootSplash extends StatefulWidget {
  const _BootSplash();

  @override
  State<_BootSplash> createState() => _BootSplashState();
}

class _BootSplashState extends State<_BootSplash> {
  bool _showSpinner = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer(_spinnerDelay, () {
      if (mounted) setState(() => _showSpinner = true);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          t('common.appTitle'),
          textAlign: TextAlign.center,
          style: theme.textTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w700,
            color: theme.colorScheme.primary,
          ),
        ),
        const SizedBox(height: 24),
        // Reserved whether or not the spinner is showing, so it fading in does not
        // shift the title — the layout is identical before and after [_spinnerDelay].
        SizedBox(
          height: 24,
          width: 24,
          child: AnimatedOpacity(
            opacity: _showSpinner ? 1 : 0,
            duration: const Duration(milliseconds: 180),
            child: const CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      ],
    );
  }
}

class _BootRetry extends ConsumerWidget {
  const _BootRetry();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.cloud_off, size: 40, color: theme.colorScheme.error),
          const SizedBox(height: 16),
          Text(
            // 'common.common.errorTitle' is not a typo: common.json nests a `common`
            // object inside itself, and the key convention eats the first segment as
            // the namespace. Reusing existing copy keeps this screen from adding a key
            // that would have to be mirrored into frontend/src/i18n/locales too.
            t('common.common.errorTitle'),
            style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 20),
          FilledButton.icon(
            icon: const Icon(Icons.refresh),
            label: Text(t('common.retry')),
            onPressed: () => ref.read(authProvider.notifier).retryBootstrap(),
          ),
          const SizedBox(height: 4),
          // Retrying does not help if the account was revoked or the backend is down for
          // the evening, and the login form is behind the router, which is behind boot.
          // Without this, holding a stored token on a dead network is a screen with no exit.
          TextButton(
            onPressed: () => ref.read(authProvider.notifier).abandonBootAndSignOut(),
            child: Text(t('common.header.logout')),
          ),
        ],
      ),
    );
  }
}
