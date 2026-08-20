import '../../core/router/lng.dart';

// The intake page's parameters travel in the URL, never in go_router's `extra:`.
//
// `extra` is an in-memory object attached to a navigation. A browser refresh, a restored
// tab, or a shared/deep link rebuilds the route from the URL ALONE, so `extra` comes back
// null: `complaintId` became null and POST /sessions 422'd with no way back. React has
// always used query params here (`SelectComplaintPage.tsx` -> `navigate('/patient/medical-info?' + params)`).
//
// The lng prefix stays the single language authority (`prefixLngToPath`), so the link is
// still `/zh-TW/patient/medical-info?...`.

const medicalInfoPath = '/patient/medical-info';

String medicalInfoLocation({
  required String lng,
  required String complaintId,
  required String complaintName,
  required String complaintText,
}) =>
    Uri(
      path: prefixLngToPath(medicalInfoPath, lng),
      queryParameters: {
        'complaintId': complaintId,
        'complaintName': complaintName,
        'complaintText': complaintText,
      },
    ).toString();

/// Inverse of [medicalInfoLocation]: what the route builder hands the page. Missing
/// params degrade to `''` (same as React's `searchParams.get(...) || ''`) — the page
/// treats empty as "not provided" rather than sending a blank string on.
Map<String, String> medicalInfoArgsFromUri(Uri uri) {
  final q = uri.queryParameters;
  return {
    'complaintId': q['complaintId'] ?? '',
    'complaintName': q['complaintName'] ?? '',
    'complaintText': q['complaintText'] ?? '',
  };
}
