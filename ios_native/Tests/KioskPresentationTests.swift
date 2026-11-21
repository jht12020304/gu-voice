import XCTest
@testable import GUVoice

@MainActor
final class KioskPresentationTests: XCTestCase {
    private func session() throws -> KioskConversation {
        let configuration = try Configuration(settings: XCTUnwrap(Bundle.main.infoDictionary))
        let api = APIClient(configuration: configuration, credentials: Credentials(service: UUID().uuidString))
        return KioskConversation(id: UUID(), source: api, language: .english)
    }

    func testNextSessionStartsAudibleAtNormalSpeed() throws {
        let first = try session()
        first.toggleTTSMute()
        first.cycleTTSSpeed()
        XCTAssertTrue(first.ttsMuted)
        XCTAssertEqual(first.speed, 1.25)
        first.close()

        let next = try session()
        XCTAssertFalse(next.ttsMuted)
        XCTAssertEqual(next.speed, 1)
        for speed in [1.25, 1.5, 1] {
            next.cycleTTSSpeed()
            XCTAssertEqual(next.speed, speed)
        }
        next.close()
    }

    func testSharedNoticeUsesOnlyThreeVisibleFlagsAfterSeverityAndAcknowledgmentSorting() throws {
        let model = try session()
        defer { model.close() }

        func flag(_ id: String, severity: String, notice: String?) {
            var payload = ["alertId": id, "severity": severity]
            payload["patientNotice"] = notice
            model.receive("red_flag_alert", payload: payload)
        }

        XCTAssertNil(model.sharedVisibleNotice)
        flag("low", severity: "low", notice: "Different message")
        flag("medium", severity: "medium", notice: " On-site staff notified ")
        flag("high", severity: "high", notice: "On-site staff notified")
        flag("critical", severity: "critical", notice: "On-site staff notified")
        XCTAssertEqual(model.visibleFlags.map(\.id), ["critical", "high", "medium"])
        XCTAssertEqual(model.sharedVisibleNotice, "On-site staff notified")

        model.acknowledge("critical")
        XCTAssertEqual(model.visibleFlags.map(\.id), ["high", "medium", "low"])
        XCTAssertNil(model.sharedVisibleNotice)
        flag("low", severity: "low", notice: nil)
        XCTAssertNil(model.sharedVisibleNotice)
        flag("low", severity: "low", notice: " ")
        XCTAssertNil(model.sharedVisibleNotice)
    }
}
