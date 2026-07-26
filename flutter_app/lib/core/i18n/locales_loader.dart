import 'dart:convert';
import 'package:flutter/services.dart' show rootBundle;

import '../router/lng.dart';

// Loads the 50 verbatim i18next JSON files (5 langs x 10 namespaces) into memory once
// at boot. ~5600 strings total — trivial to hold fully, and it makes lookup + the
// fallback chain a pure synchronous operation (no async reload on language switch).
class Locales {
  static final Map<String, Map<String, dynamic>> _store = {};

  static Future<void> loadAll() async {
    for (final lng in supportedLanguages) {
      final nsMap = <String, dynamic>{};
      for (final ns in allNamespaces) {
        final raw = await rootBundle.loadString('assets/locales/$lng/$ns.json');
        nsMap[ns] = json.decode(raw);
      }
      _store[lng] = nsMap;
    }
  }

  static Map<String, dynamic>? forLng(String lng) => _store[lng];
}
