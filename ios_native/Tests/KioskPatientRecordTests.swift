import XCTest
@testable import GUVoice

final class KioskPatientRecordTests: XCTestCase {
    func testLocalizedEducationAcceptsStringAndArrayForSameSessionLanguage() throws {
        for education in [#""  advice  ""#, #"["advice", "", 4]"#] {
            let json = #"{"summary":"中文病歷","patient_facing_localized":{"language":"en","summary":" localized ","patientEducation":EDUCATION}}"#
                .replacingOccurrences(of: "EDUCATION", with: education)
            let report = try JSONDecoder().decode(KioskReportExcerpt.self, from: Data(json.utf8))
            XCTAssertEqual(KioskReportExcerpt.patientText(report, sessionLanguage: "en-US"), .content("localized", ["advice"]))
            XCTAssertEqual(KioskReportExcerpt.patientText(report, sessionLanguage: "ja-JP"), .notice)
        }
    }

    func testMissingTranslationOnlyReturnsNativeTextForChineseSession() throws {
        let json = #"{"summary":" 摘要 ","plan":{"patient_education":" 稍候看診 "},"review_notes":"private","patient_facing_localized":{"language":"vi","summary":"  ","patient_education":[null]}}"#
        let report = try JSONDecoder().decode(KioskReportExcerpt.self, from: Data(json.utf8))
        XCTAssertEqual(KioskReportExcerpt.patientText(report, sessionLanguage: "zh-Hant"), .content("摘要", ["稍候看診"]))
        for code in ["vi-VN", "ko-KR", "en-US"] { XCTAssertEqual(KioskReportExcerpt.patientText(report, sessionLanguage: code), .notice) }
    }

    func testUnknownSessionLanguageShowsOnlyTheGenericNoticeEvenWithAGeneratedReport() throws {
        let json = #"{"status":"generated","summary":"醫師摘要","patient_facing_localized":{"language":"vi","summary":"Tóm tắt"}}"#
        let report = try JSONDecoder().decode(KioskReportExcerpt.self, from: Data(json.utf8))
        for unknown in [nil, "", "  ", "und"] as [String?] {
            XCTAssertEqual(KioskReportExcerpt.patientText(report, sessionLanguage: unknown), .notice)
        }
    }

    func testMissingReportUsesSessionLanguageForFallback() {
        XCTAssertEqual(KioskReportExcerpt.patientText(nil, sessionLanguage: "vi-VN"), .notice)
        XCTAssertEqual(KioskReportExcerpt.patientText(nil, sessionLanguage: "zh-TW"), .content(nil, []))
    }

    func testClinicianNotesNeverBecomePatientAdvice() throws {
        let json = #"{"review_notes":"internal","icd10_codes":["X00"],"ai_confidence_score":0.9,"patient_facing_localized":17}"#
        let report = try JSONDecoder().decode(KioskReportExcerpt.self, from: Data(json.utf8))
        XCTAssertEqual(KioskReportExcerpt.patientText(report, sessionLanguage: "zh-TW"), .content(nil, []))
    }
}
