import 'dart:math';

// Journal-grade stats for the research figures. Pure + unit-tested.

// Full-precision two-sided 95% z (the backend's _Z_95; the "1.96" comment is rounded).
const double _z = 1.959963984540054;

class WilsonCi {
  final double p; // point estimate x/n
  final double low;
  final double high;
  const WilsonCi(this.p, this.low, this.high);
}

// Wilson score interval. CRITICAL invariant: numerator must be ⊆ denominator, else
// p̂ > 1 makes p̂(1-p̂) negative and the sqrt is NaN → the web app 500s. We clamp x to
// [0, n] defensively so a bad input degrades instead of crashing.
WilsonCi wilsonCi(int numerator, int denominator) {
  if (denominator <= 0) return const WilsonCi(0, 0, 0);
  final x = numerator.clamp(0, denominator);
  final n = denominator.toDouble();
  final p = x / n;
  final z2 = _z * _z;
  final denom = 1 + z2 / n;
  final center = (p + z2 / (2 * n)) / denom;
  final margin = (_z / denom) * sqrt(p * (1 - p) / n + z2 / (4 * n * n));
  return WilsonCi(p, (center - margin).clamp(0.0, 1.0), (center + margin).clamp(0.0, 1.0));
}

// d3.quantile / type-7 linear interpolation on an ALREADY-SORTED ascending list.
double quantileSorted(List<double> sorted, double q) {
  if (sorted.isEmpty) return double.nan;
  if (sorted.length == 1) return sorted.first;
  final i = (sorted.length - 1) * q;
  final lo = i.floor();
  final h = i - lo;
  if (lo + 1 >= sorted.length) return sorted[lo];
  return sorted[lo] + (sorted[lo + 1] - sorted[lo]) * h;
}

class BoxStats {
  final double min, q1, median, q3, max;
  final double whiskerLow, whiskerHigh;
  final List<double> outliers;
  const BoxStats(this.min, this.q1, this.median, this.q3, this.max, this.whiskerLow, this.whiskerHigh, this.outliers);
}

// Tukey boxplot: box = Q1..Q3, whiskers reach the most extreme point within 1.5*IQR of
// the quartiles, points beyond the fences are outliers.
BoxStats? boxStats(List<double> values) {
  if (values.isEmpty) return null;
  final s = [...values]..sort();
  final q1 = quantileSorted(s, 0.25);
  final median = quantileSorted(s, 0.5);
  final q3 = quantileSorted(s, 0.75);
  final iqr = q3 - q1;
  final loFence = q1 - 1.5 * iqr;
  final hiFence = q3 + 1.5 * iqr;
  final inFence = s.where((v) => v >= loFence && v <= hiFence).toList();
  final whiskerLow = inFence.isEmpty ? s.first : inFence.first;
  final whiskerHigh = inFence.isEmpty ? s.last : inFence.last;
  final outliers = s.where((v) => v < loFence || v > hiFence).toList();
  return BoxStats(s.first, q1, median, q3, s.last, whiskerLow, whiskerHigh, outliers);
}
