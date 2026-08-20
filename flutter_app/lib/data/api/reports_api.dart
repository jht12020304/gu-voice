import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../models/soap_report.dart';
import 'dio_client.dart';

typedef ReportPage = ({List<SoapReport> data, String? nextCursor, bool hasMore, int totalCount});

// Port of frontend/src/services/api/reports.ts. There is no /reports?patientId endpoint —
// a patient's report is found via its session id.
class ReportsApi {
  final _dio = ApiClient.instance.dio;

  Future<ReportPage> list({String? cursor, int limit = 20, String? status, String? reviewStatus, String? sessionId}) async {
    final res = await _dio.get('/reports', queryParameters: {
      'cursor': ?cursor,
      'limit': limit,
      'status': ?status,
      'reviewStatus': ?reviewStatus,
      'sessionId': ?sessionId,
    });
    final data = res.data as Map;
    final list = (data['data'] as List? ?? const []).map((e) => SoapReport.fromJson(e as Map)).toList();
    final p = (data['pagination'] as Map?) ?? const {};
    return (
      data: list,
      nextCursor: p['nextCursor'] as String?,
      hasMore: (p['hasMore'] ?? false) as bool,
      totalCount: (p['totalCount'] as num?)?.toInt() ?? list.length,
    );
  }

  Future<SoapReport> review(String id, String reviewStatus, {String? notes}) async {
    final res = await _dio.put('/reports/$id/review', data: {'reviewStatus': reviewStatus, 'reviewNotes': ?notes});
    return SoapReport.fromJson(res.data as Map);
  }

  Future<Uint8List> getPdf(String id, {String? language}) async {
    final res = await _dio.get<List<int>>(
      '/reports/$id/pdf',
      queryParameters: {'includeTranscript': true, 'language': ?language},
      options: Options(responseType: ResponseType.bytes),
    );
    return Uint8List.fromList(res.data ?? const []);
  }

  Future<SoapReport> getReport(String id) async {
    final res = await _dio.get('/reports/$id');
    return SoapReport.fromJson(res.data as Map);
  }

  // Trigger async (Celery) SOAP generation. Endpoint is under /sessions.
  //
  // 一律帶 `{"regenerate": true}`。後端 report_service.generate_report 在**該場次已有
  // report row** 而請求沒帶 regenerate 時直接丟 ReportAlreadyExistsException(409)；而
  // row 早在第一次派工時就建好了，狀態才是 generating/failed/generated。也就是說舊寫法
  // 下「failed 後重試」與醫師端的「重新產生」按下去只會拿到 409——按鈕看得到、按不動。
  // 首次產生時沒有 row，帶不帶 regenerate 行為相同，所以無條件帶是安全的。
  // 呼叫端各自負責 UI 閘門（generating 期間不得再派工，見 canGenerateSoapReport /
  // canRegenerateSoapReport）。
  Future<SoapReport> generateReport(String sessionId) async {
    final res = await _dio.post(
      '/sessions/$sessionId/reports/generate',
      data: {'regenerate': true},
    );
    return SoapReport.fromJson(res.data as Map);
  }

  // Two-step: list by session (limit 1) -> fetch full by id. Returns null if none yet.
  Future<SoapReport?> getReportBySession(String sessionId) async {
    final res = await _dio.get('/reports', queryParameters: {'sessionId': sessionId, 'limit': 1});
    final data = res.data;
    final list = (data is Map ? data['data'] : data) as List? ?? const [];
    if (list.isEmpty) return null;
    final id = (list.first as Map)['id'] as String;
    return getReport(id);
  }
}
