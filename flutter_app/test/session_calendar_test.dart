// 日曆檢視（2026-08-23：「太多問診對話，要一個日曆點下去就是那天的問診，加上時間管理」）
// 的純函式守衛。
//
// 這一頁的正確性幾乎全在「哪一場算哪一天」與「時間怎麼算」上，而那兩件事都不需要
// 網路或 BuildContext——所以邏輯抽成純函式，這裡把每一條規則釘住：
//
//   - 日界線走**裝置本地時區**（後端的 monthly-summary 是 UTC 切日，拿來畫日曆
//     會讓格子上的數字跟點進去的清單對不起來，所以刻意不用它）
//   - 分桶錨點是 createdAt，與後端日期篩選比對的欄位一致
//   - 平均時長沒有樣本時是 null（`—`），不是 0
//   - 空檔只在「前一場有結束時間、且下一場晚於它」時才成立

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/data/models/session.dart';
import 'package:gu_voice/features/doctor/screens/session_calendar_view.dart';

/// 以**本地時間**造一個場次：測試不該依賴跑測試那台機器的時區。
Session _session({
  required DateTime createdAt,
  DateTime? startedAt,
  DateTime? completedAt,
  int? durationSeconds,
  String status = 'completed',
  bool redFlag = false,
  String? id,
}) {
  return Session(
    id: id ?? 's-${createdAt.microsecondsSinceEpoch}',
    status: status,
    language: 'zh-TW',
    redFlag: redFlag,
    createdAt: createdAt.toIso8601String(),
    startedAt: startedAt?.toIso8601String(),
    completedAt: completedAt?.toIso8601String(),
    durationSeconds: durationSeconds,
  );
}

