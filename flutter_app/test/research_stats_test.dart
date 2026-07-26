import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/features/doctor/research/stats.dart';

void main() {
  group('wilsonCi', () {
    test('known value 8/10 (z=1.96) ~ [0.49, 0.94]', () {
      final ci = wilsonCi(8, 10);
      expect(ci.p, 0.8);
      expect(ci.low, closeTo(0.490, 0.01));
      expect(ci.high, closeTo(0.943, 0.01));
    });
    test('numerator > denominator is clamped (no NaN — the 500 invariant)', () {
      final ci = wilsonCi(15, 10); // impossible input
      expect(ci.p, 1.0);
      expect(ci.low.isNaN, false);
      expect(ci.high.isNaN, false);
      expect(ci.high, closeTo(1.0, 0.001));
    });
    test('denominator 0 -> zeros', () {
      expect(wilsonCi(0, 0).high, 0);
    });
    test('bounds stay within [0,1]', () {
      final ci = wilsonCi(1, 3);
      expect(ci.low >= 0, true);
      expect(ci.high <= 1, true);
    });
  });

  group('quantile + boxStats', () {
    test('type-7 quantile matches d3 on 1..9', () {
      final s = <double>[1, 2, 3, 4, 5, 6, 7, 8, 9];
      expect(quantileSorted(s, 0.5), 5);
      expect(quantileSorted(s, 0.25), 3);
      expect(quantileSorted(s, 0.75), 7);
    });
    test('Tukey whiskers + outlier detection', () {
      final b = boxStats(<double>[1, 2, 3, 4, 5, 6, 7, 8, 9, 100])!;
      expect(b.median, closeTo(5.5, 0.001));
      expect(b.outliers.contains(100), true); // 100 is beyond Q3 + 1.5*IQR
      expect(b.whiskerHigh, 9); // most extreme within fence
    });
    test('empty -> null', () => expect(boxStats([]), isNull));
  });
}
