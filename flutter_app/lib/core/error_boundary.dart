import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'i18n/loc.dart';

/// Makes a Dart failure visible instead of blank.
///
/// This app ships no Crashlytics and no Sentry (docs/TODO.md §V7), so on a release iOS
/// build every uncaught error had the same presentation: nothing. A white window, no log
/// the tester could send back, and no way to tell it apart from a slow network. For a
/// TestFlight round that is the worst possible failure mode — the report that comes back
/// is "打不開", which is not actionable by anyone.
///
/// Three hooks, one per place an error can escape:
///  * [FlutterError.onError] — anything thrown inside the framework (build/layout/paint).
///  * [PlatformDispatcher.onError] — async errors that reach the root zone. Preferred over
///    wrapping `runApp` in `runZonedGuarded`, which also intercepts errors the framework
///    means to report itself; this hook is the current Flutter guidance.
///  * [ErrorWidget.builder] — what physically occupies the space where a subtree failed to
///    build. The release default is an empty grey box, i.e. the blank screen again.
///
/// Nothing here is a substitute for real crash reporting; it buys legibility until there
/// is some. Details always go to stderr, so `flutter logs` / Console.app on an attached
/// device shows the stack even though the screen shows one line.
void installErrorBoundary() {
  final previous = FlutterError.onError;
  FlutterError.onError = (details) {
    previous?.call(details);
    _report('flutter', details.exception, details.stack);
  };

  PlatformDispatcher.instance.onError = (error, stack) {
    _report('platform', error, stack);
    return true; // handled — an unhandled root-zone error terminates the isolate
  };

  ErrorWidget.builder = (details) {
    _report('widget', details.exception, details.stack);
    return _ErrorPanel(details: details);
  };
}

void _report(String source, Object error, StackTrace? stack) {
  debugPrint('[gu-voice:$source] $error');
  if (stack != null) debugPrint(stack.toString());
}

/// Deliberately built from primitives, not from Material widgets. This can be inserted
/// anywhere a build failed — including above `MaterialApp`, where there is no
/// `Directionality`, no `Theme` and no `MediaQuery` to inherit — so anything it needs it
/// has to supply itself, or replacing the broken subtree throws again from inside the
/// replacement.
class _ErrorPanel extends StatelessWidget {
  const _ErrorPanel({required this.details});

  final FlutterErrorDetails details;

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.ltr,
      child: ColoredBox(
        color: const Color(0xFFF8F9FC),
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  // Same reused key as BootGate — common.json nests `common` inside
                  // itself, so the namespace segment is eaten and this really is the
                  // path to 「發生錯誤」. Falls back to the raw key if the locale bundle
                  // is what failed, which is still more than a blank screen.
                  t('common.common.errorTitle'),
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Color(0xFF111827),
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 8),
                // The message itself, in whatever language the exception came in — the
                // point is that the person holding the phone can read it out or screenshot
                // it. Never dumped in a doctor-facing flow's normal path, only here.
                Text(
                  '${details.exception}',
                  textAlign: TextAlign.center,
                  maxLines: 6,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Color(0xFF6B7280), fontSize: 12),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
