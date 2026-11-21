import XCTest
@testable import GUVoice

@MainActor
final class KioskIdleTests: XCTestCase {
    func testIdleDeadlineMovesWithActivityAndExpiresAfterBackgroundTime() {
        let start = Date()
        let timer = KioskIdleTimer(setting: nil)
        timer.activity(at: start)
        XCTAssertEqual(timer.remaining(at: start), 180)
        timer.activity(at: start.addingTimeInterval(120))
        XCTAssertEqual(timer.remaining(at: start.addingTimeInterval(180)), 120)
        XCTAssertEqual(timer.remaining(at: start.addingTimeInterval(301)), 0)
        timer.cancel()
        XCTAssertNil(timer.remaining())
    }

    func testColdRestoreDoesNotExtendExpiredPatientLogin() {
        let suite = UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let patient = UUID()
        let start = Date()
        let firstLogin = KioskIdleTimer(setting: "180", defaults: defaults)
        firstLogin.start(patient: patient, restoring: false, at: start)
        let restored = KioskIdleTimer(setting: "180", defaults: defaults)
        let later = start.addingTimeInterval(181)
        restored.start(patient: patient, restoring: true, at: later)
        restored.activity(at: later)
        XCTAssertEqual(restored.remaining(at: later), 0)
        restored.start(patient: UUID(), restoring: true, at: later)
        XCTAssertEqual(restored.remaining(at: later), 180)
    }

    func testZeroDisablesDeadline() {
        let timer = KioskIdleTimer(setting: "0")
        timer.activity()
        XCTAssertNil(timer.remaining())
    }
}
