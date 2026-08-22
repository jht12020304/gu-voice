// URL `/:lng/*` is the SINGLE authority for the active language.
// Port of frontend/src/i18n/paths.ts + the SUPPORTED_LANGUAGES/fallback from i18n/index.ts.
// Never read language from device locale / stored pref except to seed the FIRST route.

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart' show WidgetsBinding;

const supportedLanguages = ['zh-TW', 'en-US', 'ja-JP', 'ko-KR', 'vi-VN'];
const betaLanguages = ['ja-JP', 'ko-KR', 'vi-VN'];
const defaultLanguage = 'zh-TW';

// The 10 i18next namespaces (defaultNS = common).
const allNamespaces = [
  'common', 'conversation', 'ws', 'intake', 'soap',
  'dashboard', 'session', 'admin', 'auth', 'research',
];

// i18next fallback chain: ja/ko/vi -> en-US -> zh-TW; everything -> zh-TW backstop.
const fallbackChain = <String, List<String>>{
  'ja-JP': ['en-US', 'zh-TW'],
  'ko-KR': ['en-US', 'zh-TW'],
  'vi-VN': ['en-US', 'zh-TW'],
};

// Read by the Dio Accept-Language interceptor — the router keeps this in sync with
// the active route's lng segment (the getLangFromUrl() equivalent).
String currentLng = defaultLanguage;

// Notifies App so MaterialApp's Material/Cupertino localizations (DatePicker, tooltips)
// rebuild on language change. Update via setCurrentLng() from the router redirect.
final currentLngNotifier = ValueNotifier<String>(defaultLanguage);

void setCurrentLng(String lng) {
  // Plain value stays synchronous: Dio's Accept-Language interceptor reads it, and
  // the URL must remain the single authority the moment the route resolves.
  currentLng = lng;
  if (currentLngNotifier.value == lng) return;

  // The notifier drives a ValueListenableBuilder in App. `setCurrentLng` is called
  // from go_router's `redirect`, which runs *during* the Router's build — writing the
  // notifier there marks a descendant dirty mid-build and Flutter throws
  // "setState() or markNeedsBuild() called during build" (caught by the simulator
  // integration test). Deferring to a microtask lands it after the frame's build
  // scope closes, so the rebuild is scheduled for the next frame instead.
  scheduleMicrotask(() {
    if (currentLngNotifier.value != lng) currentLngNotifier.value = lng;
  });
}

/// The language the first frame will render in, resolved the same way the router's
/// redirect resolves it — URL segment first (it is the authority; deep links and the
/// password-reset mail carry it), device locale only as the seed for a bare `/`.
///
/// `main()` needs this *before* runApp so boot can load one language's strings instead
/// of all five. Keeping the two resolutions in one place is the point: if boot loaded a
/// different language than the redirect then picks, the first frame renders the zh-TW
/// fallback and visibly re-renders a beat later.
String bootLanguage() {
  if (kIsWeb) {
    final fromUrl = extractLngFromPath(Uri.base.path);
    if (fromUrl != null) return fromUrl;
  }
  final device = WidgetsBinding.instance.platformDispatcher.locale.toLanguageTag();
  return normalizeLanguage(device) ?? defaultLanguage;
}

bool isSupportedLanguage(String? v) => v != null && supportedLanguages.contains(v);

String? normalizeLanguage(String? raw) {
  if (raw == null || raw.isEmpty) return null;
  if (isSupportedLanguage(raw)) return raw;
  final lower = raw.toLowerCase();
  if (lower.startsWith('zh')) return 'zh-TW';
  if (lower.startsWith('en')) return 'en-US';
  if (lower.startsWith('ja')) return 'ja-JP';
  if (lower.startsWith('ko')) return 'ko-KR';
  if (lower.startsWith('vi')) return 'vi-VN';
  return null;
}

String? extractLngFromPath(String pathname) {
  final parts = pathname.split('/').where((s) => s.isNotEmpty).toList();
  final first = parts.isEmpty ? null : parts.first;
  return isSupportedLanguage(first) ? first : null;
}

String stripLngFromPath(String pathname) {
  final parts = pathname.split('/').where((s) => s.isNotEmpty).toList();
  if (parts.isEmpty) return '/';
  if (isSupportedLanguage(parts.first)) {
    final rest = parts.sublist(1).join('/');
    return rest.isNotEmpty ? '/$rest' : '/';
  }
  return pathname.startsWith('/') ? pathname : '/$pathname';
}

// Prepend lng to an absolute path; if it already has a lng, strip then re-add.
String prefixLngToPath(String path, String lng) {
  if (path.isEmpty) return '/$lng';
  final cleaned = stripLngFromPath(path.startsWith('/') ? path : '/$path');
  final normalized = cleaned == '/' ? '' : cleaned;
  return '/$lng$normalized';
}
