import Foundation

struct KioskComplaint: Decodable, Identifiable, Sendable {
    static let otherID = UUID(uuidString: "00000000-0000-4000-8000-0000000000ff")!
    let id: UUID
    let name: String
    let description: String?
    let displayOrder: Int

    enum CodingKeys: String, CodingKey {
        case id, name, description
        case displayOrder = "display_order"
    }
}

struct KioskComplaintSelection {
    private(set) var items: [KioskComplaint] = []
    var note = ""

    var needsNote: Bool {
        items.contains { $0.id == KioskComplaint.otherID } && note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var ready: Bool { !items.isEmpty && !needsNote }

    mutating func toggle(_ item: KioskComplaint, language: AppLanguage) -> String? {
        if let index = items.firstIndex(where: { $0.id == item.id }) {
            items.remove(at: index)
        } else {
            guard items.count < 5 else { return language.text("intake.selectComplaint.maxReached", args: ["max": "5"]) }
            let proposed = Self.names(items + [item], language: language)
            if !items.isEmpty && item.id != KioskComplaint.otherID && proposed.unicodeScalars.count > 160 {
                return language.text("intake.selectComplaint.nameLimitReached")
            }
            items.append(item)
        }
        return nil
    }

    mutating func relocalize(from fresh: [KioskComplaint]) {
        items = items.compactMap { selected in fresh.first { $0.id == selected.id } }
    }

    private static func names(_ items: [KioskComplaint], language: AppLanguage) -> String {
        items.filter { $0.id != KioskComplaint.otherID }.map(\.name)
            .joined(separator: language.text("intake.selectComplaint.nameSeparator"))
    }

    func complaintText(language: AppLanguage) -> String {
        let names = Self.names(items, language: language)
        let custom = note.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !custom.isEmpty else { return String(names.unicodeScalars.prefix(200)) }
        guard !names.isEmpty else { return String(custom.unicodeScalars.prefix(200)) }
        let cjk = language == .traditionalChinese || language == .japanese
        let open = cjk ? "（" : " ("
        let close = cjk ? "）" : ")"
        let room = 200 - names.unicodeScalars.count - open.unicodeScalars.count - close.unicodeScalars.count
        guard room > 0 else { return String(names.unicodeScalars.prefix(200)) }
        return names + open + String(custom.unicodeScalars.prefix(room)) + close
    }
}

struct IntakeAnswer<Row> {
    var denied = false {
        didSet { if denied { rows.removeAll() } }
    }
    var rows: [Row] = []
}

struct KioskIntake {
    struct Allergy: Identifiable {
        let id = UUID()
        var name = ""
        var hospitalized = false
    }

    struct Medication: Identifiable {
        let id = UUID()
        var name = ""
        var frequency = "onceDaily"
    }

    struct History: Identifiable {
        let id = UUID()
        var condition = ""
        var yearsAgo = "unsure"
        var stillHas = true
    }

    struct Family: Identifiable {
        let id = UUID()
        var condition = ""
        var relation = "father"
    }

    var allergies = IntakeAnswer<Allergy>()
    var medications = IntakeAnswer<Medication>()
    var history = IntakeAnswer<History>()
    var family = IntakeAnswer<Family>()

    func payload(language: AppLanguage) -> [String: Any] {
        func entries<Row>(_ answer: IntakeAnswer<Row>, value: KeyPath<Row, String>,
                          project: (Row, String) -> [String: Any]) -> [[String: Any]] {
            guard !answer.denied else { return [] }
            return answer.rows.compactMap { row in
                let text = row[keyPath: value].trimmingCharacters(in: .whitespacesAndNewlines)
                return text.isEmpty ? nil : project(row, text)
            }
        }

        return [
            "no_known_allergies": allergies.denied,
            "allergies": entries(allergies, value: \.name) { row, name in
                var fields: [String: Any] = ["allergen": name, "had_hospitalization": row.hospitalized]
                if row.hospitalized {
                    fields["reaction"] = language.text("intake.medicalInfo.allergy.hospitalized")
                    fields["severity"] = "severe"
                }
                return fields
            },
            "no_current_medications": medications.denied,
            "current_medications": entries(medications, value: \.name) { row, name in
                ["name": name, "frequency": language.text("intake.medicalInfo.frequency.\(row.frequency)")]
            },
            "no_past_medical_history": history.denied,
            "medical_history": entries(history, value: \.condition) { row, condition in
                ["condition": condition, "years_ago": language.text("intake.medicalInfo.yearsAgo.\(row.yearsAgo)"), "still_has": row.stillHas]
            },
            "no_family_history": family.denied,
            "family_history": entries(family, value: \.condition) { row, condition in
                ["condition": condition, "relation": language.text("intake.medicalInfo.relations.\(row.relation)")]
            }
        ]
    }
}
