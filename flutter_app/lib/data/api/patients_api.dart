import '../models/patient.dart';
import '../models/session.dart';
import 'dio_client.dart';
import 'parse_page.dart';

typedef PatientPage = ({List<Patient> data, String? nextCursor, bool hasMore, int totalCount});

// Port of frontend/src/services/api/patients.ts. Doctor sees own patients; admin all.
class PatientsApi {
  final _dio = ApiClient.instance.dio;

  Future<PatientPage> list({String? cursor, int limit = 20, String? search, String? createdFrom, String? createdTo}) async {
    final res = await _dio.get('/patients', queryParameters: {
      'cursor': ?cursor,
      'limit': limit,
      'search': ?search,
      'createdFrom': ?createdFrom,
      'createdTo': ?createdTo,
    });
    return parsePage(res.data, Patient.fromJson);
  }

  Future<Patient> get(String id) async {
    final res = await _dio.get('/patients/$id');
    return Patient.fromJson(res.data as Map);
  }

  Future<void> delete(String id) => _dio.delete('/patients/$id');

  Future<List<Session>> getSessions(String patientId) async {
    final res = await _dio.get('/patients/$patientId/sessions');
    final data = res.data;
    final list = (data is Map ? data['data'] : data) as List? ?? const [];
    return list.map((e) => Session.fromJson(e as Map)).toList();
  }
}
