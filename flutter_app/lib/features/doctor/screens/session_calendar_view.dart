import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/sessions_api.dart';
import '../state/sessions_list_controller.dart';
import '../../../data/models/session.dart';
import '../../../shared/format.dart';
import '../../../shared/widgets/status_badge.dart';
import '../../../shared/widgets/ui_kit.dart';

// 依日期看問診（2026-08-23 使用者需求：「太多問診對話，要一個日曆點下去就是那天的
// 問診，加上時間管理」）。場次清單頁只抓最新 50 筆、按狀態與關鍵字過濾——場次一多，
// 「上週三那位病患」就再也翻不到了。這裡改以**日期**為索引，並在選定那天之上疊一層
// 時間資訊：起訖、時長、場與場之間的空檔。
//
// 日界線由**裝置時區**決定，不是後端的 UTC 日界線。後端既有的
// `/dashboard/monthly-summary` 是以 UTC 切日的（`_parse_day_range`），在 +08:00 的
// 診間等於把一天切在早上八點；拿它畫日曆，格子上的數字會跟點進去的清單對不起來。
// 日曆將裝置的逐日零點送到聚合 API（含夏令時間變化），明細沿用同一組日期邊界。

// ── 純函式（抽出來是為了可測，不吃 BuildContext / 網路）──────────────

/// 場次歸屬的「那一天」。
///
/// 錨點刻意用 `createdAt` 而不是 `startedAt`：後端的日期篩選比對的就是
/// `sessions.created_at`，錨點與篩選欄位一致，抓回來的區間才不會有一頭一尾
/// 落在桶外（建立於 23:58、隔天 00:01 才開口說話的那種場次）。
/// 顯示時間仍用 `startedAt ?? createdAt`——病患真正開始講話的時間才是醫師要的。
DateTime? sessionLocalDay(Session s) {
  final iso = s.createdAt ?? s.startedAt;
  if (iso == null) return null;
  final dt = DateTime.tryParse(iso);
  if (dt == null) return null;
  final local = dt.toLocal();
  return DateTime(local.year, local.month, local.day);
}

/// 場次在時間軸上的位置（顯示用）：開始講話的時間。
DateTime? sessionLocalStart(Session s) {
  final iso = s.startedAt ?? s.createdAt;
  if (iso == null) return null;
  return DateTime.tryParse(iso)?.toLocal();
}

/// 場次結束時間（沒有就 null——進行中／等待中都是這一類）。
DateTime? sessionLocalEnd(Session s) {
  final iso = s.completedAt;
  if (iso == null) return null;
  return DateTime.tryParse(iso)?.toLocal();
}

/// 依本地日期分桶。key 是當地 00:00 的 `DateTime`。
Map<DateTime, List<Session>> bucketByLocalDay(List<Session> sessions) {
  final buckets = <DateTime, List<Session>>{};
  for (final s in sessions) {
    final day = sessionLocalDay(s);
    if (day == null) continue;
    buckets.putIfAbsent(day, () => <Session>[]).add(s);
  }
  for (final list in buckets.values) {
    list.sort((a, b) {
      final sa = sessionLocalStart(a);
      final sb = sessionLocalStart(b);
      if (sa == null && sb == null) return 0;
      if (sa == null) return 1;
      if (sb == null) return -1;
      return sa.compareTo(sb);
    });
  }
  return buckets;
}

/// 月曆格子：從該月 1 號往前補到週日、往後補到週六，長度必為 7 的倍數。
///
/// 回傳的每一格都是實際日期（含補的前後月日子），由呼叫端依 `.month` 決定
/// 要不要淡化。不用 null 當佔位是刻意的：使用者點到補格時應該跳到那一天，
/// 而不是點了沒反應。
List<DateTime> monthGridDays(DateTime month) {
  final first = DateTime(month.year, month.month, 1);
  // DateTime.weekday：1=週一 … 7=週日。日曆以週日起頭，所以週日要補 0 格。
  final leading = first.weekday % 7;
  final lastOfMonth = DateTime(month.year, month.month + 1, 0);
  final totalDays = leading + lastOfMonth.day;
  final cells = ((totalDays + 6) ~/ 7) * 7;
  // Calendar days are not always 24 hours when daylight saving time changes.
  return [for (var i = 0; i < cells; i++) DateTime(month.year, month.month, 1 - leading + i)];
}

