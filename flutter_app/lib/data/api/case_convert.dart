// Deep snake_case <-> camelCase conversion at the API boundary.
// Direct port of frontend/src/services/api/client.ts (snakeToCamel/camelToSnake).
// Backend snake_case is authoritative; number-boundary keys (icd10_codes, audio_b64)
// must round-trip unchanged, so we never break on digit boundaries.

final _snakeToCamel = RegExp(r'_([a-z])');
final _acronymBoundary = RegExp(r'([A-Z]+)([A-Z][a-z])');
final _lowerUpperBoundary = RegExp(r'([a-z0-9])([A-Z])');

String snakeToCamelKey(String key) =>
    key.replaceAllMapped(_snakeToCamel, (m) => m.group(1)!.toUpperCase());

String camelToSnakeKey(String key) => key
    .replaceAllMapped(_acronymBoundary, (m) => '${m.group(1)}_${m.group(2)}')
    .replaceAllMapped(_lowerUpperBoundary, (m) => '${m.group(1)}_${m.group(2)}')
    .toLowerCase();

dynamic _deepConvert(dynamic data, String Function(String) convert) {
  if (data is List) return data.map((e) => _deepConvert(e, convert)).toList();
  if (data is Map) {
    return data.map(
      (k, v) => MapEntry(convert(k as String), _deepConvert(v, convert)),
    );
  }
  return data;
}

T snakeToCamel<T>(dynamic data) => _deepConvert(data, snakeToCamelKey) as T;
T camelToSnake<T>(dynamic data) => _deepConvert(data, camelToSnakeKey) as T;
