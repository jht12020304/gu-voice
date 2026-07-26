// Patient (types/index.ts). Keys camelCased by the Dio interceptor. No email/sessionCount
// fields exist; session count on the detail page = length of the separately-fetched list.
// The history arrays are flattened to their display strings (allergen/name/condition).
class Patient {
  final String id;
  final String name;
  final String? medicalRecordNumber;
  final String? gender;
  final String? dateOfBirth;
  final String? phone;
  final List<String> allergens; // allergies[].allergen
  final List<String> medications; // currentMedications[].name
  final List<String> conditions; // medicalHistory[].condition
  final String? createdAt;

  const Patient({
    required this.id,
    required this.name,
    this.medicalRecordNumber,
    this.gender,
    this.dateOfBirth,
    this.phone,
    this.allergens = const [],
    this.medications = const [],
    this.conditions = const [],
    this.createdAt,
  });

  static List<String> _field(dynamic list, String key) =>
      list is List ? [for (final e in list) if (e is Map && e[key] != null) e[key].toString()] : const [];

  factory Patient.fromJson(Map j) => Patient(
        id: j['id'] as String,
        name: (j['name'] ?? '') as String,
        medicalRecordNumber: j['medicalRecordNumber'] as String?,
        gender: j['gender'] as String?,
        dateOfBirth: j['dateOfBirth'] as String?,
        phone: j['phone'] as String?,
        allergens: _field(j['allergies'], 'allergen'),
        medications: _field(j['currentMedications'], 'name'),
        conditions: _field(j['medicalHistory'], 'condition'),
        createdAt: j['createdAt'] as String?,
      );
}