void main() {
  group('monthGridDays', () {
    test('格數是 7 的倍數、從週日起頭、涵蓋整個月', () {
      for (final month in [
        DateTime(2026, 8, 1), // 8/1 是週六 → 前面補 6 格
        DateTime(2026, 2, 1), // 短月
        DateTime(2024, 2, 1), // 閏年
        DateTime(2026, 11, 1), // 11/1 是週日 → 不補
        DateTime(2026, 12, 1), // 跨年邊界
      ]) {
        final days = monthGridDays(month);
        expect(days.length % 7, 0, reason: '$month 的格數不是 7 的倍數');
        expect(days.first.weekday % 7, 0, reason: '$month 的第一格不是週日');
        expect(days.last.weekday, DateTime.saturday, reason: '$month 的最後一格不是週六');

        final lastOfMonth = DateTime(month.year, month.month + 1, 0).day;
        for (var d = 1; d <= lastOfMonth; d++) {
          expect(days.contains(DateTime(month.year, month.month, d)), isTrue,
              reason: '$month 的 $d 號不在格子裡');
        }
      }
    });

    test('補格是真實日期（前後月），不是佔位 null', () {
      final days = monthGridDays(DateTime(2026, 8, 1));
      expect(days.first, DateTime(2026, 7, 26));
      expect(days.where((d) => d.month == 7).isNotEmpty, isTrue);
    });
  });

  group('bucketByLocalDay', () {
    test('依本地日期分桶，桶內依開始時間排序', () {
      final morning = _session(
        createdAt: DateTime(2026, 8, 23, 9, 5),
        startedAt: DateTime(2026, 8, 23, 9, 6),
      );
      final afternoon = _session(
        createdAt: DateTime(2026, 8, 23, 14, 30),
        startedAt: DateTime(2026, 8, 23, 14, 31),
      );
      final otherDay = _session(createdAt: DateTime(2026, 8, 24, 8, 0));

      final buckets = bucketByLocalDay([afternoon, otherDay, morning]);
      expect(buckets.keys.length, 2);
      final day = buckets[DateTime(2026, 8, 23)]!;
      expect(day.map((s) => s.id).toList(), [morning.id, afternoon.id],
          reason: '同一天要依開始時間由早到晚');
    });

    test('清晨與深夜都留在**本地**的那一天（UTC 切日會把它們搬走）', () {
      // +08:00 的診間：本地 00:30 是 UTC 前一天 16:30、本地 23:30 是 UTC 同日 15:30。
      // 用本地時間建構、再看分桶結果，就能證明日界線跟著裝置走。
      final justAfterMidnight = _session(createdAt: DateTime(2026, 8, 23, 0, 30));
      final lateNight = _session(createdAt: DateTime(2026, 8, 23, 23, 30));
      final buckets = bucketByLocalDay([justAfterMidnight, lateNight]);
      expect(buckets.keys.toList(), [DateTime(2026, 8, 23)]);
      expect(buckets[DateTime(2026, 8, 23)]!.length, 2);
    });

    test('錨點是 createdAt——跨午夜才開口的場次算在建立的那天', () {
      // 後端的日期篩選比對 created_at，錨點必須跟它一致，否則區間邊界會撈進
      // 分不進任何一天的孤兒場次。
      final s = _session(
        createdAt: DateTime(2026, 8, 23, 23, 58),
        startedAt: DateTime(2026, 8, 24, 0, 3),
      );
      expect(sessionLocalDay(s), DateTime(2026, 8, 23));
    });

    test('沒有任何時間戳的場次不進桶（不是丟到今天）', () {
      final ghost = Session(id: 'x', status: 'waiting', language: 'zh-TW');
      expect(sessionLocalDay(ghost), isNull);
      expect(bucketByLocalDay([ghost]), isEmpty);
    });
  });

  group('sessionDurationSeconds', () {
    test('優先用後端的 durationSeconds', () {
      final s = _session(
        createdAt: DateTime(2026, 8, 23, 9, 0),
        startedAt: DateTime(2026, 8, 23, 9, 0),
        completedAt: DateTime(2026, 8, 23, 9, 30),
        durationSeconds: 600,
      );
      expect(sessionDurationSeconds(s), 600);
    });

    test('缺 durationSeconds 時退回 completedAt − startedAt', () {
      final s = _session(
        createdAt: DateTime(2026, 8, 23, 9, 0),
        startedAt: DateTime(2026, 8, 23, 9, 0),
        completedAt: DateTime(2026, 8, 23, 9, 15),
      );
      expect(sessionDurationSeconds(s), 900);
    });

    test('進行中／等待中回 null（不是 0）', () {
      final s = _session(
        createdAt: DateTime(2026, 8, 23, 9, 0),
        startedAt: DateTime(2026, 8, 23, 9, 0),
        status: 'in_progress',
      );
      expect(sessionDurationSeconds(s), isNull);
    });

    test('時間反序（結束早於開始）視為無效，回 null', () {
      final s = _session(
        createdAt: DateTime(2026, 8, 23, 9, 0),
        startedAt: DateTime(2026, 8, 23, 9, 30),
        completedAt: DateTime(2026, 8, 23, 9, 0),
      );
      expect(sessionDurationSeconds(s), isNull);
    });
  });

  group('gapMinutes', () {
    final first = _session(
      createdAt: DateTime(2026, 8, 23, 9, 0),
      startedAt: DateTime(2026, 8, 23, 9, 0),
      completedAt: DateTime(2026, 8, 23, 9, 20),
    );

    test('前一場結束到下一場開始的分鐘數', () {
      final second = _session(
        createdAt: DateTime(2026, 8, 23, 9, 45),
        startedAt: DateTime(2026, 8, 23, 9, 45),
      );
      expect(gapMinutes(first, second), 25);
    });

    test('重疊或緊接著開始 → null（不顯示負空檔或 0 分空檔）', () {
      final overlapping = _session(
        createdAt: DateTime(2026, 8, 23, 9, 10),
        startedAt: DateTime(2026, 8, 23, 9, 10),
      );
      final backToBack = _session(
        createdAt: DateTime(2026, 8, 23, 9, 20),
        startedAt: DateTime(2026, 8, 23, 9, 20),
      );
      expect(gapMinutes(first, overlapping), isNull);
      expect(gapMinutes(first, backToBack), isNull);
    });

    test('前一場還沒結束 → null（進行中的場次沒有「之後的空檔」）', () {
      final ongoing = _session(
        createdAt: DateTime(2026, 8, 23, 9, 0),
        startedAt: DateTime(2026, 8, 23, 9, 0),
        status: 'in_progress',
      );
      final next = _session(
        createdAt: DateTime(2026, 8, 23, 10, 0),
        startedAt: DateTime(2026, 8, 23, 10, 0),
      );
      expect(gapMinutes(ongoing, next), isNull);
    });
  });

  group('DayLoad', () {
    test('場次數／完成數／紅旗數／總時長／平均／起訖', () {
      final sessions = [
        _session(
          createdAt: DateTime(2026, 8, 23, 9, 0),
          startedAt: DateTime(2026, 8, 23, 9, 0),
          completedAt: DateTime(2026, 8, 23, 9, 20),
          durationSeconds: 1200,
        ),
        _session(
          createdAt: DateTime(2026, 8, 23, 10, 0),
          startedAt: DateTime(2026, 8, 23, 10, 0),
          completedAt: DateTime(2026, 8, 23, 10, 10),
          durationSeconds: 600,
          redFlag: true,
          status: 'aborted_red_flag',
        ),
        _session(
          createdAt: DateTime(2026, 8, 23, 11, 0),
          startedAt: DateTime(2026, 8, 23, 11, 0),
          status: 'in_progress',
        ),
      ];
      final load = DayLoad.of(sessions);
      expect(load.total, 3);
      expect(load.completed, 1);
      expect(load.redFlags, 1);
      expect(load.busySeconds, 1800);
      // 平均只除以「有時長」的兩場（進行中那場不該把平均拉低）
      expect(load.averageSeconds, 900);
      expect(load.firstStart, DateTime(2026, 8, 23, 9, 0));
      expect(load.lastEnd, DateTime(2026, 8, 23, 10, 10));
    });

    test('一場都還沒結束時平均是 null，不是 0', () {
      final load = DayLoad.of([
        _session(
          createdAt: DateTime(2026, 8, 23, 9, 0),
          startedAt: DateTime(2026, 8, 23, 9, 0),
          status: 'in_progress',
        ),
      ]);
      expect(load.busySeconds, 0);
      expect(load.averageSeconds, isNull,
          reason: '「還沒有資料」與「平均 0 分鐘」是兩件事');
      expect(load.lastEnd, isNull);
    });

    test('空清單不炸', () {
      final load = DayLoad.of(const []);
      expect(load.total, 0);
      expect(load.averageSeconds, isNull);
      expect(load.firstStart, isNull);
    });
  });

  group('isoWithOffset', () {
    test('帶得出裝置時區位移（後端靠它決定日界線）', () {
      final d = DateTime(2026, 8, 23, 0, 0, 0);
      final iso = isoWithOffset(d);
      expect(iso.startsWith('2026-08-23T00:00:00'), isTrue);
      expect(RegExp(r'[+-]\d{2}:\d{2}$').hasMatch(iso), isTrue,
          reason: '沒有位移的字串會被後端當成 UTC，日界線就會切錯');

      final offset = d.timeZoneOffset;
      final sign = offset.isNegative ? '-' : '+';
      final abs = offset.abs();
      final expected =
          '$sign${abs.inHours.toString().padLeft(2, '0')}:${(abs.inMinutes % 60).toString().padLeft(2, '0')}';
      expect(iso.endsWith(expected), isTrue);
    });
  });

  test('五語系都有日曆文案（缺一個語系就會顯示 key 本身）', () {
    const keys = [
      'viewCalendar',
      'viewList',
      'previousMonth',
      'nextMonth',
      'monthSessions',
      'daysWithSessions',
      'dayTitle',
      'sessionsCount',
      'busyTime',
      'averageDuration',
      'clinicWindow',
      'gap',
      'ongoing',
      'minutesShort',
      'hoursMinutes',
      'emptyDayTitle',
      'emptyDayMessage',
    ];
    const weekdays = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
    for (final lng in supportedLanguages) {
      final raw = json.decode(
        File('${Directory.current.path}/assets/locales/$lng/session.json')
            .readAsStringSync(),
      ) as Map;
      final cal = (raw['doctor'] as Map)['calendar'] as Map?;
      expect(cal, isNotNull, reason: '$lng 沒有 session.doctor.calendar 區塊');
      for (final k in keys) {
        expect(cal![k], isA<String>(), reason: '$lng 缺 calendar.$k');
        expect((cal[k] as String).trim(), isNotEmpty, reason: '$lng 的 $k 是空字串');
      }
      final wd = cal!['weekday'] as Map?;
      expect(wd, isNotNull, reason: '$lng 缺 calendar.weekday');
      for (final k in weekdays) {
        expect((wd![k] as String?)?.trim().isNotEmpty ?? false, isTrue,
            reason: '$lng 缺星期簡稱 $k');
      }
    }
  });

  test('帶佔位符的文案在五語系都保留了佔位符', () {
    const withArgs = {
      'dayTitle': ['{{month}}', '{{day}}', '{{weekday}}'],
      'sessionsCount': ['{{count}}'],
      'gap': ['{{minutes}}'],
      'minutesShort': ['{{minutes}}'],
      'hoursMinutes': ['{{hours}}', '{{minutes}}'],
    };
    for (final lng in supportedLanguages) {
      final raw = json.decode(
        File('${Directory.current.path}/assets/locales/$lng/session.json')
            .readAsStringSync(),
      ) as Map;
      final cal = ((raw['doctor'] as Map)['calendar'] as Map);
      withArgs.forEach((key, placeholders) {
        for (final p in placeholders) {
          expect((cal[key] as String).contains(p), isTrue,
              reason: '$lng 的 $key 掉了 $p——畫面上會少掉一個數字');
        }
      });
    }
  });
}
