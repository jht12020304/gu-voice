import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../data/models/research_analytics.dart';
import 'stats.dart';

// Journal-grade figure primitives, ported pixel-faithfully from research/charts.tsx.
// Each is an SVG viewBox in the web; here we scale the canvas by size.width/W and draw in
// viewBox units. Values (median/CI/whiskers) are pre-computed by the backend — we draw
// what we receive (no client-side stats), with a defensive Wilson fallback + [0,1] clamps.

const _blue = Color(0xFF2563EB);
const _track = Color(0xFFF1F5F9);
const _muted = Color(0xFF64748B);
const _ink = Color(0xFF0F172A);
const _grid = Color(0xFFE2E8F0);

void _text(Canvas c, String s, Offset topLeft,
    {double size = 11, Color color = _ink, FontWeight weight = FontWeight.w400, double anchor = 0}) {
  // anchor: 0 = left, 0.5 = center, 1 = right (shifts x by -anchor*width)
  final tp = TextPainter(
    text: TextSpan(text: s, style: TextStyle(fontSize: size, color: color, fontWeight: weight, fontFeatures: const [FontFeature.tabularFigures()])),
    textDirection: TextDirection.ltr,
  )..layout();
  tp.paint(c, Offset(topLeft.dx - anchor * tp.width, topLeft.dy));
}

String _fmt(double v) => v.abs() >= 100 ? v.toStringAsFixed(0) : v.toStringAsFixed(1);

// ── ProportionRow: track + value bar + Wilson 95% CI whisker (domain [0,1]) ──
class ProportionRowChart extends StatelessWidget {
  const ProportionRowChart({super.key, required this.prop, this.color = _blue});
  final Proportion prop;
  final Color color;

  @override
  Widget build(BuildContext context) => AspectRatio(
        aspectRatio: 520 / 34,
        child: CustomPaint(painter: _ProportionPainter(prop, color)),
      );
}

class _ProportionPainter extends CustomPainter {
  _ProportionPainter(this.prop, this.color);
  final Proportion prop;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 520);
    const padL = 6.0, padR = 96.0, cy = 17.0;
    const barW = 520 - padL - padR;
    double x(double v) => padL + v.clamp(0.0, 1.0) * barW;

    canvas.drawRRect(RRect.fromRectAndRadius(const Rect.fromLTWH(padL, cy - 7, barW, 14), const Radius.circular(4)), Paint()..color = _track);

    // Backend value/ci; fall back to a client Wilson CI if value is null but counts exist.
    var value = prop.value;
    var ciLow = prop.ciLow, ciHigh = prop.ciHigh;
    if (value == null && prop.denominator > 0) {
      final w = wilsonCi(prop.numerator, prop.denominator);
      value = w.p;
      ciLow = w.low;
      ciHigh = w.high;
    }

    if (value != null) {
      final w = (x(value) - padL).clamp(1.0, barW);
      canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(padL, cy - 7, w, 14), const Radius.circular(4)), Paint()..color = color);
      if (ciLow != null && ciHigh != null) {
        final p = Paint()..color = _ink..strokeWidth = 1.5;
        canvas.drawLine(Offset(x(ciLow), cy), Offset(x(ciHigh), cy), p);
        canvas.drawLine(Offset(x(ciLow), cy - 5), Offset(x(ciLow), cy + 5), p);
        canvas.drawLine(Offset(x(ciHigh), cy - 5), Offset(x(ciHigh), cy + 5), p);
      }
      _text(canvas, '${(value * 100).toStringAsFixed(1)}%', const Offset(520 - padR + 8, cy - 6), weight: FontWeight.w600);
    } else {
      _text(canvas, '—', const Offset(520 - padR + 8, cy - 6), color: _muted);
    }
  }

  @override
  bool shouldRepaint(_ProportionPainter old) => old.prop != prop || old.color != color;
}

// ── BoxPlotRow: Tukey box/whisker/outliers, auto-fit domain (5% pad) ──
class BoxPlotRowChart extends StatelessWidget {
  const BoxPlotRowChart({super.key, required this.summary, this.transform, this.unit = ''});
  final NumericSummary summary;
  final double Function(double)? transform;
  final String unit;

