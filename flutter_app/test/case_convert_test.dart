import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/data/api/case_convert.dart';

void main() {
  test('snake wire keys round-trip through camel and back unchanged', () {
    // The invariant from client.ts: number-boundary keys must survive both directions.
    for (final key in ['icd10_codes', 'audio_b64', 'user_id', 'spo2', 'preferred_language']) {
      expect(camelToSnakeKey(snakeToCamelKey(key)), key, reason: key);
    }
  });

  test('acronyms do not explode', () {
    expect(camelToSnakeKey('httpURL'), 'http_url');
    expect(camelToSnakeKey('userID'), 'user_id');
  });

  test('deep conversion recurses into nested maps and lists', () {
    final wire = {
      'session_id': 'x',
      'red_flags': [
        {'icd10_codes': ['N39'], 'is_active': true},
      ],
    };
    final camel = snakeToCamel<Map>(wire);
    expect(camel['sessionId'], 'x');
    expect((camel['redFlags'] as List).first['icd10Codes'], ['N39']);
    // round trip back to the wire shape
    expect(camelToSnake<Map>(camel), wire);
  });
}
