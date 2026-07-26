import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../core/theme/app_tokens.dart';

// Port of SessionThankYouPage.tsx. Two variants driven by the abortedRedFlag flag:
// normal completion auto-returns home after 8s; the red-flag safety variant tells the
// patient to notify on-site staff and deliberately does NOT auto-redirect.
class SessionThankYouPage extends StatefulWidget {
  const SessionThankYouPage({super.key, this.abortedRedFlag = false});
  final bool abortedRedFlag;

  @override
  State<SessionThankYouPage> createState() => _SessionThankYouPageState();
}

class _SessionThankYouPageState extends State<SessionThankYouPage> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // Safety invariant: red-flag variant starts NO timer — the patient stays to find staff.
    if (!widget.abortedRedFlag) {
      _timer = Timer(const Duration(seconds: 8), _goHome);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _goHome() {
    if (mounted) context.go(prefixLngToPath('/patient', currentLng));
  }

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final theme = Theme.of(context);
    final aborted = widget.abortedRedFlag;

    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircleAvatar(
                  radius: 32,
                  backgroundColor: (aborted ? tk.alertCritical : tk.alertSuccess).withValues(alpha: 0.15),
                  child: Icon(aborted ? Icons.warning_amber_rounded : Icons.check_circle,
                      color: aborted ? tk.alertCritical : tk.alertSuccess, size: 34),
                ),
                const SizedBox(height: 24),
                Text(
                  aborted ? t('session.complete.redFlagTitle') : t('session.thankYou.title'),
                  textAlign: TextAlign.center,
                  style: theme.textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: aborted ? tk.alertCritical : null,
                  ),
                ),
                const SizedBox(height: 16),
                // The red-flag safety message is an assertive live region for screen readers.
                Semantics(
                  liveRegion: aborted,
                  child: Text(
                    aborted ? t('ws.events.session.aborted_red_flag') : t('session.thankYou.message'),
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodyLarge?.copyWith(
                      fontWeight: aborted ? FontWeight.w500 : null,
                    ),
                  ),
                ),
                if (!aborted) ...[
                  const SizedBox(height: 24),
                  Text(t('session.thankYou.autoRedirectHint'),
                      style: theme.textTheme.bodySmall, textAlign: TextAlign.center),
                ],
                const SizedBox(height: 24),
                FilledButton(onPressed: _goHome, child: Text(t('session.thankYou.backNowAction'))),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
