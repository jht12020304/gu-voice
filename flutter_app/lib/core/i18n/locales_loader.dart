import 'dart:convert';
import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:flutter/services.dart' show rootBundle;

import '../router/lng.dart';

// Holds the 50 verbatim i18next JSON files (5 langs x 10 namespaces, ~400 KB, ~5600
// strings) in memory. Small enough to keep fully resident, and that is what makes
// lookup + the fallback chain a pure *synchronous* operation — `t()` is called from
// build() everywhere, so it can never be async.
//
// What changed 2026-08-22 (cold start): loading all 50 files was on the pre-runApp
// path AND was fully sequential — 50 awaited platform-channel round trips plus 50
// json.decode calls on the main isolate, all before the first frame could paint.
// Nothing is on screen during that, so it read as a hung launch. Now:
//   * per-language load fans out over the 10 namespaces (Future.wait), and
//   * boot awaits only the languages `t()` can actually resolve to right now
//     (the active language + its fallback chain), and
//   * the rest are warmed in the background after the first frame.
// `loadAll()` keeps its old all-5-languages contract because the test suite asserts
// on every language being resident; it is now parallel and idempotent as well.
class Locales {
  static final Map<String, Map<String, dynamic>> _store = {};
  static final Map<String, Future<void>> _inFlight = {};

  /// The languages `t()` may fall back through for [lng], nearest first.
  /// Mirrors `_resolutionChain` in loc.dart — if these two ever disagree, `t()` can
  /// resolve to a language boot never loaded and silently render raw keys.
  static List<String> resolutionChain(String lng) {
    final seen = <String>{};
    return <String>[lng, ...?fallbackChain[lng], defaultLanguage].where(seen.add).toList();
  }

  /// Load one language's 10 namespaces concurrently. Idempotent and de-duplicated:
  /// concurrent callers share one in-flight future, and a completed language is a
  /// no-op, so `ensure` is safe to call on every language switch.
  static Future<void> ensure(String lng) {
    if (_store.containsKey(lng)) return Future.value();
    return _inFlight.putIfAbsent(lng, () async {
      try {
        final raws = await Future.wait(
          allNamespaces.map((ns) => rootBundle.loadString('assets/locales/$lng/$ns.json')),
        );
        final nsMap = <String, dynamic>{};
        for (var i = 0; i < allNamespaces.length; i++) {
          nsMap[allNamespaces[i]] = json.decode(raws[i]);
        }
        _store[lng] = nsMap;
      } finally {
        // Drop the marker either way: a failed load (missing asset in a stripped
        // build) must stay retryable rather than poisoning the language forever.
        _inFlight.remove(lng);
      }
    });
  }

  /// Boot path. Awaits only what the first frame can actually need for [lng]
  /// (1 language for zh-TW/en-US, 3 for the beta languages) instead of all 5.
  static Future<void> loadForBoot(String lng) =>
      Future.wait(resolutionChain(lng).map(ensure));

  /// Background warm-up for the languages boot skipped. Fire-and-forget after the
  /// first frame — failures are swallowed because `ensure` is called again (and
  /// awaited) on the language-switch path, which is the only place it matters.
  static Future<void> warmRemaining() async {
    for (final lng in supportedLanguages) {
      if (_store.containsKey(lng)) continue;
      try {
        await ensure(lng);
      } catch (_) {/* retried on demand by switchLanguage */}
    }
  }

  /// All 5 languages. Kept for the test suite, which asserts every language is
  /// resident (`Locales.forLng(lng)!` across supportedLanguages).
  static Future<void> loadAll() => Future.wait(supportedLanguages.map(ensure));

  static bool isLoaded(String lng) => _store.containsKey(lng);

  static Map<String, dynamic>? forLng(String lng) => _store[lng];

  /// Drops everything loaded. Only for tests that assert on *which* languages boot
  /// pulled in — the whole point of `loadForBoot` is that it does not load all five,
  /// and that is unobservable without being able to start from empty.
  @visibleForTesting
  static void resetForTest() {
    _store.clear();
    _inFlight.clear();
  }
}