/// 一天的時間負載（時間管理那半的資料來源）。
class DayLoad {
  /// 一律走 [DayLoad.of]——分母（有時長的場次數）是算出來的，不該由呼叫端自己給。

  /// 這天的場次數。
  final int total;
  final int redFlags;

  /// 實際在問診上的秒數合計（只算有時長的場次）。
  final int busySeconds;
  final DateTime? firstStart;
  final DateTime? lastEnd;

  /// 平均時長（秒）。沒有任何有時長的場次時為 null，**不是 0**——
  /// 「還沒有資料」與「平均 0 分鐘」是兩件事，畫面上要顯示成 `—`。
  int? get averageSeconds {
    final counted = _countedForDuration;
    if (counted == 0) return null;
    return (busySeconds / counted).round();
  }

  final int _countedForDuration;

  static DayLoad of(List<Session> sessions) {
    var redFlags = 0;
    var busy = 0;
    var counted = 0;
    DateTime? firstStart;
    DateTime? lastEnd;
    for (final s in sessions) {
      if (s.redFlag) redFlags++;
      final seconds = sessionDurationSeconds(s);
      if (seconds != null) {
        busy += seconds;
        counted++;
      }
      final start = sessionLocalStart(s);
      if (start != null && (firstStart == null || start.isBefore(firstStart))) {
        firstStart = start;
      }
      final end = sessionLocalEnd(s);
      if (end != null && (lastEnd == null || end.isAfter(lastEnd))) {
        lastEnd = end;
      }
    }
    return DayLoad._(
      total: sessions.length,
      redFlags: redFlags,
      busySeconds: busy,
      countedForDuration: counted,
      firstStart: firstStart,
      lastEnd: lastEnd,
    );
  }

  const DayLoad._({
    required this.total,
    required this.redFlags,
    required this.busySeconds,
    required int countedForDuration,
    required this.firstStart,
    required this.lastEnd,
  }) : _countedForDuration = countedForDuration;
}

/// 場次時長（秒）。優先用後端算好的 `durationSeconds`，缺值時退回
/// `completedAt − startedAt`；兩者都拿不到就是 null（進行中／等待中）。
int? sessionDurationSeconds(Session s) {
  final d = s.durationSeconds;
  if (d != null && d >= 0) return d;
  final start = sessionLocalStart(s);
  final end = sessionLocalEnd(s);
  if (start == null || end == null) return null;
  final seconds = end.difference(start).inSeconds;
  return seconds >= 0 ? seconds : null;
}

/// 兩場之間的空檔（分鐘）。前一場沒結束時間、或時間反序時回 null。
int? gapMinutes(Session previous, Session next) {
  final end = sessionLocalEnd(previous);
  final start = sessionLocalStart(next);
  if (end == null || start == null) return null;
  final minutes = start.difference(end).inMinutes;
  return minutes > 0 ? minutes : null;
}

/// ISO-8601 + 時區位移（後端要靠這個位移才知道日界線切在哪）。
String isoWithOffset(DateTime local) {
  final offset = local.timeZoneOffset;
  final sign = offset.isNegative ? '-' : '+';
  final abs = offset.abs();
  final hh = abs.inHours.toString().padLeft(2, '0');
  final mm = (abs.inMinutes % 60).toString().padLeft(2, '0');
  return '${local.toIso8601String()}$sign$hh:$mm';
}

// ── 畫面 ────────────────────────────────────────────────────────

class SessionCalendarView extends ConsumerStatefulWidget {
  const SessionCalendarView({super.key, this.fetchMonth, this.today});

