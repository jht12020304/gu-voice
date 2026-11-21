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
        try await MainActor.run { try credentials.clear() }
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
        let cursor = try page.continuation(after: nil)
        _ = try await reports.page(after: cursor)
        let request = try XCTUnwrap(HTTPStub.routes.requests("reports").last)
        let url = try XCTUnwrap(request.url)
        XCTAssertEqual(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, "a+b=")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Accept-Language"), "ja-JP")
    }

    func testLanguageAndReportLink() throws {
        XCTAssertEqual(AppLanguage.resolve(saved: "", preferred: ["ja-JP"]), .japanese)
        XCTAssertEqual(AppLanguage.resolve(saved: "", preferred: ["fr-FR"]), .traditionalChinese)
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

    private func makeClient(_ handler: @escaping HTTPStub.Handler) throws -> APIClient {
        try credentials.save(Tokens(access: "old-access", refresh: "old-refresh"))
        HTTPStub.routes.configure(handler)
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HTTPStub.self]
        return try APIClient(configuration: Configuration(settings: Self.settings), credentials: credentials,
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

private final class HTTPStub: URLProtocol, @unchecked Sendable {
    enum Reply {
        case json(String)
        case status(Int)
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
        case let .status(code):
            status = code
            data = Data()
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
