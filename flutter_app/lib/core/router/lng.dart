// URL `/:lng/*` is the SINGLE authority for the active language.
// Port of frontend/src/i18n/paths.ts + the SUPPORTED_LANGUAGES/fallback from i18n/index.ts.
// Never read language from device locale / stored pref except to seed the FIRST route.

import 'package:flutter/foundation.dart';

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
  currentLng = lng;
  if (currentLngNotifier.value != lng) currentLngNotifier.value = lng;
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
