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