  @override
  Widget build(BuildContext context) => AspectRatio(
        aspectRatio: 520 / 46,
        child: CustomPaint(painter: _BoxPlotPainter(summary, transform ?? (v) => v, unit)),
      );
}

class _BoxPlotPainter extends CustomPainter {
  _BoxPlotPainter(this.s, this.t, this.unit);
  final NumericSummary s;
  final double Function(double) t;
  final String unit;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 520);
    const padL = 6.0, padR = 46.0, cy = 20.0;
    const plotW = 520 - padL - padR;

    if (s.n == 0 || s.median == null) {
      _text(canvas, 'n = 0', const Offset(padL, cy - 6), color: _muted);
      return;
    }
    final lo = t(s.min ?? 0), hi = t(s.max ?? 0);
    var pad = (hi - lo) * 0.05;
    if (pad == 0) pad = 1;
    final dmin = lo - pad, dmax = hi + pad;
    final span = (dmax - dmin) == 0 ? 1.0 : (dmax - dmin);
    double x(double raw) => padL + ((t(raw) - dmin) / span) * plotW;

    final whisk = Paint()..color = _muted..strokeWidth = 1.5;
    final wl = x(s.whiskerLow ?? s.min ?? 0), wh = x(s.whiskerHigh ?? s.max ?? 0);
    canvas.drawLine(Offset(wl, cy), Offset(wh, cy), whisk);
    canvas.drawLine(Offset(wl, cy - 6), Offset(wl, cy + 6), whisk);
    canvas.drawLine(Offset(wh, cy - 6), Offset(wh, cy + 6), whisk);

    final x1 = x(s.p25 ?? s.median!), x2 = x(s.p75 ?? s.median!);
    final boxRect = Rect.fromLTWH(x1, cy - 11, math.max(x2 - x1, 1), 22);
    canvas.drawRRect(RRect.fromRectAndRadius(boxRect, const Radius.circular(2)), Paint()..color = _blue.withValues(alpha: 0.14));
    canvas.drawRRect(RRect.fromRectAndRadius(boxRect, const Radius.circular(2)), Paint()..color = _blue..style = PaintingStyle.stroke..strokeWidth = 1.5);

    final xm = x(s.median!);
    canvas.drawLine(Offset(xm, cy - 11), Offset(xm, cy + 11), Paint()..color = _blue..strokeWidth = 2.5);

    for (final o in s.outliers) {
      canvas.drawCircle(Offset(x(o), cy), 2.6, Paint()..color = _muted..style = PaintingStyle.stroke..strokeWidth = 1);
    }
    _text(canvas, '${_fmt(t(s.median!))}${unit.isEmpty ? '' : ' $unit'}', const Offset(520 - padR + 6, cy - 6), weight: FontWeight.w600);
  }

  @override
  bool shouldRepaint(_BoxPlotPainter old) => old.s != s;
}

// ── ForestPlot: subgroup proportions with CI, √n square markers, dashed overall line ──
class ForestPlotChart extends StatelessWidget {
  const ForestPlotChart({super.key, required this.rows, this.overall, required this.overallLabel, required this.xLabel});
  final List<({String label, Proportion prop})> rows;
  final double? overall;
  final String overallLabel;
  final String xLabel;

  @override
  Widget build(BuildContext context) {
    const headH = 8.0, rowH = 34.0, footH = 34.0, w = 640.0;
    final h = headH + rows.length * rowH + footH;
    return AspectRatio(
      aspectRatio: w / h,
      child: CustomPaint(painter: _ForestPainter(rows, overall, overallLabel, xLabel)),
    );
  }
}

class _ForestPainter extends CustomPainter {
  _ForestPainter(this.rows, this.overall, this.overallLabel, this.xLabel);
  final List<({String label, Proportion prop})> rows;
  final double? overall;
  final String overallLabel;
  final String xLabel;

