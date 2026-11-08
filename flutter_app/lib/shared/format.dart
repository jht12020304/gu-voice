import 'package:intl/intl.dart';

// DateFormat 建構不便宜（解析 pattern），列表每列都要用，所以 hoist 成常數級單例。
final _dateTimeFmt = DateFormat('yyyy/MM/dd HH:mm');
final _shortTimeFmt = DateFormat('MM-dd HH:mm');
final _clockFmt = DateFormat('HH:mm');

// Mirrors the web formatDate (Intl yyyy/MM/dd HH:mm) and durationMinutes(round(sec/60)).
String formatDateTime(String? iso) {
  if (iso == null) return '—';
  final dt = DateTime.tryParse(iso);
  if (dt == null) return '—';
  return _dateTimeFmt.format(dt.toLocal());
}

/// `2026-09-09T01:23:45Z` → `09-09 01:23`（本地時間）。解析不了就原樣顯示，不要吞掉。
String formatShortTime(String iso) {
  final dt = DateTime.tryParse(iso);
  return dt == null ? iso : _shortTimeFmt.format(dt.toLocal());
}

/// `HH:mm`（已是本地時間的 DateTime）；null → `—`。
String formatClock(DateTime? dt) => dt == null ? '—' : _clockFmt.format(dt);

/// `yyyy-MM`——月份統計卡與 /sessions 月份篩選用的 key。
String monthKey(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}';

/// `yyyy-MM-dd`（不轉時區：給的是什麼日期就印什麼日期）。
String isoDate(DateTime d) => '${monthKey(d)}-${d.day.toString().padLeft(2, '0')}';

/// ISO 時間字串 → **裝置本地**的那一天（當地 00:00 的 `DateTime`）。
/// 本地日只有這一份實作：日曆的 `sessionLocalDay`／`bucketByLocalDay` 與分組清單的
/// [localDayKey] 都從這裡派生。裸 `substring(0, 10)` 是 UTC 切日，23:30 的本地事件會掉到前一天。
DateTime? localDay(String? iso) {
  if (iso == null) return null;
  final dt = DateTime.tryParse(iso);
  if (dt == null) return null;
  final local = dt.toLocal();
  return DateTime(local.year, local.month, local.day);
}

/// [localDay] 的 `yyyy-MM-dd` 字串版——給「依日期分組」的 map key 用。
String? localDayKey(String? iso) {
  final day = localDay(iso);
  return day == null ? null : isoDate(day);
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
