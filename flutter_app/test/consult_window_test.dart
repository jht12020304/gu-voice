import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/shared/format.dart';

void main() {
  test('session fields win; transcript fills gaps', () {
    final turns = ['2026-11-08T01:00:30Z', '2026-11-08T01:07:05Z', null];
    var w = consultWindow(null, null, null, turns);
    expect(w.seconds, 395);
    expect(w.start, DateTime.parse('2026-11-08T01:00:30Z').toLocal());
    w = consultWindow('2026-11-08T01:00:00Z', '2026-11-08T01:10:00Z', 590, turns);
    expect(w.seconds, 590);
    expect(w.end, DateTime.parse('2026-11-08T01:10:00Z').toLocal());
    expect(consultWindow(null, null, null, const []).seconds, isNull);
  });
  test('formatElapsed', () {
    expect(formatElapsed(457), '7:37');
    expect(formatElapsed(3725), '1:02:05');
    expect(formatElapsed(5), '0:05');
  });
}