  @override
  void paint(Canvas canvas, Size size) {
    const w = 640.0, headH = 8.0, rowH = 34.0, footH = 34.0, padL = 150.0, padR = 60.0;
    const plotW = w - padL - padR;
    final h = headH + rows.length * rowH + footH;
    canvas.scale(size.width / w);
    double x(double v) => padL + v.clamp(0.0, 1.0) * plotW;

    // grid ticks
    for (final tk in const [0.0, 0.25, 0.5, 0.75, 1.0]) {
      canvas.drawLine(Offset(x(tk), headH), Offset(x(tk), headH + rows.length * rowH), Paint()..color = _grid..strokeWidth = 1);
      _text(canvas, '${(tk * 100).round()}%', Offset(x(tk), h - footH + 14), size: 10, color: _muted, anchor: 0.5);
    }
    // overall dashed reference line
    if (overall != null) {
      final p = Paint()..color = _blue..strokeWidth = 1;
      final xo = x(overall!);
      var y = headH;
      while (y < headH + rows.length * rowH) {
        canvas.drawLine(Offset(xo, y), Offset(xo, math.min(y + 4, headH + rows.length * rowH)), p);
        y += 7;
      }
    }
    for (var i = 0; i < rows.length; i++) {
      final cy = headH + i * rowH + rowH / 2;
      final r = rows[i];
      _text(canvas, r.label, Offset(8, cy - 6), size: 12);
      final v = r.prop.value, lo = r.prop.ciLow, hi = r.prop.ciHigh;
      if (v != null && lo != null && hi != null) {
        final p = Paint()..color = _ink..strokeWidth = 1.5;
        canvas.drawLine(Offset(x(lo), cy), Offset(x(hi), cy), p);
        canvas.drawLine(Offset(x(lo), cy - 5), Offset(x(lo), cy + 5), p);
        canvas.drawLine(Offset(x(hi), cy - 5), Offset(x(hi), cy + 5), p);
        final sz = 3.0 + math.min(6.0, math.sqrt(r.prop.denominator.toDouble()));
        final mk = Rect.fromLTWH(x(v) - sz / 2, cy - sz / 2, sz, sz);
        canvas.drawRect(mk, Paint()..color = _blue);
        canvas.drawRect(mk, Paint()..color = Colors.white..style = PaintingStyle.stroke..strokeWidth = 1);
        _text(canvas, '${(v * 100).round()}% (${r.prop.numerator}/${r.prop.denominator})', Offset(w - padR + 6, cy - 6), anchor: 0);
      } else {
        _text(canvas, 'n/a', Offset(x(0.5), cy - 6), color: _muted, anchor: 0.5);
      }
    }
    final footText = overall != null ? '$xLabel   - - - $overallLabel ${(overall! * 100).toStringAsFixed(1)}%' : xLabel;
    _text(canvas, footText, Offset(padL + plotW / 2, h - 12), size: 10, color: _muted, anchor: 0.5);
  }

  @override
  bool shouldRepaint(_ForestPainter old) => old.rows != rows || old.overall != overall;
}

// ── StackedShareBar: part-to-whole (plain widgets, no painter) ──
class StackedShareBar extends StatelessWidget {
  const StackedShareBar({super.key, required this.items});
  final List<({String label, int count, Color color})> items;

  @override
  Widget build(BuildContext context) {
    final total = items.fold<int>(0, (s, i) => s + i.count);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      ClipRRect(
        borderRadius: BorderRadius.circular(4),
        child: SizedBox(
          height: 24,
          child: total == 0
              ? Container(color: _muted)
              : Row(children: [
                  for (var i = 0; i < items.length; i++)
                    if (items[i].count > 0) ...[
                      if (i > 0) const SizedBox(width: 2),
                      Expanded(flex: items[i].count, child: Container(color: items[i].color)),
                    ],
                ]),
        ),
      ),
      const SizedBox(height: 6),
      Wrap(spacing: 12, runSpacing: 4, children: [
        for (final it in items)
          Row(mainAxisSize: MainAxisSize.min, children: [
            Container(width: 10, height: 10, decoration: BoxDecoration(color: it.color, shape: BoxShape.circle)),
            const SizedBox(width: 4),
            Text('${it.label} ${it.count} (${total > 0 ? (it.count / total * 100).round() : 0}%)',
                style: const TextStyle(fontSize: 12, fontFeatures: [FontFeature.tabularFigures()])),
          ]),
      ]),
    ]);
  }
}
