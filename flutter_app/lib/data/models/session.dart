// Backend Session (subset the patient flow needs). Keys arrive camelCased by the Dio
// response interceptor. session.language is the FINAL resolved language — authoritative
// for the WS opening line.
class Session {
  final String id;
  final String status; // waiting|in_progress|completed|aborted_red_flag|cancelled
  final String language;
  final bool redFlag;
  final String? redFlagReason;
  final String? chiefComplaintText;
  final String? doctorId;
  final String? patientName; // backend may inline on list/detail
  final String? startedAt;
  final String? completedAt;
  final int? durationSeconds;
  final String? createdAt;

  const Session({
    required this.id,
    required this.status,
    required this.language,
    this.redFlag = false,
    this.redFlagReason,
    this.chiefComplaintText,
    this.doctorId,
    this.patientName,
    this.startedAt,
    this.completedAt,
    this.durationSeconds,
    this.createdAt,
  });

  factory Session.fromJson(Map json) => Session(
        id: json['id'] as String,
        status: (json['status'] ?? 'waiting') as String,
        language: (json['language'] ?? 'zh-TW') as String,
        redFlag: (json['redFlag'] ?? false) as bool,
        redFlagReason: json['redFlagReason'] as String?,
        chiefComplaintText: json['chiefComplaintText'] as String?,
        doctorId: json['doctorId'] as String?,
        patientName: json['patientName'] as String?,
        startedAt: json['startedAt'] as String?,
        completedAt: json['completedAt'] as String?,
        durationSeconds: (json['durationSeconds'] as num?)?.toInt(),
        createdAt: json['createdAt'] as String?,
      );

  Session copyWith({String? status}) => Session(
        id: id,
        status: status ?? this.status,
        language: language,
        redFlag: redFlag,
        redFlagReason: redFlagReason,
        chiefComplaintText: chiefComplaintText,
        doctorId: doctorId,
        patientName: patientName,
        startedAt: startedAt,
        completedAt: completedAt,
        durationSeconds: durationSeconds,
        createdAt: createdAt,
      );
}

class Complaint {
  final String id;
  final String name;
  final String? nameEn;
  final String? description;
  final String category;
  final int displayOrder;

  const Complaint({
    required this.id,
    required this.name,
    this.nameEn,
    this.description,
    required this.category,
    this.displayOrder = 0,
  });

  factory Complaint.fromJson(Map json) => Complaint(
        id: json['id'] as String,
        name: (json['name'] ?? '') as String,
        nameEn: json['nameEn'] as String?,
        description: json['description'] as String?,
        category: (json['category'] ?? '') as String,
        displayOrder: (json['displayOrder'] ?? 0) as int,
      );
}

// Hard contract with backend seed 20260704_1000-seed_other_chief_complaint.
const otherComplaintId = '00000000-0000-4000-8000-0000000000ff';
