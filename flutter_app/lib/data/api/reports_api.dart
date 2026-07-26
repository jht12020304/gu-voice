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
  Future<SoapReport> generateReport(String sessionId) async {
    final res = await _dio.post('/sessions/$sessionId/reports/generate');
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
