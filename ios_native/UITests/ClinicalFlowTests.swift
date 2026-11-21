import XCTest

@MainActor
final class ClinicalFlowTests: XCTestCase {
    private let app = XCUIApplication()

    private func login(_ email: String, landingButton: String) throws {
        #if DEBUG && targetEnvironment(simulator)
        try XCTSkipUnless(ProcessInfo.processInfo.environment["CLINICAL_UI_TEST"] == "1",
                          "Local clinical fixture is opt-in.")
        continueAfterFailure = false
        app.launchArguments = ["-appLanguage", "en-US"]
        app.launchEnvironment["GUVOICE_DISABLE_REMOTE_PUSH"] = "1"
        app.launchEnvironment["GUVOICE_KIOSK_TEST_FIXTURE"] = "1"
        app.launch()
        let emailField = app.textFields["login-email"]
        if !emailField.waitForExistence(timeout: 5) {
            app.buttons["account-menu"].tap()
            let logout = app.buttons.matching(NSPredicate(format: "label == %@", "Log out")).firstMatch
            XCTAssertTrue(logout.waitForExistence(timeout: 5))
            logout.tap()
            XCTAssertTrue(emailField.waitForExistence(timeout: 15))
        }
        emailField.tap()
        emailField.typeText(email)
        app.secureTextFields["login-password"].tap()
        app.secureTextFields["login-password"].typeText("Kiosk-fixture9!\n")
        XCTAssertTrue(app.buttons[landingButton].waitForExistence(timeout: 20))
        #else
        throw XCTSkip("The local Docker clinical fixture requires a debug iOS simulator build.")
        #endif
    }

    func testDoctorReportActionsStayReachableFromMoreMenu() throws {
        try login("kiosk-doctor@example.com", landingButton: "SOAP reports")
        app.buttons["SOAP reports"].tap()
        let patient = app.staticTexts["Synthetic Patient"]
        XCTAssertTrue(patient.waitForExistence(timeout: 20))
        capture("doctor-reports")
        patient.tap()

        let more = app.buttons["secondary-actions-menu"]
        XCTAssertTrue(more.waitForExistence(timeout: 15))
        capture("report-detail")
        more.tap()

        // The SwiftUI dialog can expose a button nested in another button with the same identifier.
        let revision = app.buttons.matching(identifier: "report-reject").firstMatch
        let export = app.buttons.matching(identifier: "report-export").firstMatch
        let orders = app.buttons.matching(identifier: "report-quick-orders").firstMatch
        XCTAssertTrue(revision.waitForExistence(timeout: 10))
        XCTAssertTrue(revision.isHittable)
        XCTAssertTrue(export.isHittable)
        XCTAssertTrue(orders.isHittable)
        capture("report-detail-more")

        revision.tap()
        let reason = app.textFields.firstMatch
        XCTAssertTrue(app.navigationBars["Request Revision"].waitForExistence(timeout: 5))
        XCTAssertTrue(reason.exists)
        let submit = app.buttons["Request Revision"]
        XCTAssertFalse(submit.isEnabled)
        reason.tap()
        reason.typeText("   ")
        XCTAssertFalse(submit.isEnabled)
        reason.typeText("Needs clarification")
        XCTAssertTrue(submit.isEnabled)
        app.buttons["Cancel"].tap()

        more.tap()
        orders.tap()
        XCTAssertTrue(app.navigationBars["Quick orders"].waitForExistence(timeout: 10))
    }

    func testSystemAdminCanOpenManagementAndActionsMenu() throws {
        try login("kiosk-admin@example.com", landingButton: "User management")
        app.buttons["User management"].tap()
        XCTAssertTrue(app.navigationBars["User Management"].waitForExistence(timeout: 15))
        let actions = app.buttons.matching(NSPredicate(format: "label == %@", "Actions")).firstMatch
        XCTAssertTrue(actions.waitForExistence(timeout: 10))
        capture("admin-users")
        actions.tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label == %@", "Edit")).firstMatch.waitForExistence(timeout: 10))
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
