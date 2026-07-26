import '../models/session.dart';
import 'dio_client.dart';

// GET /complaints — backend returns name/description/category already localized via the
// Accept-Language header (which the Dio interceptor sets from the URL lng). Patient token
// is auto-scoped to active + default rows. Refetch on language change.
class ComplaintsApi {
  final _dio = ApiClient.instance.dio;

  Future<List<Complaint>> getComplaints({bool activeOnly = true}) async {
    final res = await _dio.get('/complaints', queryParameters: {'limit': 100, if (activeOnly) 'isActive': true});
    final data = res.data;
    final list = (data is Map ? data['data'] : data) as List? ?? const [];
    final complaints = list.map((e) => Complaint.fromJson(e as Map)).toList();
    complaints.sort((a, b) => a.displayOrder.compareTo(b.displayOrder));
    return complaints;
  }

  // Admin CRUD (ComplaintManagementPage).
  Future<Complaint> create(Map<String, dynamic> payload) async {
    final res = await _dio.post('/complaints', data: payload);
    return Complaint.fromJson(res.data as Map);
  }

  Future<Complaint> update(String id, Map<String, dynamic> payload) async {
    final res = await _dio.put('/complaints/$id', data: payload);
    return Complaint.fromJson(res.data as Map);
  }

  Future<void> delete(String id) => _dio.delete('/complaints/$id');
}