  /// 測試用完整月份資料；正式路徑使用日統計與單日分頁。
  /// 傳入的是該月 1 號（本地）。
  final Future<List<Session>> Function(DateTime month)? fetchMonth;

  /// 「今天」的注入點（僅測試用）——決定初始月份、初始選取日與 today 外框。
  final DateTime? today;

  @override
  ConsumerState<SessionCalendarView> createState() => _SessionCalendarViewState();
}

class _SessionCalendarViewState extends ConsumerState<SessionCalendarView> {
  final _api = SessionsApi();

  late DateTime _month; // 當月 1 號（本地）
  late DateTime _selected; // 選中的那一天（本地 00:00）
  Map<DateTime, List<Session>> _buckets = const {};
  Map<DateTime, DayLoad> _summaries = const {};
  final _monthCache = <DateTime, ({DateTime at, Map<DateTime, DayLoad> data})>{};
  int _monthRequest = 0;
  int _dayRequest = 0;
  bool _dayLoading = false;
  bool _dayError = false;
  String? _cursor;
  bool _hasMore = false;
  bool _loading = true;
  bool _error = false;

  DateTime get _now => widget.today ?? DateTime.now();

  @override
  void initState() {
    super.initState();
    final now = _now;
    _month = DateTime(now.year, now.month, 1);
    _selected = DateTime(now.year, now.month, now.day);
    Future.microtask(_load);
  }

  Future<void> _load({bool useCache = false}) async {
    if (!mounted) return;
    final request = ++_monthRequest;
    final month = _month;
    setState(() {
      _loading = true;
      _error = false;
    });
    if (widget.fetchMonth == null) _loadDay();
    try {
      Map<DateTime, DayLoad> summaries;
      final cached = _monthCache[month];
      if (widget.fetchMonth != null) {
        final sessions = await widget.fetchMonth!(month);
        if (!mounted || request != _monthRequest) return;
        _buckets = bucketByLocalDay(sessions);
        summaries = _buckets.map((day, rows) => MapEntry(day, DayLoad.of(rows)));
      } else if (useCache && cached != null && DateTime.now().difference(cached.at).inSeconds < 60) {
        summaries = cached.data;
      } else {
        final days = DateTime(month.year, month.month + 1, 0).day;
        final boundaries = List.generate(days + 1, (i) => DateTime(month.year, month.month, i + 1));
        final rows = await _api.calendarSummary(boundaries);
        summaries = {
          for (final row in rows)
            boundaries[(row['dayIndex'] as num).toInt()]: DayLoad._(
              total: (row['total'] as num).toInt(),
              redFlags: (row['redFlags'] as num).toInt(),
              busySeconds: (row['busySeconds'] as num).toInt(),
              countedForDuration: (row['durationCount'] as num).toInt(),
              firstStart: DateTime.tryParse(row['firstStart'] as String? ?? '')?.toLocal(),
              lastEnd: DateTime.tryParse(row['lastEnd'] as String? ?? '')?.toLocal(),
            ),
        };
        _monthCache[month] = (at: DateTime.now(), data: summaries);
        if (_monthCache.length > 12) _monthCache.remove(_monthCache.keys.first);
      }
      if (!mounted || request != _monthRequest) return;
      setState(() {
        _summaries = summaries;
        _loading = false;
      });
    } catch (_) {
      if (!mounted || request != _monthRequest) return;
      setState(() {
        _loading = false;
        _error = true;
      });
    }
  }

