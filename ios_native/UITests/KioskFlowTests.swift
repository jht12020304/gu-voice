import XCTest

@MainActor
final class KioskFlowTests: XCTestCase {
    private let app = XCUIApplication()

    private func launchFixture() throws {
        #if DEBUG && targetEnvironment(simulator)
        try XCTSkipUnless(ProcessInfo.processInfo.environment["KIOSK_UI_TEST"] == "1", "Local kiosk fixture is opt-in.")
        continueAfterFailure = false
        app.launchArguments = ["-appLanguage", "en-US"]
        app.launchEnvironment["GUVOICE_DISABLE_REMOTE_PUSH"] = "1"
        app.launchEnvironment["GUVOICE_KIOSK_TEST_FIXTURE"] = "1"
        app.launch()
        let email = app.textFields["login-email"]
        let start = app.buttons["kiosk-start"]
        wait(until: { email.exists || start.exists })
        if email.exists {
            email.tap()
            email.typeText("kiosk-patient@example.com")
            let password = app.secureTextFields["login-password"]
            password.tap()
            password.typeText("Kiosk-fixture9!\n")
        }
        XCTAssertTrue(start.waitForExistence(timeout: 20))
        #else
        throw XCTSkip("The local Docker kiosk fixture requires a debug iOS simulator build.")
        #endif
    }

    func testCompletedAfterTextReplyAndConfirmedEnd() throws {
        try launchFixture()
        enterConversation(verifyDraft: true)
        verifyAudioMenu()
        let answer = app.staticTexts.matching(NSPredicate(format: "label == %@", "How long have you felt this way?"))
        let greetingCount = answer.count
        let message = "I have needed to urinate more often for three days."
        send(message)
        XCTAssertTrue(app.staticTexts[message].waitForExistence(timeout: 15))
        wait(until: { answer.count > greetingCount })
        app.buttons["kiosk-end"].tap()
        let confirmation = app.alerts.buttons.matching(identifier: "kiosk-end-confirm").firstMatch
        XCTAssertTrue(confirmation.waitForExistence(timeout: 5))
        confirmation.tap()
        let terminal = element("kiosk-terminal-completed")
        XCTAssertTrue(terminal.waitForExistence(timeout: 40))
        wait(until: { !terminal.exists && self.app.buttons["kiosk-start"].isHittable })
    }

    func testCriticalRedFlagAbortsFromServerWithoutManualEnd() throws {
        try launchFixture()
        enterConversation()
        send("Two hours ago my left testicle suddenly started to hurt badly.")
        let terminal = element("kiosk-terminal-aborted_red_flag")
        XCTAssertTrue(terminal.waitForExistence(timeout: 60))
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "on-site clinical staff")).firstMatch.exists)
        app.buttons["kiosk-return"].tap()
        wait(until: { !terminal.exists && self.app.buttons["kiosk-start"].isHittable })
    }

    private func enterConversation(verifyDraft: Bool = false) {
        app.buttons["kiosk-start"].tap()
        let complaint = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "kiosk.complaint.")).firstMatch
        XCTAssertTrue(complaint.waitForExistence(timeout: 15))
        complaint.tap()
        app.buttons["kiosk.complaints.next"].tap()
        let name = app.textFields["kiosk.intake.name"]
        XCTAssertTrue(name.waitForExistence(timeout: 15))
        XCTAssertTrue(element("kiosk.intake.doctor").waitForExistence(timeout: 10),
                      "The fixture needs an active doctor with a nonempty department.")
        name.tap()
        name.typeText("Synthetic Kiosk QA")
        app.buttons["kiosk.intake.gender.male"].tap()
        let birthday = app.buttons["kiosk.intake.dob"]
        if !birthday.isHittable { app.swipeUp() }
        birthday.tap()
        app.buttons["kiosk.intake.dob.confirm"].tap()
        if verifyDraft {
            app.buttons["kiosk.intake.back"].tap()
            app.buttons["kiosk.complaints.next"].tap()
            XCTAssertTrue(element("kiosk.intake.doctor").waitForExistence(timeout: 10))
            XCTAssertEqual(name.value as? String, "Synthetic Kiosk QA")
        }
        app.buttons["kiosk.intake.submit"].tap()
        let field = element("kiosk-message")
        XCTAssertTrue(field.waitForExistence(timeout: 30))
        XCTAssertTrue(app.staticTexts["AI Assistant"].waitForExistence(timeout: 30))
    }

    private func verifyAudioMenu() {
        let more = app.buttons["secondary-actions-menu"]
        wait(until: { more.isHittable && more.isEnabled })
        more.tap()
        let mute = app.buttons.matching(identifier: "kiosk-tts-mute").firstMatch
        let speed = app.buttons.matching(identifier: "kiosk-tts-speed").firstMatch
        XCTAssertTrue(mute.waitForExistence(timeout: 5))
        XCTAssertTrue(speed.isHittable)
        let initialMuteLabel = mute.label
        let initialSpeedLabel = speed.label

        mute.tap()
        more.tap()
        XCTAssertNotEqual(mute.label, initialMuteLabel)
        speed.tap()
        more.tap()
        XCTAssertNotEqual(speed.label, initialSpeedLabel)
        mute.tap()
    }

    private func send(_ text: String) {
        let field = element("kiosk-message")
        field.tap()
        field.typeText(text)
        let send = app.buttons["kiosk-send"]
        wait(until: { send.isHittable && send.isEnabled })
        send.tap()
    }

    private func element(_ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    private func wait(until condition: @escaping () -> Bool, file: StaticString = #filePath, line: UInt = #line) {
        let predicate = NSPredicate { _, _ in condition() }
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 40), .completed, file: file, line: line)
    }
}
