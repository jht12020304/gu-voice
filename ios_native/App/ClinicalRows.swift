import Foundation

struct ClinicalRows {
    struct Row: Identifiable {
        let id: String
        let label: String
        let content: String
    }

    let language: AppLanguage
    let section: String

    private static let fieldOrder = [
        "chief_complaint", "hpi", "onset", "location", "duration", "severity", "characteristics",
        "timing", "context", "aggravating_factors", "relieving_factors", "associated_symptoms",
        "past_medical_history", "medication_history", "medications", "allergies", "family_history",
        "review_of_systems", "system_review", "social_history",
        "vital_signs", "physical_exam", "lab_results", "imaging_results",
        "clinical_impression", "differential_diagnoses", "diagnosis", "likelihood", "reasoning",
        "urgency", "recommended_tests", "test_name", "rationale", "clinical_reasoning",
        "treatments", "follow_up", "referrals", "patient_education", "diagnostic_reasoning"
    ]

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
        let order = Self.fieldOrder
        return values.keys.sorted { lhs, rhs in
            let left = rank(for: lhs, order: order)
            let right = rank(for: rhs, order: order)
            return left == right ? lhs < rhs : left < right
        }.compactMap { key in
            guard let value = values[key], let text = render(value, key: key) else { return nil }
            let canonical = normalized(key)
            let labelKey = section == "plan" && canonical == "medications"
                ? "native.soap.recommendedMedications" : Self.labels[canonical]
            let label = labelKey.map(language.text) ?? canonical.replacingOccurrences(of: "_", with: " ").capitalized
            return Row(id: key, label: label, content: text)
        }
    }

    private func rank(for key: String, order: [String]) -> Int {
        let name = normalized(key)
        if section == "plan", name == "medications" {
            return order.firstIndex(of: "treatments") ?? order.count
        }
        return order.firstIndex(of: name) ?? order.count
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
