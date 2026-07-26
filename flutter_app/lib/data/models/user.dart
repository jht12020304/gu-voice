// ponytail: plain immutable model + manual fromJson. No freezed/codegen until the
// model count justifies a build_runner step. Keys arrive already camelCased by the
// Dio response interceptor.
class User {
  final String id;
  final String email;
  final String name;
  final String role; // 'patient' | 'doctor' | 'admin'
  final String? phone;
  final String? department;
  final String? licenseNumber;
  final bool isActive;

  const User({
    required this.id,
    required this.email,
    required this.name,
    required this.role,
    this.phone,
    this.department,
    this.licenseNumber,
    this.isActive = true,
  });

  factory User.fromJson(Map json) => User(
        id: json['id'] as String,
        email: (json['email'] ?? '') as String,
        name: (json['name'] ?? '') as String,
        role: (json['role'] ?? 'patient') as String,
        phone: json['phone'] as String?,
        department: json['department'] as String?,
        licenseNumber: json['licenseNumber'] as String?,
        isActive: (json['isActive'] ?? true) as bool,
      );

  bool get isPatient => role == 'patient';
  bool get isDoctor => role == 'doctor';
  bool get isAdmin => role == 'admin';
}
