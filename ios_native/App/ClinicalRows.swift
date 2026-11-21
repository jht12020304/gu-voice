import Foundation

struct ClinicalRows {
    struct Row: Identifiable {
        let id: String
        let label: String
        let content: String
    }

    let language: AppLanguage

    private static let labels: [String: String] = [
        "chief_complaint": "soap.subjective.chiefComplaint",
        "hpi": "soap.subjective.hpi.title",
        "onset": "soap.subjective.hpi.onset",
        "location": "soap.subjective.hpi.location",
        "duration": "soap.subjective.hpi.duration",
        "characteristics": "soap.subjective.hpi.characteristics",
        "severity": "soap.subjective.hpi.severity",
        "timing": "soap.subjective.hpi.timing",
        "context": "soap.subjective.hpi.context",
        "aggravating_factors": "soap.subjective.hpi.aggravatingFactors",
        "relieving_factors": "soap.subjective.hpi.relievingFactors",
        "associated_symptoms": "soap.subjective.hpi.associatedSymptoms",
        "past_medical_history": "soap.subjective.pastMedicalHistory.title",
        "medications": "soap.subjective.medicationHistory.title",
        "medication_history": "soap.subjective.medicationHistory.title",
        "allergies": "native.soap.allergies",
        "family_history": "native.soap.familyHistory",
        "social_history": "soap.subjective.socialHistory.title",
        "review_of_systems": "soap.subjective.systemReview.title",
        "system_review": "soap.subjective.systemReview.title",
        "vital_signs": "soap.objective.vitalSigns.title",
        "physical_exam": "soap.objective.physicalExam.title",
        "lab_results": "soap.objective.labResults.title",
        "imaging_results": "native.soap.imaging",
        "clinical_impression": "soap.assessment.clinicalImpression",
        "differential_diagnoses": "soap.assessment.differentialDiagnoses.title",
        "diagnosis": "soap.diagnosis.title",
        "likelihood": "native.soap.likelihood",
        "reasoning": "soap.plan.diagnosticReasoning",
        "recommended_tests": "soap.plan.recommendedTests.title",
        "test_name": "soap.objective.labResults.columns.test",
        "rationale": "native.soap.rationale",
        "clinical_reasoning": "soap.plan.diagnosticReasoning",
        "treatments": "soap.plan.treatments.title",
        "follow_up": "soap.plan.followUp.title",
        "patient_education": "soap.plan.patientEducation.title",
        "referrals": "soap.plan.referrals.title",
        "diagnostic_reasoning": "soap.plan.diagnosticReasoning",
        "urgency": "native.soap.urgency"
    ]

    func fields(_ values: [String: ClinicalValue]) -> [Row] {
        let leading = ["chief_complaint", "hpi", "clinical_impression", "urgency", "test_name", "diagnosis"]
        return values.keys.sorted { lhs, rhs in
            let left = leading.firstIndex(of: normalized(lhs)) ?? leading.count
            let right = leading.firstIndex(of: normalized(rhs)) ?? leading.count
            return left == right ? lhs < rhs : left < right
        }.compactMap { key in
            guard let value = values[key], let text = render(value, key: key) else { return nil }
            let canonical = normalized(key)
            let label = Self.labels[canonical].map(language.text) ?? canonical.replacingOccurrences(of: "_", with: " ").capitalized
            return Row(id: key, label: label, content: text)
        }
    }

    private func normalized(_ key: String) -> String {
        key.replacingOccurrences(of: "([a-z0-9])([A-Z])", with: "$1_$2", options: .regularExpression).lowercased()
    }

    private func render(_ value: ClinicalValue, key: String) -> String? {
        switch value {
        case .null: return nil
        case let .text(text):
            if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return nil }
            if normalized(key) == "urgency", ["er_now", "24h", "this_week", "routine"].contains(text) {
                return language.text("soap.plan.urgency.\(text)")
            }
            if normalized(key) == "likelihood", ["high", "medium", "moderate", "low"].contains(text) {
                return language.text("soap.assessment.probability.\(text == "moderate" ? "medium" : text)")
            }
            return text
        case let .number(number):
            return number.formatted(.number.locale(Locale(identifier: language.rawValue)))
        case let .bool(flag):
            return language.text(flag ? "native.yes" : "native.no")
        case let .object(object):
            let rows = fields(object)
            return rows.isEmpty ? nil : rows.map { "\($0.label) · \($0.content)" }.joined(separator: "\n")
        case let .array(array):
            let items = array.compactMap { render($0, key: key) }
            return items.isEmpty ? nil : items.joined(separator: "\n\n")
        }
    }
}
