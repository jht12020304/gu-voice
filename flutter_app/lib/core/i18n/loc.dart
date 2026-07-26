import '../router/lng.dart';
import 'locales_loader.dart';

// Runtime lookup over the nested i18next JSON.
// Key convention: first dot-segment is the namespace, the rest walks into that
// namespace's JSON. e.g. t('auth.register.title'), t('common.appTitle').
// Interpolation is i18next Handlebars {{name}} (spaces tolerated).
// Fallback chain matches i18n/index.ts: <active> -> (ja/ko/vi -> en-US) -> zh-TW.

final _interp = RegExp(r'\{\{\s*(\w+)\s*\}\}');

List<String> _resolutionChain(String lng) {
  final chain = <String>[lng, ...?fallbackChain[lng], defaultLanguage];
  final seen = <String>{};
  return chain.where(seen.add).toList();
}

String? _lookupIn(String lng, List<String> parts) {
  final root = Locales.forLng(lng);
  if (root == null) return null;
  dynamic node = root[parts.first];
  for (final seg in parts.skip(1)) {
    if (node is Map && node.containsKey(seg)) {
      node = node[seg];
    } else {
      return null;
    }
  }
  return node is String ? node : null;
}

/// Translate `key` for the active language (URL authority). Returns the key itself
/// if missing everywhere, so a gap is visible rather than silently blank.
String t(String key, {Map<String, Object?>? args, String? lng}) {
  final parts = key.split('.');
  String? value;
  for (final candidate in _resolutionChain(lng ?? currentLng)) {
    value = _lookupIn(candidate, parts);
    if (value != null) break;
  }
  final resolved = value ?? key;
  if (args == null || args.isEmpty) return resolved;
  return resolved.replaceAllMapped(
    _interp,
    (m) => (args[m.group(1)] ?? m.group(0)).toString(),
  );
}
