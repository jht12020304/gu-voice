import Foundation
import Security
import XCTest
@testable import GUVoice

@MainActor
final class FoundationTests: XCTestCase {
    private let native = "test.guvoice.native.\(UUID())"
    private let legacy = "test.guvoice.flutter.\(UUID())"
    private let sessionID = UUID(uuidString: "81CA2E05-33CA-48AA-8E60-486F3AB22035")!
    private var credentials: Credentials { Credentials(service: native, legacyService: legacy) }

    override func tearDown() async throws {
        try await MainActor.run {
            try credentials.clear()
            try credentials.savePushBinding(nil)
            credentials.finishFlutterPushMigration()
        }
    }

    func testKeychainMigratesFlutterItemsAndLogoutDoesNotRestoreThem() throws {
        let pair = Tokens(access: "old-access", refresh: "old-refresh")
        try seedFlutter(pair.access, account: "access_token")
        try seedFlutter(pair.refresh, account: "refresh_token")
        XCTAssertEqual(try credentials.load(), pair)
        XCTAssertEqual(try credentials.load(), pair)
        XCTAssertEqual(SecItemCopyMatching(flutterKey("access_token") as CFDictionary, nil), errSecItemNotFound)
        XCTAssertEqual(SecItemCopyMatching(flutterKey("refresh_token") as CFDictionary, nil), errSecItemNotFound)
        try credentials.clear()
        XCTAssertNil(try credentials.load())
    }

    func testIncompleteFlutterKeychainReturnsLoginState() throws {
        XCTAssertNil(try credentials.load())
        try seedFlutter("old-access", account: "access_token")
        XCTAssertNil(try credentials.load())
        XCTAssertEqual(SecItemCopyMatching(flutterKey("access_token") as CFDictionary, nil), errSecSuccess)
    }

    func testFlutterSignInReplacesOlderNativeAccountAfterRollback() throws {
        XCTAssertEqual(Credentials.flutterService, "flutter_secure_storage_service")
        try credentials.save(Tokens(access: "native-a", refresh: "native-a-refresh"))
        let newer = Tokens(access: "flutter-b", refresh: "flutter-b-refresh")
        try seedFlutter(newer.access, account: "access_token")
        try seedFlutter(newer.refresh, account: "refresh_token")
        XCTAssertEqual(try credentials.load(), newer)
        XCTAssertEqual(try credentials.load(), newer)
        XCTAssertEqual(SecItemCopyMatching(flutterKey("access_token") as CFDictionary, nil), errSecItemNotFound)
    }

    func testColdLaunchCannotReuseAnUnpersistedRotation() throws {
        try credentials.save(Tokens(access: "expired", refresh: "consumed"))
        credentials.markUnpersistedRotation()
        XCTAssertNil(try credentials.load())
        XCTAssertNil(try credentials.load())
    }

    func testCredentialReadErrorShowsLoginWithoutSendingARequest() async throws {
        let storage = FailingCredentials(base: credentials, failingLoad: FailureOnce())
        let api = try makeClient(storage: storage) { _ in .status(500) }
        let account = Account(api: api)
        await account.restore(.english)
        guard case .signedOut = account.state else { return XCTFail("Expected the login screen") }
        XCTAssertTrue(account.credentialsUnavailable)
        XCTAssertEqual(HTTPStub.routes.count("me"), 0)
        XCTAssertEqual(try credentials.load(), Tokens(access: "old-access", refresh: "old-refresh"))
    }

