// Research analytics response (types/api.ts). Keys camelCased by the Dio interceptor.
// Every numeric summary field (except n/outliers) and Proportion value/ci are nullable.
double? _d(dynamic v) => (v as num?)?.toDouble();
int _i(dynamic v) => (v as num?)?.toInt() ?? 0;
List<double> _dl(dynamic v) => v is List ? [for (final e in v) (e as num).toDouble()] : const [];
List<T> _list<T>(dynamic v, T Function(Map) f) => v is List ? [for (final e in v) f(e as Map)] : const [];

class NumericSummary {
  final int n;
  final double? mean, sd, median, p25, p75, min, max, whiskerLow, whiskerHigh;
  final List<double> outliers;
  const NumericSummary({this.n = 0, this.mean, this.sd, this.median, this.p25, this.p75, this.min, this.max, this.whiskerLow, this.whiskerHigh, this.outliers = const []});
  factory NumericSummary.fromJson(Map j) => NumericSummary(
        n: _i(j['n']), mean: _d(j['mean']), sd: _d(j['sd']), median: _d(j['median']),
        p25: _d(j['p25']), p75: _d(j['p75']), min: _d(j['min']), max: _d(j['max']),
        whiskerLow: _d(j['whiskerLow']), whiskerHigh: _d(j['whiskerHigh']), outliers: _dl(j['outliers']),
      );
}

class Proportion {
  final int numerator, denominator;
  final double? value, ciLow, ciHigh;
  const Proportion({this.numerator = 0, this.denominator = 0, this.value, this.ciLow, this.ciHigh});
  factory Proportion.fromJson(Map j) => Proportion(
        numerator: _i(j['numerator']), denominator: _i(j['denominator']),
        value: _d(j['value']), ciLow: _d(j['ciLow']), ciHigh: _d(j['ciHigh']),
      );
}

class Bucket {
  final String key;
  final int count;
  const Bucket(this.key, this.count);
  factory Bucket.fromJson(Map j) => Bucket((j['key'] ?? '') as String, _i(j['count']));
}

class HistogramBucket {
  final double start, end;
  final int count;
  const HistogramBucket(this.start, this.end, this.count);
  factory HistogramBucket.fromJson(Map j) => HistogramBucket(_d(j['start']) ?? 0, _d(j['end']) ?? 0, _i(j['count']));
}

class WeeklyTrendItem {
  final String weekStart;
  final int sessions, completed, redFlagSessions;
  const WeeklyTrendItem(this.weekStart, this.sessions, this.completed, this.redFlagSessions);
  factory WeeklyTrendItem.fromJson(Map j) =>
      WeeklyTrendItem((j['weekStart'] ?? '') as String, _i(j['sessions']), _i(j['completed']), _i(j['redFlagSessions']));
}

class HpiFieldFillRate {
  final String field;
  final int filled, total;
  final double? rate;
  const HpiFieldFillRate(this.field, this.filled, this.total, this.rate);
  factory HpiFieldFillRate.fromJson(Map j) => HpiFieldFillRate((j['field'] ?? '') as String, _i(j['filled']), _i(j['total']), _d(j['rate']));
}

class LanguageBreakdown {
  final String language;
  final int sessions, completed;
  final double? medianDurationSeconds, meanPatientTurns, meanSttConfidence, redFlagSessionRate;
  final Proportion redFlagRate;
  const LanguageBreakdown(this.language, this.sessions, this.completed, this.medianDurationSeconds, this.meanPatientTurns, this.meanSttConfidence, this.redFlagSessionRate, this.redFlagRate);
  factory LanguageBreakdown.fromJson(Map j) => LanguageBreakdown(
        (j['language'] ?? '') as String, _i(j['sessions']), _i(j['completed']),
        _d(j['medianDurationSeconds']), _d(j['meanPatientTurns']), _d(j['meanSttConfidence']),
        _d(j['redFlagSessionRate']), Proportion.fromJson((j['redFlagRate'] as Map?) ?? const {}),
      );
}

class ResearchAnalytics {
  final String? generatedAt;
  // cohort
  final int totalSessions;
  final Proportion completion;
  final List<WeeklyTrendItem> weeklyTrend;
  // demographics
  final int totalPatients;
  final NumericSummary ageYears;
  final List<Bucket> ageBandDistribution, genderDistribution, chiefComplaintDistribution;
  // efficiency
  final NumericSummary durationSeconds, patientTurns, patientTurnChars;
  // history taking
  final int reportsAnalyzed;
  final double? meanHpiCompleteness;
  final List<HpiFieldFillRate> hpiFieldFillRates;
  // safety
  final Proportion alertSession, acknowledged;
  final List<Bucket> severityDistribution, urgencyDistribution, layerDistribution;
  final NumericSummary timeToFirstAlertSeconds, ackLatencySeconds;
  // stt
  final int turnsWithConfidence;
  final NumericSummary confidenceSummary;
  final Proportion lowConfidence;
  final List<HistogramBucket> sttHistogram;
  final double? voiceTurnShare;
  // documentation
  /// Documentation 區塊自己的分母（reports_generated）；與 History-Taking 的
  /// reportsAnalyzed 是不同母體（subjective 為 null 時兩者會岔開）。
  final int reportsGenerated;
  final NumericSummary aiConfidenceSummary;
  final Proportion icd10Verified, physicianAgreement;
  final List<Bucket> reviewOutcomes;
  // language
  final List<LanguageBreakdown> byLanguage;

