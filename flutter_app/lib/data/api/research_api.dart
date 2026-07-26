import '../models/research_analytics.dart';
import 'dio_client.dart';

// GET /api/v1/research/analytics. date_from/date_to optional (YYYY-MM-DD). The Dio request
// interceptor converts dateFrom -> date_from.
class ResearchApi {
  final _dio = ApiClient.instance.dio;

  Future<ResearchAnalytics> getAnalytics({String? dateFrom, String? dateTo}) async {
    final res = await _dio.get('/research/analytics', queryParameters: {'dateFrom': ?dateFrom, 'dateTo': ?dateTo});
    return ResearchAnalytics.fromJson(res.data as Map);
  }
}