    func testRestoringAnIdlePatientRevokesLoginBeforeShowingTheirRecords() async throws {
        let patient = UUID()
        let profile = #"{"id":"\#(patient)","name":"Fixture","role":"patient"}"#
        let api = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(profile)
            case "logout": .status(204)
            default: .status(500)
            }
        }
        let account = Account(api: api)
        account.kioskIdle.start(patient: patient, restoring: false, at: Date(timeIntervalSince1970: 0))
        defer { account.kioskIdle.clear() }
        await account.restore(.english)
        guard case .signedOut = account.state else { return XCTFail("Expired kiosk restored patient access") }
        XCTAssertNil(try credentials.load())
        XCTAssertEqual(HTTPStub.routes.count("logout"), 1)
    }

    func testWrongCurrentPasswordPreservesPatientLoginWithoutRefreshing() async throws {
        let api = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "change-password": .status(401, body: #"{"error":{"code":"INVALID_CREDENTIALS"}}"#)
            default: .status(500)
            }
        }
        _ = try await api.restore(language: .english)
        do {
            _ = try await api.request("auth/change-password", language: .english, method: "POST", body: Data("{}".utf8))
            XCTFail("Expected a rejected current password")
        } catch APIError.incorrectCurrentPassword {}
        XCTAssertEqual(HTTPStub.routes.count("refresh"), 0)
        let signedIn = await api.hasSession
        XCTAssertTrue(signedIn)
    }

    func testLocalDayQueryPreservesDSTOffsetsAndPositiveOffsetEncoding() async throws {
        let api = try makeClient { request in
            request.url?.lastPathComponent == "me" ? .json(Self.user) : .json("42")
        }
        _ = try await api.restore(language: .english)
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: "America/New_York"))
        let start = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 3, day: 8)))
        let end = try XCTUnwrap(calendar.date(byAdding: .day, value: 1, to: start))
        let range = LocalDateRange(start: start, end: end, calendar: calendar)
        XCTAssertEqual(range.query[0].value, "2026-03-08T00:00:00.000000-05:00")
        XCTAssertEqual(range.query[1].value, "2026-03-08T23:59:59.999999-04:00")

        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: "Asia/Taipei"))
        let taipeiStart = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 8, day: 1)))
        let taipeiEnd = try XCTUnwrap(calendar.date(byAdding: .day, value: 1, to: taipeiStart))
        let taipei = LocalDateRange(start: taipeiStart, end: taipeiEnd, calendar: calendar)
        let _: Int = try await api.get("sessions", language: .english, query: taipei.query)
        let url = try XCTUnwrap(HTTPStub.routes.requests("sessions").first?.url?.absoluteString)
        XCTAssertTrue(url.contains("2026-08-01T00:00:00.000000%2B08:00"), url)
        XCTAssertTrue(url.contains("2026-08-01T23:59:59.999999%2B08:00"), url)
    }

    func testOfflinePushCleanupSurvivesRestartAndDoesNotRestoreDoctor() async throws {
        let api = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "fcm-token": .json("{}")
            case "unbind": HTTPStub.routes.count("unbind") == 1 ? .json("{}") : .status(503)
            default: .status(500)
            }
        }
        _ = try await api.restore(language: .english)
        try await api.registerPush(user: sessionID, token: "old-fcm", apnsToken: "abcd", language: .english)
        do {
            try await api.signOut(language: .english)
            XCTFail("Expected cleanup to remain pending")
        } catch is PushCleanupPending {}
        XCTAssertTrue(try XCTUnwrap(credentials.loadPushBinding()).isSigningOut)
        XCTAssertNotNil(try credentials.load())
        XCTAssertEqual(HTTPStub.routes.count("logout"), 0)

        let restarted = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "unbind", "logout": .json("{}")
            default: .status(500)
            }
        }
        let account = Account(api: restarted)
        await account.restore(.english)
        guard case .signedOut = account.state else { return XCTFail("Expected ordinary login after cleanup") }
        XCTAssertEqual(HTTPStub.routes.count("unbind"), 1)
        XCTAssertEqual(HTTPStub.routes.count("logout"), 1)
        XCTAssertNil(try credentials.loadPushBinding())
        XCTAssertNil(try credentials.load())
    }

    func testLegacyDeviceWithoutAPNsUsesRecoveryCodeOrCachedFCM() async throws {
        let pending = PushBinding(userID: sessionID, isSigningOut: true, requiresLegacyLookup: true)
        try credentials.savePushBinding(pending)
        let api = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "unbind": .status(409)
            default: .status(500)
            }
        }
        let account = Account(api: api)
        await account.restore(.english)
        guard case let .deviceRecovery(id) = account.state else { return XCTFail("Expected device recovery") }
        XCTAssertEqual(id, pending.id)
        XCTAssertEqual(try credentials.loadPushBinding()?.id, pending.id)
        XCTAssertEqual(HTTPStub.routes.count("logout"), 0)

        try await api.captureLegacyDevice(apnsToken: nil, fcmToken: "flutter-cached-fcm")
        XCTAssertEqual(try credentials.loadPushBinding()?.tokens, ["flutter-cached-fcm"])
        HTTPStub.routes.configure { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "unbind", "logout": .json("{}")
            default: .status(500)
            }
        }
        await account.signOut(.english)
        guard case .signedOut = account.state else { return XCTFail("Expected login after device cleanup") }
        XCTAssertNil(try credentials.loadPushBinding())
    }

    func testOlderBackendCannotCreateNativePushBinding() async throws {
        let api = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "unbind": .status(404)
            case "logout": .json("{}")
            default: .status(500)
            }
        }
        _ = try await api.restore(language: .english)
        do {
            try await api.registerPush(user: sessionID, token: "token", apnsToken: "abcd", language: .english)
            XCTFail("Expected push registration to wait for the backend upgrade")
        } catch is PushBackendUpgradeRequired {}
        XCTAssertEqual(HTTPStub.routes.count("fcm-token"), 0)
        XCTAssertNil(try credentials.loadPushBinding())
        try await api.signOut(language: .english)
        XCTAssertEqual(HTTPStub.routes.count("logout"), 1)
    }

    func testExpiredPendingPushCleanupRequiresOriginalAccount() async throws {
        try credentials.savePushBinding(PushBinding(userID: sessionID, tokens: ["token"], isSigningOut: true))
        let old = try makeClient { _ in .status(401) }
        let account = Account(api: old)
        await account.restore(.english)
        guard case .reauthenticate = account.state else { return XCTFail("Expected the recovery login") }

        HTTPStub.routes.configure { request in
            switch request.url?.lastPathComponent {
            case "login":
                .json(#"{"access_token":"another-access","refresh_token":"another-refresh","user":{"id":"0C42BF15-71CE-4B2B-9640-631D74F233B8","name":"Other","role":"doctor"}}"#)
            case "logout": .json("{}")
            default: .status(500)
            }
        }
        do {
            try await account.signIn(email: "b@example.com", password: "test", language: .english)
            XCTFail("A different account must not clear the binding")
        } catch is PushCleanupReauthentication {}
        XCTAssertEqual(HTTPStub.routes.count("unbind"), 0)
        XCTAssertTrue(try XCTUnwrap(credentials.loadPushBinding()).isSigningOut)

        HTTPStub.routes.configure { request in
            switch request.url?.lastPathComponent {
            case "login": .json(#"{"access_token":"new-access","refresh_token":"new-refresh","user":"# + Self.user + "}")
            case "me": .json(Self.user)
            case "unbind", "logout": .json("{}")
            default: .status(500)
            }
        }
        try await account.signIn(email: "a@example.com", password: "test", language: .english)
        guard case .signedOut = account.state else { return XCTFail("Recovery sign-in must finish on the ordinary login") }
        XCTAssertNil(try credentials.loadPushBinding())
    }

    func testClinicalAnalyticsRequiresBackendCapability() throws {
        func user(role: User.Role, license: String?, allowed: Bool?) throws -> User {
            let profile: [String: Any] = [
                "id": sessionID.uuidString, "name": "Fixture", "role": role.rawValue,
                "license_number": license.map { $0 as Any } ?? NSNull(),
                "can_read_audit_and_research": allowed.map { $0 as Any } ?? NSNull(),
            ]
            return try JSONDecoder().decode(User.self, from: JSONSerialization.data(withJSONObject: profile))
        }

        XCTAssertFalse(try user(role: .doctor, license: "QA", allowed: nil).canOpenAuditAndResearch)
        XCTAssertTrue(try user(role: .doctor, license: "QA", allowed: true).canOpenAuditAndResearch)
        XCTAssertTrue(try user(role: .admin, license: "QA", allowed: true).canOpenAuditAndResearch)
        XCTAssertFalse(try user(role: .admin, license: "", allowed: false).isSystemAdmin)
        XCTAssertTrue(try user(role: .admin, license: nil, allowed: true).isSystemAdmin)
    }

    func testReportReadyPayloadOpensOrdersAndAlertTakesPriority() {
        let id = sessionID.uuidString
        XCTAssertEqual(NotificationRoute(type: nil, sessionID: id, alertID: nil, reportID: id), .order(sessionID))
        XCTAssertEqual(NotificationRoute(type: "red_flag", sessionID: id, alertID: id, reportID: nil), .alert(sessionID))
        XCTAssertNil(NotificationRoute(type: "report_ready", sessionID: "invalid", alertID: nil, reportID: id))
    }

    func testConcurrentUnauthorizedRequestsRotateOnceAndPersistPair() async throws {
        let api = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "refresh":
                request.value(forHTTPHeaderField: "Cookie") == nil
                    && Self.refreshBody(request) == "old-refresh"
                    ? .json(Self.rotatedTokens) : .status(403)
            case "protected":
                request.value(forHTTPHeaderField: "Authorization") == "Bearer new-access"
                    ? .json("42") : .status(401)
            default: .status(500)
            }
        }
        _ = try await api.restore(language: .english)
        async let first: Int = api.get("protected", language: .english)
        async let second: Int = api.get("protected", language: .english)
        let result = try await [first, second]
        XCTAssertEqual(result, [42, 42])
        XCTAssertEqual(HTTPStub.routes.count("refresh"), 1)
        XCTAssertEqual(try credentials.load(), Tokens(access: "new-access", refresh: "new-refresh"))
    }

    func testInvalidRefreshClearsPersistedCredentials() async throws {
        let api = try makeClient { _ in .status(401) }
        let restored = try await api.restore(language: .english)
        XCTAssertNil(restored)
        XCTAssertNil(try credentials.load())
    }

    func testTransientRefreshErrorKeepsCredentialsForRetry() async throws {
        let api = try makeClient { request in
            request.url?.lastPathComponent == "refresh" ? .status(503) : .status(401)
        }
        do {
            _ = try await api.restore(language: .english)
            XCTFail("Expected an unavailable session")
        } catch APIError.status(503) {}
        XCTAssertEqual(try credentials.load(), Tokens(access: "old-access", refresh: "old-refresh"))
    }

    func testLogoutUsesTheRotatedRefreshTokenAndSendsNoCookies() async throws {
        let api = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "refresh": .json(Self.rotatedTokens)
            case "logout":
                if request.value(forHTTPHeaderField: "Authorization") == "Bearer old-access" { .status(401) }
                else { .json("{}") }
            default: .status(500)
            }
        }
        _ = try await api.restore(language: .english)
        try await api.signOut(language: .english)
        let logoutRequests = HTTPStub.routes.requests("logout")
        XCTAssertEqual(logoutRequests.map(Self.refreshBody), ["old-refresh", "new-refresh"])
        XCTAssertEqual(logoutRequests.last?.value(forHTTPHeaderField: "Authorization"), "Bearer new-access")
        XCTAssertTrue(logoutRequests.allSatisfy { $0.value(forHTTPHeaderField: "Cookie") == nil })
        XCTAssertNil(try credentials.load())
    }

    func testLogoutStillRevokesWhenLocalClearFailsAndRetriesRemoteFailure() async throws {
        let storage = FailingCredentials(base: credentials, failingClear: FailureOnce())
        let api = try makeClient(storage: storage) { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "logout": .status(503)
            default: .status(500)
            }
        }
        _ = try await api.restore(language: .english)
        do {
            try await api.signOut(language: .english)
            XCTFail("Expected the local clear to fail")
        } catch let error as KeychainError {
            XCTAssertEqual(error.status, errSecInteractionNotAllowed)
        }
        XCTAssertEqual(HTTPStub.routes.count("logout"), 1)
        let signedIn = await api.hasSession
        XCTAssertFalse(signedIn)

        HTTPStub.routes.configure { _ in .json("{}") }
        try await api.signOut(language: .english)
        XCTAssertEqual(HTTPStub.routes.count("logout"), 1)
        XCTAssertNil(try credentials.load())
    }

    func testLogoutDuringRotationRevokesTheNewPairAndDropsTheOldRequest() async throws {
        let allowRotation = DispatchSemaphore(value: 0)
        let api = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "refresh":
                allowRotation.wait(timeout: .now() + 5) == .success
                    ? .json(Self.rotatedTokens) : .status(503)
            case "protected": .status(401)
            case "logout": .json("{}")
            default: .status(500)
            }
        }
        _ = try await api.restore(language: .english)
        let request = Task { () -> Int in try await api.get("protected", language: .english) }
        for _ in 0..<100 where HTTPStub.routes.count("refresh") == 0 {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(HTTPStub.routes.count("refresh"), 1)
        let logout = Task { try await api.signOut(language: .english) }
        for _ in 0..<100 {
            if !(await api.hasSession) { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        allowRotation.signal()
        try await logout.value
        do {
            _ = try await request.value
            XCTFail("The request crossed an account change")
        } catch APIError.signedOut {}
        XCTAssertEqual(HTTPStub.routes.requests("logout").map(Self.refreshBody), ["new-refresh"])
        XCTAssertNil(try credentials.load())
    }

    func testFailedRotationWriteDoesNotFailTheRequestAndIsRetried() async throws {
        let storage = FailingCredentials(base: credentials, failingSave: FailureOnce())
        let api = try makeClient(storage: storage) { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "refresh": .json(Self.rotatedTokens)
            case "protected":
                request.value(forHTTPHeaderField: "Authorization") == "Bearer new-access"
                    ? .json("42") : .status(401)
            default: .status(500)
            }
        }
        _ = try await api.restore(language: .english)
        let first: Int = try await api.get("protected", language: .english)
        let second: Int = try await api.get("protected", language: .english)
        XCTAssertEqual(first, 42)
        XCTAssertEqual(second, 42)
        XCTAssertEqual(HTTPStub.routes.count("refresh"), 1)
        XCTAssertEqual(try credentials.load(), Tokens(access: "new-access", refresh: "new-refresh"))
    }

    func testDisabledAccountCannotRestoreFromMeOrRefresh() async throws {
        for initialStatus in [401, 403] {
            let api = try makeClient { request in
                request.url?.lastPathComponent == "me" ? .status(initialStatus) : .status(403)
            }
            let restored = try await api.restore(language: .english)
            XCTAssertNil(restored)
            XCTAssertNil(try credentials.load())
        }
    }

    func testPartialLoadsCannotTurnFailureIntoNoRedFlags() async throws {
        let api = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "alerts": .status(503)
            case "report": .status(404)
            case "conversations": .json(Self.emptyPage)
            default: .json(#"{"red_flag":true,"red_flag_reason":"Fixture"}"#)
            }
        }
        _ = try await api.restore(language: .english)
        let details = await Reports(api: api, language: .english).details(for: sessionID)
        XCTAssertEqual(details.redFlagStatus, .flagged)
        guard case .failed = details.alerts else { return XCTFail("Expected an alerts error") }
        guard case .loaded(nil) = details.report else { return XCTFail("Expected an unavailable report") }

        HTTPStub.routes.configure { request in
            if request.url?.lastPathComponent == "alerts" { .json(Self.emptyPage) }
            else { .status(503) }
        }
        let unavailable = await Reports(api: api, language: .english).details(for: sessionID)
        XCTAssertEqual(unavailable.redFlagStatus, .unavailable)
        guard case .failed = unavailable.session else { return XCTFail("Expected a session error") }
        guard case .failed = unavailable.transcript else { return XCTFail("Expected a transcript error") }

        HTTPStub.routes.configure { request in
            request.url?.lastPathComponent == "alerts" ? .json(Self.emptyPage) : .json(#"{"red_flag":false}"#)
        }
        let clear = await Reports(api: api, language: .english).details(for: sessionID)
        XCTAssertEqual(clear.redFlagStatus, .clear)
    }

    func testClinicalMessagesInterpolateInEveryLanguage() {
        for language in AppLanguage.allCases {
            for (key, argument) in [
                ("common.patientList.newPatientsInMonth", "month"),
                ("common.doctor.patient.deleteConfirm", "name"),
                ("dashboard.alert.triggerLabel", "value"),
                ("soap.quickOrders.lastOrdered", "time"),
            ] {
                let message = language.text(key, args: [argument: "fixture"])
                XCTAssertTrue(message.contains("fixture"), "\(language.rawValue) \(key)")
                XCTAssertFalse(message.contains("{{"), "\(language.rawValue) \(key)")
            }
            XCTAssertNotEqual(language.text("native.researchGender"), "native.researchGender")
            XCTAssertNotEqual(language.text("native.pushDeviceRecovery"), "native.pushDeviceRecovery")
        }
    }

    func testRevisionRequiresNonblankReasonAndSendsOneWrite() async throws {
        let record = """
        {"id":"\(sessionID)","session_id":"\(sessionID)","created_at":"2026-08-01T00:00:00Z",
        "status":"generated","review_status":"pending"}
        """
        let api = try makeClient { request in
            switch request.url?.lastPathComponent {
            case "me": .json(Self.user)
            case "review":
                .json(record.replacingOccurrences(of: #""pending""#, with: #""revision_needed","review_notes":"Reason""#))
            default: .json(record)
            }
        }
        _ = try await api.restore(language: .english)
        let report: Report = try await api.get("reports/\(sessionID)", language: .english)
        let reports = Reports(api: api, language: .english)
        do {
            _ = try await reports.review(report, decision: .revisionNeeded, notes: "   \n")
            XCTFail("Whitespace is not a revision reason")
        } catch APIError.invalidResponse {}
        XCTAssertEqual(HTTPStub.routes.count("review"), 0)

        let reviewed = try await reports.review(report, decision: .revisionNeeded, notes: "  Reason  ")
        XCTAssertEqual(reviewed.reviewStatus, .revisionNeeded)
        XCTAssertEqual(reviewed.reviewNotes, "Reason")
        XCTAssertEqual(HTTPStub.routes.requests("review").map(\.httpMethod), ["PUT"])
    }

    func testReportDecodesDatesDecimalsAndPreservesClinicalKeys() async throws {
        let dates = ["2026-08-01T00:00:00.123456Z", "2026-08-01T08:00:00.123456+08:00",
                     "2026-08-01T00:00:00Z", "2026-08-01T00:00:00+00:00"]
        let ids = dates.map { _ in UUID().uuidString }
        let list = zip(dates, ids).map { date, id in
            """
            {"id":"\(id)","session_id":"\(id)","created_at":"\(date)","status":"generated",
             "review_status":"pending","ai_confidence_score":0.87,"subjective":{"chief_complaint":"test"}}
            """
        }.joined(separator: ",")
        let payload = """
        {"data":[\(list)],"pagination":{"has_more":true,"next_cursor":"a+b="}}
        """
        let api = try makeClient {
            $0.url?.lastPathComponent == "me" ? .json(Self.user) : .json(payload)
        }
        _ = try await api.restore(language: .english)
        let reports = Reports(api: api, language: .japanese)
        let page = try await reports.page(after: nil)
        XCTAssertEqual(page.data.map(\.confidence), Array(repeating: Decimal(string: "0.87"), count: 4))
        XCTAssertEqual(page.data[0].createdAt, page.data[1].createdAt)
        XCTAssertEqual(page.data[2].createdAt, page.data[3].createdAt)
        guard case .text("test")? = page.data.first?.subjective?["chief_complaint"] else {
            return XCTFail("Expected the JSONB field name as sent")
        }
        var seen = Set<String>()
        let cursor = try page.continuation(seen: &seen)
        XCTAssertThrowsError(try page.continuation(seen: &seen))
        _ = try await reports.page(after: cursor)
        let request = try XCTUnwrap(HTTPStub.routes.requests("reports").last)
        let url = try XCTUnwrap(request.url)
        XCTAssertEqual(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, "a+b=")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Accept-Language"), "ja-JP")
    }

    func testLanguageAndReportLink() throws {
        XCTAssertEqual(AppLanguage.resolve(saved: "", preferred: ["ja-JP"]), .japanese)
        XCTAssertEqual(AppLanguage.resolve(saved: "", preferred: ["fr-FR", "en-US"]), .traditionalChinese)
        XCTAssertEqual(AppLanguage.resolve(saved: "ko-KR", preferred: ["en-US"]), .korean)
        let config = try Configuration(settings: Self.settings)
        XCTAssertEqual(config.reportLink(sessionID: sessionID, language: .vietnamese).absoluteString,
                       "http://127.0.0.1/vi-VN/reports/81ca2e05-33ca-48aa-8e60-486f3ab22035")
        var malformed = Self.settings
        malformed["API_BASE"] = "https:"
        XCTAssertThrowsError(try Configuration(settings: malformed))
        malformed["API_BASE"] = "https://gu.zymomed.com"
        XCTAssertThrowsError(try Configuration(settings: malformed))
    }

    func testEveryCatalogKeyExistsInAllFiveBuiltLocalizations() throws {
        var expected: Set<String>?
        for language in AppLanguage.allCases {
            let url = try XCTUnwrap(Bundle.main.url(
                forResource: "Localizable", withExtension: "strings", subdirectory: nil,
                localization: language.localization
            ))
            let bundle = try XCTUnwrap(Bundle.main.url(forResource: language.localization, withExtension: "lproj"))
            XCTAssertEqual(url.deletingLastPathComponent(), bundle)
            let catalog = try XCTUnwrap(PropertyListSerialization.propertyList(
                from: Data(contentsOf: url), format: nil
            ) as? [String: String])
            XCTAssertGreaterThan(catalog.count, 50)
            XCTAssertFalse(catalog.values.contains(where: \.isEmpty))
            XCTAssertEqual(Set(catalog.keys), expected ?? Set(catalog.keys))
            expected = Set(catalog.keys)
        }
        XCTAssertEqual(AppLanguage.traditionalChinese.text("common.login.submit"), "登入")
        XCTAssertEqual(AppLanguage.english.text("common.login.submit"), "Sign in")
    }

    private func flutterKey(_ account: String) -> [CFString: Any] {
        [kSecClass: kSecClassGenericPassword, kSecAttrService: legacy, kSecAttrAccount: account]
    }

    private func seedFlutter(_ token: String, account: String) throws {
        var item = flutterKey(account)
        item[kSecAttrAccessible] = kSecAttrAccessibleWhenUnlocked
        item[kSecValueData] = Data(token.utf8)
        XCTAssertEqual(SecItemAdd(item as CFDictionary, nil), errSecSuccess)
    }

    private func makeClient(
        storage: (any CredentialStore)? = nil, _ handler: @escaping HTTPStub.Handler
    ) throws -> APIClient {
        try credentials.save(Tokens(access: "old-access", refresh: "old-refresh"))
        HTTPStub.routes.configure(handler)
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HTTPStub.self]
        return try APIClient(configuration: Configuration(settings: Self.settings), credentials: storage ?? credentials,
                             session: URLSession(configuration: config))
    }

    private nonisolated static let settings = [
        "API_BASE": "http://127.0.0.1:8000/api/v1",
        "WS_BASE": "ws://127.0.0.1:8000/api/v1/ws",
        "WEB_BASE": "http://127.0.0.1"
    ]
    private nonisolated static let user = #"{"id":"81CA2E05-33CA-48AA-8E60-486F3AB22035","name":"Doctor","role":"doctor"}"#
    private nonisolated static let rotatedTokens = #"{"access_token":"new-access","refresh_token":"new-refresh"}"#
    private nonisolated static let emptyPage = #"{"data":[],"pagination":{"has_more":false,"next_cursor":null}}"#

    private nonisolated static func refreshBody(_ request: URLRequest) -> String? {
        guard let stream = request.httpBodyStream else {
            return decodeRefresh(request.httpBody)
        }
        stream.open()
        defer { stream.close() }
        var bytes = [UInt8](repeating: 0, count: 4096)
        let count = stream.read(&bytes, maxLength: bytes.count)
        return count > 0 ? decodeRefresh(Data(bytes.prefix(count))) : nil
    }

    private nonisolated static func decodeRefresh(_ data: Data?) -> String? {
        guard let data else { return nil }
        return (try? JSONDecoder().decode([String: String].self, from: data))?["refresh_token"]
    }
}

private struct FailingCredentials: CredentialStore {
    let base: Credentials
    var failingSave: FailureOnce?
    var failingClear: FailureOnce?
    var failingLoad: FailureOnce?

    func load() throws -> Tokens? {
        try failingLoad?.check()
        return try base.load()
    }
    func save(_ tokens: Tokens) throws {
        try failingSave?.check()
        try base.save(tokens)
    }
    func markUnpersistedRotation() { base.markUnpersistedRotation() }
    func clear() throws {
        try failingClear?.check()
        try base.clear()
    }
    func removeLegacy() throws { try base.removeLegacy() }
    func loadPushBinding() throws -> PushBinding? { try base.loadPushBinding() }
    func savePushBinding(_ binding: PushBinding?) throws { try base.savePushBinding(binding) }
    var migratedFromFlutter: Bool { base.migratedFromFlutter }
    func finishFlutterPushMigration() { base.finishFlutterPushMigration() }
}

private final class FailureOnce: @unchecked Sendable {
    private let lock = NSLock()
    private var remaining = true

    func check() throws {
        try lock.withLock {
            if remaining {
                remaining = false
                throw KeychainError(status: errSecInteractionNotAllowed)
            }
        }
    }
}

private final class HTTPStub: URLProtocol, @unchecked Sendable {
    enum Reply {
        case json(String)
        case status(Int, body: String = "")
    }

    typealias Handler = @Sendable (URLRequest) -> Reply
    static let routes = Routes()

    final class Routes: @unchecked Sendable {
        private let lock = NSLock()
        private var handler: Handler = { _ in .status(500) }
        private var received: [URLRequest] = []

        func configure(_ handler: @escaping Handler) {
            lock.withLock {
                self.handler = handler
                received = []
            }
        }

        func respond(to request: URLRequest) -> Reply {
            let handler = lock.withLock {
                received.append(request)
                return self.handler
            }
            return handler(request)
        }

        func requests(_ lastPathComponent: String) -> [URLRequest] {
            lock.withLock { received.filter { $0.url?.lastPathComponent == lastPathComponent } }
        }

        func count(_ lastPathComponent: String) -> Int {
            requests(lastPathComponent).count
        }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url else { return }
        let status: Int
        let data: Data
        switch Self.routes.respond(to: request) {
        case let .json(body):
            status = 200
            data = Data(body.utf8)
        case let .status(code, body):
            status = code
            data = Data(body.utf8)
        }
        guard let response = HTTPURLResponse(
            url: url, statusCode: status, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json", "Set-Cookie": "refresh_token=should-not-be-sent; Path=/"]
        ) else { return }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
