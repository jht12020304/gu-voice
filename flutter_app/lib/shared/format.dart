import 'package:intl/intl.dart';

// Mirrors the web formatDate (Intl yyyy/MM/dd HH:mm) and durationMinutes(round(sec/60)).
String formatDateTime(String? iso) {
  if (iso == null) return '—';
  final dt = DateTime.tryParse(iso);
  if (dt == null) return '—';
  return DateFormat('yyyy/MM/dd HH:mm').format(dt.toLocal());
}

int durationMinutes(int? seconds) => seconds == null ? 0 : (seconds / 60).round();
/// 問診起訖（本地時間）＋時長（秒）。場次欄位優先；production 有不少已完成場次沒有
/// `startedAt`／`durationSeconds`（2026-11-08 實查 40 場 completed 只有 26 場有），缺值時
/// 用逐字稿第一句／最後一句的 `createdAt` 補——醫師要知道「這場問了多久」。
({DateTime? start, DateTime? end, int? seconds}) consultWindow(
  String? startedAt,
  String? completedAt,
  int? durationSeconds,
  Iterable<String?> turnTimes,
) {
  DateTime? p(String? iso) => iso == null ? null : DateTime.tryParse(iso)?.toLocal();
  final times = [for (final iso in turnTimes) ?p(iso)]..sort();
  final start = p(startedAt) ?? (times.isEmpty ? null : times.first);
  final end = p(completedAt) ?? (times.isEmpty ? null : times.last);
  final seconds = (durationSeconds != null && durationSeconds >= 0)
      ? durationSeconds
      : (start != null && end != null && !end.isBefore(start) ? end.difference(start).inSeconds : null);
  return (start: start, end: end, seconds: seconds);
}

/// 秒 → `7:05`／`1:02:05`。
String formatElapsed(int seconds) {
  String two(int n) => n.toString().padLeft(2, '0');
  final h = seconds ~/ 3600, m = seconds % 3600 ~/ 60, s = seconds % 60;
  return h > 0 ? '$h:${two(m)}:${two(s)}' : '$m:${two(s)}';
}

final _clockSecFmt = DateFormat('HH:mm:ss');

/// ISO → 本地 `HH:mm:ss`；null／解析失敗 → `''`。
String formatClockSeconds(String? iso) {
  final dt = iso == null ? null : DateTime.tryParse(iso);
  return dt == null ? '' : _clockSecFmt.format(dt.toLocal());
}

/// 一行摘要：`09:12:03–09:19:40 · 持續時間 7:37`（缺的部分省略）。
String consultWindowLabel(({DateTime? start, DateTime? end, int? seconds}) w, String durationLabel) {
  final parts = <String>[
    if (w.start != null) '${_clockSecFmt.format(w.start!)}–${w.end == null ? '' : _clockSecFmt.format(w.end!)}',
    if (w.seconds != null) '$durationLabel ${formatElapsed(w.seconds!)}',
  ];
  return parts.join(' · ');
}
