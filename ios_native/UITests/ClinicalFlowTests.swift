import XCTest

@MainActor
final class ClinicalFlowTests: XCTestCase {
    private let app = XCUIApplication()

    private func login(_ email: String) throws {
        app.launchArguments = ["-appLanguage", "en-US"]
        app.launchEnvironment["GUVOICE_DISABLE_REMOTE_PUSH"] = "1"
        app.launch()
        let emailField = app.textFields["login-email"]
        if !emailField.waitForExistence(timeout: 5) {
            app.buttons["account-menu"].tap()
            app.buttons["sign-out"].tap()
            XCTAssertTrue(emailField.waitForExistence(timeout: 15))
        }
        emailField.tap()
        emailField.typeText(email)
        app.secureTextFields["login-password"].tap()
        app.secureTextFields["login-password"].typeText("Kiosk-fixture9!\n")
        XCTAssertTrue(app.buttons["SOAP reports"].waitForExistence(timeout: 20) || app.buttons["User management"].waitForExistence(timeout: 20))
    }

    func testDoctorReportActionsStayReachableFromMoreMenu() throws {
        try login("kiosk-doctor@example.com")
        app.buttons["SOAP reports"].tap()
        XCTAssertTrue(app.staticTexts["Synthetic Patient"].waitForExistence(timeout: 20))
        app.staticTexts["Synthetic Patient"].tap()
        XCTAssertTrue(app.buttons["secondary-actions-menu"].waitForExistence(timeout: 15))
        let more = app.buttons["More"]
        more.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        let menu = app.sheets.element
        let revision = menu.buttons["report-reject"]
        let export = menu.buttons["report-export"]
        let orders = menu.buttons["report-quick-orders"]
        XCTAssertTrue(revision.waitForExistence(timeout: 10))
        XCTAssertTrue(export.waitForExistence(timeout: 10))
        XCTAssertTrue(orders.waitForExistence(timeout: 10))
        revision.tap()
        let reason = app.textFields["Revision reason"]
        XCTAssertTrue(reason.waitForExistence(timeout: 5))
        let submit = app.buttons["Request Revision"]
        XCTAssertFalse(submit.isEnabled)
        reason.tap()
        reason.typeText("Needs clarification")
        XCTAssertTrue(submit.isEnabled)
        app.buttons["Cancel"].tap()
    }

    func testSystemAdminCanOpenManagementAndActionsMenu() throws {
        try login("kiosk-admin@example.com")
        app.buttons["User management"].tap()
        XCTAssertTrue(app.navigationBars["User Management"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label == %@", "Actions")).firstMatch.waitForExistence(timeout: 10))
    }
}
