import '../models/exam_order.dart';
import 'dio_client.dart';

/// 檢查醫囑端點。掛在 `/sessions/{id}/exam-orders` 之下——醫囑的生命週期綁著場次，
/// 沒有跨場次列出所有醫囑的需求。
class ExamOrdersApi {
  final _dio = ApiClient.instance.dio;

  /// 這場次最新一張檢查單；還沒開過時後端回 200 + `null`（不是 404——「還沒開」
  /// 是正常狀態），這裡照樣回 null。
  Future<ExamOrder?> getLatest(String sessionId) async {
    final res = await _dio.get('/sessions/$sessionId/exam-orders/latest');
    final data = res.data;
    if (data is! Map) return null;
    return ExamOrder.fromJson(data);
  }

  /// 送出一張檢查單。空的 [items] 是合法的——代表「看過摘要、這次不開任何檢查」，
  /// 與「還沒看」在臨床上是兩件事。
  Future<ExamOrder> submit(
    String sessionId, {
    required List<ExamOrderItem> items,
    String? note,
    String? reportId,
  }) async {
    final res = await _dio.post('/sessions/$sessionId/exam-orders', data: {
      'items': [for (final i in items) i.toJson()],
      'note': ?note,
      'reportId': ?reportId,
    });
    return ExamOrder.fromJson(res.data as Map);
  }
}