  const ResearchAnalytics({
    this.generatedAt,
    this.totalSessions = 0,
    this.completion = const Proportion(),
    this.weeklyTrend = const [],
    this.totalPatients = 0,
    this.ageYears = const NumericSummary(),
    this.ageBandDistribution = const [],
    this.genderDistribution = const [],
    this.chiefComplaintDistribution = const [],
    this.durationSeconds = const NumericSummary(),
    this.patientTurns = const NumericSummary(),
    this.patientTurnChars = const NumericSummary(),
    this.reportsAnalyzed = 0,
    this.reportsGenerated = 0,
    this.meanHpiCompleteness,
    this.hpiFieldFillRates = const [],
    this.alertSession = const Proportion(),
    this.acknowledged = const Proportion(),
    this.severityDistribution = const [],
    this.urgencyDistribution = const [],
    this.layerDistribution = const [],
    this.timeToFirstAlertSeconds = const NumericSummary(),
    this.ackLatencySeconds = const NumericSummary(),
    this.turnsWithConfidence = 0,
    this.confidenceSummary = const NumericSummary(),
    this.lowConfidence = const Proportion(),
    this.sttHistogram = const [],
    this.voiceTurnShare,
    this.aiConfidenceSummary = const NumericSummary(),
    this.icd10Verified = const Proportion(),
    this.physicianAgreement = const Proportion(),
    this.reviewOutcomes = const [],
    this.byLanguage = const [],
  });

  factory ResearchAnalytics.fromJson(Map j) {
    Map m(dynamic v) => v is Map ? v : const {};
    final cohort = m(j['cohort']);
    final demo = m(j['demographics']);
    final eff = m(j['efficiency']);
    final hist = m(j['historyTaking']);
    final safety = m(j['safety']);
    final stt = m(j['sttQuality']);
    final doc = m(j['documentation']);
    return ResearchAnalytics(
      generatedAt: j['generatedAt'] as String?,
      totalSessions: _i(cohort['totalSessions']),
      completion: Proportion.fromJson(m(cohort['completion'])),
      weeklyTrend: _list(cohort['weeklyTrend'], WeeklyTrendItem.fromJson),
      totalPatients: _i(demo['totalPatients']),
      ageYears: NumericSummary.fromJson(m(demo['ageYears'])),
      ageBandDistribution: _list(demo['ageBandDistribution'], Bucket.fromJson),
      genderDistribution: _list(demo['genderDistribution'], Bucket.fromJson),
      chiefComplaintDistribution: _list(demo['chiefComplaintDistribution'], Bucket.fromJson),
      durationSeconds: NumericSummary.fromJson(m(eff['durationSeconds'])),
      patientTurns: NumericSummary.fromJson(m(eff['patientTurns'])),
      patientTurnChars: NumericSummary.fromJson(m(eff['patientTurnChars'])),
      reportsAnalyzed: _i(hist['reportsAnalyzed']),
      meanHpiCompleteness: _d(hist['meanHpiCompleteness']),
      hpiFieldFillRates: _list(hist['hpiFieldFillRates'], HpiFieldFillRate.fromJson),
      alertSession: Proportion.fromJson(m(safety['alertSession'])),
      acknowledged: Proportion.fromJson(m(safety['acknowledged'])),
      severityDistribution: _list(safety['severityDistribution'], Bucket.fromJson),
      urgencyDistribution: _list(safety['urgencyDistribution'], Bucket.fromJson),
      layerDistribution: _list(safety['layerDistribution'], Bucket.fromJson),
      timeToFirstAlertSeconds: NumericSummary.fromJson(m(safety['timeToFirstAlertSeconds'])),
      ackLatencySeconds: NumericSummary.fromJson(m(safety['ackLatencySeconds'])),
      turnsWithConfidence: _i(stt['turnsWithConfidence']),
      confidenceSummary: NumericSummary.fromJson(m(stt['confidenceSummary'])),
      lowConfidence: Proportion.fromJson(m(stt['lowConfidence'])),
      sttHistogram: _list(stt['histogram'], HistogramBucket.fromJson),
      voiceTurnShare: _d(stt['voiceTurnShare']),
      reportsGenerated: _i(doc['reportsGenerated']),
      aiConfidenceSummary: NumericSummary.fromJson(m(doc['aiConfidenceSummary'])),
      icd10Verified: Proportion.fromJson(m(doc['icd10Verified'])),
      physicianAgreement: Proportion.fromJson(m(doc['physicianAgreement'])),
      reviewOutcomes: _list(doc['reviewOutcomes'], Bucket.fromJson),
      byLanguage: _list(j['byLanguage'], LanguageBreakdown.fromJson),
    );
  }
}