  Future<void> _loadDay({bool more = false}) async {
    if (widget.fetchMonth != null || (more && (_dayLoading || !_hasMore))) return;
    final request = ++_dayRequest;
    final day = _selected;
    setState(() {
      _dayLoading = true;
      _dayError = false;
      if (!more) {
        _buckets = {};
        _cursor = null;
        _hasMore = false;
      }
    });
    try {
      final page = await _api.getSessionsPage(
        dateFrom: isoWithOffset(day),
        dateTo: isoWithOffset(DateTime(day.year, day.month, day.day + 1).subtract(const Duration(microseconds: 1))),
        limit: 20,
        cursor: more ? _cursor : null,
        sortBy: 'created_at',
        sortOrder: 'asc',
      );
      if (!mounted || request != _dayRequest) return;
      if (page.hasMore && (page.nextCursor == null || (more && page.nextCursor == _cursor))) {
        throw StateError('Pagination did not advance');
      }
      setState(() {
        final rows = {
          for (final row in [if (more) ...?_buckets[day], ...page.sessions]) row.id: row,
        }.values.toList();
        _buckets = {day: rows};
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
        _dayLoading = false;
      });
    } catch (_) {
      if (!mounted || request != _dayRequest) return;
      setState(() {
        _dayLoading = false;
        _dayError = true;
      });
    }
  }

  void _shiftMonth(int delta) {
    setState(() {
      _month = DateTime(_month.year, _month.month + delta, 1);
      // 換月後選中該月 1 號；停在舊的選取日會顯示一個不在畫面上的日期。
      _selected = DateTime(_month.year, _month.month, 1);
    });
    _load(useCache: true);
  }

  List<Session> get _selectedSessions => _buckets[_selected] ?? const [];

  String get _monthLabel =>
      t('common.doctor.dashboard.monthFormat', args: {'year': _month.year, 'month': _month.month});

  String _dayLabel(DateTime day) => t(
    'session.doctor.calendar.dayTitle',
    args: {'month': day.month, 'day': day.day, 'weekday': t('session.doctor.calendar.weekday.${_weekdayKey(day)}')},
  );

