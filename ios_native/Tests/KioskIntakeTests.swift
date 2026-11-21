import XCTest
@testable import GUVoice

final class KioskIntakeTests: XCTestCase {
    func testUnansweredExplicitDenialAndPositiveHistoryForAllFourTopics() throws {
        var intake = KioskIntake()
        let keys = [
            ("no_known_allergies", "allergies"), ("no_current_medications", "current_medications"),
            ("no_past_medical_history", "medical_history"), ("no_family_history", "family_history")
        ]
        func check(_ denied: Bool, count: Int, line: UInt = #line) throws {
            // Read the actual wire representation rather than the form's checkbox values.
            let data = try JSONSerialization.data(withJSONObject: intake.payload(language: .english))
            let body = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            for (flag, items) in keys {
                XCTAssertEqual(body[flag] as? Bool, denied, line: line)
                XCTAssertEqual((body[items] as? [[String: Any]])?.count, count, line: line)
            }
        }

        intake.allergies.rows.append(.init(name: " "))
        intake.medications.rows.append(.init())
        intake.history.rows.append(.init())
        intake.family.rows.append(.init())
        try check(false, count: 0)
        intake.allergies.rows.append(.init(name: " peanut ", hospitalized: true))
        intake.medications.rows.append(.init(name: "aspirin"))
        intake.history.rows.append(.init(condition: "diabetes"))
        intake.family.rows.append(.init(condition: "cancer"))
        try check(false, count: 1)
        let data = intake.payload(language: .english)
        let allergies = try XCTUnwrap(data["allergies"] as? [[String: Any]])
        XCTAssertEqual(allergies.first?["allergen"] as? String, "peanut")
        XCTAssertEqual(allergies.first?["severity"] as? String, "severe")
        let family = try XCTUnwrap(data["family_history"] as? [[String: String]])
        XCTAssertEqual(family, [["condition": "cancer", "relation": "Father"]])

        intake.allergies.denied = true
        intake.medications.denied = true
        intake.history.denied = true
        intake.family.denied = true
        try check(true, count: 0)
        intake.allergies.denied = false
        intake.medications.denied = false
        intake.history.denied = false
        intake.family.denied = false
        try check(false, count: 0)
    }

    func testOtherNeedsFreeTextAndLocalizedNamesKeepTheirOrderWithinScalarBudget() {
        var picks = KioskComplaintSelection()
        let other = KioskComplaint(id: KioskComplaint.otherID, name: "Other", description: nil, displayOrder: 10)
        let pain = KioskComplaint(id: UUID(), name: "Pain", description: nil, displayOrder: 1)
        XCTAssertNil(picks.toggle(other, language: .english))
        XCTAssertNil(picks.toggle(pain, language: .english))
        XCTAssertFalse(picks.ready)
        picks.note = String(repeating: "🧑🏽", count: 120)
        XCTAssertTrue(picks.ready)
        let translated = KioskComplaint(id: pain.id, name: "疼痛", description: nil, displayOrder: 1)
        picks.relocalize(from: [translated, other])
        XCTAssertEqual(picks.items.map(\.id), [other.id, pain.id])
        let result = picks.complaintText(language: .traditionalChinese)
        XCTAssertTrue(result.hasPrefix("疼痛（"))
        XCTAssertTrue(result.hasSuffix("）"))
        XCTAssertEqual(result.unicodeScalars.count, 200)
    }
}
