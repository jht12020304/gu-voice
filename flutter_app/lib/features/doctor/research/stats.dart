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