  static String _weekdayKey(DateTime day) => const ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][day.weekday - 1];

  /// 秒 → 「1 小時 20 分」／「20 分」。null → `—`。
  String _duration(int? seconds) {
    if (seconds == null) return '—';
    final minutes = (seconds / 60).round();
    if (minutes < 60) {
      return t('session.doctor.calendar.minutesShort', args: {'minutes': minutes});
    }
    return t('session.doctor.calendar.hoursMinutes', args: {'hours': minutes ~/ 60, 'minutes': minutes % 60});
  }

  @override
  Widget build(BuildContext context) {
    if (widget.fetchMonth == null) {
      ref.listen(sessionsListProvider, (previous, next) {
        if (previous != null && !identical(previous.sessions, next.sessions)) {
          _monthCache.clear();
          _load();
        }
      });
    }
    final monthTotal = _summaries.entries
        .where((e) => e.key.year == _month.year && e.key.month == _month.month)
        .fold<int>(0, (sum, e) => sum + e.value.total);

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          MonthStatsCard(
            monthLabel: _monthLabel,
            prevTooltip: t('session.doctor.calendar.previousMonth'),
            nextTooltip: t('session.doctor.calendar.nextMonth'),
            onPrev: _loading ? null : () => _shiftMonth(-1),
            onNext: _loading ? null : () => _shiftMonth(1),
            cells: [
              StatCell(label: t('session.doctor.calendar.monthSessions'), value: '$monthTotal', loading: _loading),
              StatCell(
                label: t('session.doctor.calendar.daysWithSessions'),
                value: '${_summaries.keys.where((d) => d.year == _month.year && d.month == _month.month).length}',
                loading: _loading,
              ),
            ],
          ),
          const SizedBox(height: 12),
          _calendarCard(context),
          const SizedBox(height: 12),
          if (_error)
            ErrorState(message: t('session.doctor.detail.loadError'), retryLabel: t('common.retry'), onRetry: _load)
          else
            _dayPanel(context),
        ],
      ),
    );
  }

  Widget _calendarCard(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final days = monthGridDays(_month);
    final now = _now;
    final today = DateTime(now.year, now.month, now.day);

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 12, 8, 12),
        child: Column(
          children: [
            Row(
              children: [
                for (final key in const ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'])
                  Expanded(
                    child: Center(
                      child: Text(
                        t('session.doctor.calendar.weekday.$key'),
                        style: Theme.of(context).textTheme.labelSmall?.copyWith(color: tk.inkMuted),
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            for (var row = 0; row < days.length ~/ 7; row++)
              Row(
                children: [
                  for (var col = 0; col < 7; col++)
                    Expanded(child: _dayCell(context, days[row * 7 + col], today: today)),
                ],
              ),
          ],
        ),
      ),
    );
  }

  Widget _dayCell(BuildContext context, DateTime day, {required DateTime today}) {
    final theme = Theme.of(context);
    final tk = theme.extension<AppTokens>()!;
    final count = _summaries[day]?.total ?? 0;
    final inMonth = day.month == _month.month && day.year == _month.year;
    final isSelected = day == _selected;
    final isToday = day == today;
    final hasRedFlag = (_summaries[day]?.redFlags ?? 0) > 0;

    // 顏色階梯：沒場次＝無底色；有場次＝品牌藍淡底，越多越深（上限 3 階）。
    // 用底色深淺而不是點點數量：一眼看得出哪幾天忙，而且不會在小格子裡擠爆。
    final level = count == 0 ? 0 : (count >= 5 ? 3 : (count >= 3 ? 2 : 1));
    final fill = isSelected
        ? theme.colorScheme.primary
        : level == 0
        ? null
        : theme.colorScheme.primary.withValues(alpha: 0.06 * level + 0.04);
    final textColor = isSelected
        ? Colors.white
        : inMonth
        ? tk.inkHeading
        : tk.inkMuted;

    return Padding(
      padding: const EdgeInsets.all(2),
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: () {
          setState(() {
            _selected = day;
            // 點到補格＝想看上／下個月那天，順手把月份也切過去（並重抓資料）。
            if (!inMonth) {
              _month = DateTime(day.year, day.month, 1);
              _load(useCache: true);
            } else {
              _loadDay();
            }
          });
        },
        child: Container(
          height: 46,
          decoration: BoxDecoration(
            color: fill,
            borderRadius: BorderRadius.circular(10),
            border: isToday && !isSelected ? Border.all(color: theme.colorScheme.primary, width: 1.5) : null,
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                '${day.day}',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: textColor,
                  fontWeight: isSelected || isToday ? FontWeight.w700 : FontWeight.w500,
                ),
              ),
              const SizedBox(height: 2),
              SizedBox(
                height: 6,
                child: count == 0
                    ? null
                    : Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Container(
                            width: 4,
                            height: 4,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              // 紅旗那天用警示色的點，翻月份時一眼看得到
                              color: hasRedFlag
                                  ? tk.alertCritical
                                  : isSelected
                                  ? Colors.white
                                  : theme.colorScheme.primary,
                            ),
                          ),
                        ],
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _dayPanel(BuildContext context) {
    final theme = Theme.of(context);
    final tk = theme.extension<AppTokens>()!;
    final sessions = _selectedSessions;
    final load = _summaries[_selected] ?? DayLoad.of(sessions);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 8),
          child: Row(
            children: [
              Text(
                _dayLabel(_selected),
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700, color: tk.inkHeading),
              ),
              const SizedBox(width: 8),
              Text(
                t('session.doctor.calendar.sessionsCount', args: {'count': load.total}),
                style: theme.textTheme.bodySmall?.copyWith(color: tk.inkSecondary),
              ),
            ],
          ),
        ),
        if (_dayError)
          ErrorState(
            message: t('session.doctor.detail.loadError'),
            retryLabel: t('common.retry'),
            onRetry: () => _loadDay(more: sessions.isNotEmpty),
          )
        else if (_loading || (_dayLoading && sessions.isEmpty))
          const SkeletonList()
        else if (sessions.isEmpty)
          EmptyState(
            icon: Icons.event_available_outlined,
            title: t('session.doctor.calendar.emptyDayTitle'),
            message: t('session.doctor.calendar.emptyDayMessage'),
          )
        else ...[
          // ── 時間管理：這天的總覽 ──────────────────────────
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: StatCell(label: t('session.doctor.calendar.busyTime'), value: _duration(load.busySeconds)),
                  ),
                  Container(width: 1, height: 48, color: tk.edge),
                  const SizedBox(width: 16),
                  Expanded(
                    child: StatCell(
                      label: t('session.doctor.calendar.averageDuration'),
                      value: _duration(load.averageSeconds),
                    ),
                  ),
                  Container(width: 1, height: 48, color: tk.edge),
                  const SizedBox(width: 16),
                  Expanded(
                    child: StatCell(
                      label: t('session.doctor.calendar.clinicWindow'),
                      value: load.firstStart == null
                          ? '—'
                          : '${formatClock(load.firstStart)}–${formatClock(load.lastEnd ?? load.firstStart)}',
                      // 「09:12–17:40」在半寬格裡會斷在破折號上，用 compact 的字級
                      compact: true,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          // ── 時間軸：一場一列，中間標出空檔 ────────────────
          for (var i = 0; i < sessions.length; i++) ...[
            if (i > 0)
              Builder(
                builder: (context) {
                  final minutes = gapMinutes(sessions[i - 1], sessions[i]);
                  if (minutes == null) return const SizedBox(height: 4);
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2, horizontal: 12),
                    child: Row(
                      children: [
                        Expanded(child: Divider(color: tk.edge)),
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 8),
                          child: Text(
                            t('session.doctor.calendar.gap', args: {'minutes': minutes}),
                            style: theme.textTheme.labelSmall?.copyWith(color: tk.inkMuted),
                          ),
                        ),
                        Expanded(child: Divider(color: tk.edge)),
                      ],
                    ),
                  );
                },
              ),
            _sessionRow(context, sessions[i]),
          ],
          if (_hasMore)
            TextButton(
              onPressed: _dayLoading ? null : () => _loadDay(more: true),
              child: _dayLoading ? const CircularProgressIndicator() : Text(t('common.pagination.loadMore')),
            ),
        ],
      ],
    );
  }

  Widget _sessionRow(BuildContext context, Session s) {
    final theme = Theme.of(context);
    final tk = theme.extension<AppTokens>()!;
    final start = sessionLocalStart(s);
    final end = sessionLocalEnd(s);
    final seconds = sessionDurationSeconds(s);
    final name = (s.patientName?.isNotEmpty ?? false) ? s.patientName! : t('session.doctor.list.unknownPatient');

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => context.go(prefixLngToPath('/sessions/${s.id}', currentLng)),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 時間欄：起訖 + 時長，固定寬度讓一整天的列對齊成時間軸
              SizedBox(
                width: 62,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      formatClock(start),
                      style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700, color: tk.inkHeading),
                    ),
                    Text(
                      end != null ? formatClock(end) : t('session.doctor.calendar.ongoing'),
                      style: theme.textTheme.labelSmall?.copyWith(color: tk.inkMuted),
                    ),
                  ],
                ),
              ),
              Container(width: 1, height: 40, color: tk.edge),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        if (s.redFlag) ...[
                          Icon(Icons.flag, size: 14, color: tk.alertCritical),
                          const SizedBox(width: 4),
                        ],
                        Expanded(
                          child: Text(
                            name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.bodyMedium?.copyWith(
                              fontWeight: FontWeight.w600,
                              color: tk.inkHeading,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(
                      s.chiefComplaintText?.isNotEmpty ?? false ? s.chiefComplaintText! : '—',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall?.copyWith(color: tk.inkSecondary),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  StatusBadge(s.status),
                  const SizedBox(height: 4),
                  Text(_duration(seconds), style: theme.textTheme.labelSmall?.copyWith(color: tk.inkMuted)),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
