import 'dio_client.dart';

class BucketItem {
  final String key;
  final String label;
  final int count;
  const BucketItem(this.key, this.label, this.count);
  factory BucketItem.fromJson(Map j) =>
      BucketItem((j['key'] ?? '') as String, (j['label'] ?? '') as String, (j['count'] as num?)?.toInt() ?? 0);
}

class DailyTrendItem {
  final String date;
  final String label; // MM/DD
  final int sessions;
  final int redFlags;
  const DailyTrendItem(this.date, this.label, this.sessions, this.redFlags);
  factory DailyTrendItem.fromJson(Map j) => DailyTrendItem(
        (j['date'] ?? '') as String,
        (j['label'] ?? '') as String,
        (j['sessions'] as num?)?.toInt() ?? 0,
        (j['redFlags'] as num?)?.toInt() ?? 0,
      );
}

class MonthlySummary {
  /// 機器可讀的 `YYYY-MM`（後端 `month_key`），月份標題由 UI 依當前語系自行格式化。
  /// 後端另有的 `month_label` 是硬寫中文（「2026 年 7 月」），刻意不收進 model：
  /// 直接顯示會讓非中文語系的醫師看到中英混雜的標題。
  /// 舊版後端沒有這個欄位 → null，呼叫端必須 fallback。
  final String? month;
  final int totalSessions;
  final int totalRedFlagAlerts;
  final List<BucketItem> chiefComplaintDistribution;
  final List<DailyTrendItem> dailyTrend;

  const MonthlySummary({
    this.month,
    this.totalSessions = 0,
    this.totalRedFlagAlerts = 0,
    this.chiefComplaintDistribution = const [],
    this.dailyTrend = const [],
  });

  factory MonthlySummary.fromJson(Map j) => MonthlySummary(
        month: j['month'] as String?,
        totalSessions: (j['totalSessions'] as num?)?.toInt() ?? 0,
        totalRedFlagAlerts: (j['totalRedFlagAlerts'] as num?)?.toInt() ?? 0,
        chiefComplaintDistribution:
            (j['chiefComplaintDistribution'] as List? ?? const []).map((e) => BucketItem.fromJson(e as Map)).toList(),
        dailyTrend: (j['dailyTrend'] as List? ?? const []).map((e) => DailyTrendItem.fromJson(e as Map)).toList(),
      );
}

class DashboardApi {
  final _dio = ApiClient.instance.dio;

  // month = 'YYYY-MM'
  Future<MonthlySummary> getMonthlySummary(String month) async {
    final res = await _dio.get('/dashboard/monthly-summary', queryParameters: {'month': month});
    return MonthlySummary.fromJson(res.data as Map);
  }
}
