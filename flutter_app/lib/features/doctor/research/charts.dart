import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

// Shared chart palette (matches the web charts.tsx), assigned by index, wrapping.
const researchPalette = [
  Color(0xFF8F3A6F),
  Color(0xFFF2A83B),
  Color(0xFF16181D),
  Color(0xFF4A7AF7),
  Color(0xFF46A168),
  Color(0xFFD0D5DD),
];
const _donutTrack = Color(0xFFE8ECF3);

// Donut (chief-complaint distribution) + legend. Percent = round(count/total*100).
class DonutCard extends StatelessWidget {
  const DonutCard({super.key, required this.title, required this.items, required this.centerLabel, required this.emptyLabel});
  final String title;
  final List<({String label, int count})> items;
  final String centerLabel;
  final String emptyLabel;

  @override
  Widget build(BuildContext context) {
    final total = items.fold<int>(0, (s, i) => s + i.count);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 12),
          if (items.isEmpty)
            Container(
              height: 120,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                border: Border.all(color: Theme.of(context).dividerColor, style: BorderStyle.solid),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(emptyLabel),
            )
          else
            Row(children: [
              SizedBox(
                width: 140,
                height: 140,
                child: Stack(alignment: Alignment.center, children: [
                  PieChart(PieChartData(
                    sectionsSpace: 0,
                    centerSpaceRadius: 44,
                    startDegreeOffset: -90,
                    sections: total == 0
                        ? [PieChartSectionData(value: 1, color: _donutTrack, radius: 18, showTitle: false)]
                        : [
                            for (var i = 0; i < items.length; i++)
                              PieChartSectionData(
                                value: items[i].count.toDouble(),
                                color: researchPalette[i % researchPalette.length],
                                radius: 18,
                                showTitle: false,
                              ),
                          ],
                  )),
                  Column(mainAxisSize: MainAxisSize.min, children: [
                    Text('$total', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
                    Text(centerLabel, style: Theme.of(context).textTheme.bodySmall),
                  ]),
                ]),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(children: [
                  for (var i = 0; i < items.length; i++)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(children: [
                        Container(width: 10, height: 10, decoration: BoxDecoration(color: researchPalette[i % researchPalette.length], shape: BoxShape.circle)),
                        const SizedBox(width: 6),
                        Expanded(child: Text(items[i].label, overflow: TextOverflow.ellipsis)),
                        Text('${items[i].count}  ${total > 0 ? (items[i].count / total * 100).round() : 0}%',
                            style: const TextStyle(fontWeight: FontWeight.w600, fontFeatures: [FontFeature.tabularFigures()])),
                      ]),
                    ),
                ]),
              ),
            ]),
        ]),
      ),
    );
  }
}

// Daily-trend bars (sessions). ponytail: the floating amber red-flag count badge above
// each bar is deferred — days with red flags are marked by an amber dot under the bar.
class DailyTrendCard extends StatelessWidget {
  const DailyTrendCard({super.key, required this.title, required this.days, required this.totalLabel, required this.peakLabel});
  final String title;
  final List<({String label, int sessions, int redFlags})> days;
  final String totalLabel;
  final String peakLabel;

  @override
  Widget build(BuildContext context) {
    final total = days.fold<int>(0, (s, d) => s + d.sessions);
    final maxV = days.fold<int>(1, (m, d) => d.sessions > m ? d.sessions : m);
    final peak = days.isEmpty ? null : days.reduce((a, b) => a.sessions >= b.sessions ? a : b);
    final primary = Theme.of(context).colorScheme.primary;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall),
            Text('$totalLabel $total  ·  $peakLabel ${peak?.sessions ?? 0} (${peak?.label ?? '-'})',
                style: Theme.of(context).textTheme.bodySmall),
          ]),
          const SizedBox(height: 12),
          SizedBox(
            height: 160,
            child: days.isEmpty
                ? const SizedBox.shrink()
                : SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: SizedBox(
                      width: (days.length * 22).clamp(300, 5000).toDouble(),
                      child: BarChart(BarChartData(
                        maxY: maxV.toDouble(),
                        barTouchData: BarTouchData(enabled: true),
                        gridData: const FlGridData(show: false),
                        borderData: FlBorderData(show: false),
                        titlesData: FlTitlesData(
                          leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                          rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                          bottomTitles: AxisTitles(
                            sideTitles: SideTitles(
                              showTitles: true,
                              reservedSize: 22,
                              getTitlesWidget: (value, meta) {
                                final i = value.toInt();
                                if (i < 0 || i >= days.length) return const SizedBox.shrink();
                                final label = days[i].label;
                                final show = i == 0 || i == days.length - 1 || label.endsWith('/01') || label.endsWith('/15');
                                return Text(show ? label : (label.contains('/') ? label.split('/')[1] : label),
                                    style: const TextStyle(fontSize: 9));
                              },
                            ),
                          ),
                        ),
                        barGroups: [
                          for (var i = 0; i < days.length; i++)
                            BarChartGroupData(x: i, barRods: [
                              BarChartRodData(
                                toY: days[i].sessions.toDouble(),
                                width: 8,
                                color: days[i].redFlags > 0 ? const Color(0xFFF2A83B) : primary,
                                borderRadius: BorderRadius.circular(2),
                              ),
                            ]),
                        ],
                      )),
                    ),
                  ),
          ),
        ]),
      ),
    );
  }
}
