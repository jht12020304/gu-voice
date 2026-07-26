import 'package:intl/intl.dart';

// Mirrors the web formatDate (Intl yyyy/MM/dd HH:mm) and durationMinutes(round(sec/60)).
String formatDateTime(String? iso) {
  if (iso == null) return '—';
  final dt = DateTime.tryParse(iso);
  if (dt == null) return '—';
  return DateFormat('yyyy/MM/dd HH:mm').format(dt.toLocal());
}

int durationMinutes(int? seconds) => seconds == null ? 0 : (seconds / 60).round();
