import Foundation

enum APIError: Error, Equatable {
    case status(Int)
    case invalidResponse
    case signedOut
    case credentialsUnavailable
    case incorrectCurrentPassword
}

struct User: Decodable, Sendable {
    let id: UUID
    let name: String
    let role: Role
    let licenseNumber: String?
    let canReadAuditAndResearch: Bool?

    var isSystemAdmin: Bool { role == .admin && licenseNumber == nil }
    var canOpenAuditAndResearch: Bool { isSystemAdmin || canReadAuditAndResearch == true }

    enum CodingKeys: String, CodingKey {
        case id, name, role
        case licenseNumber = "license_number"
        case canReadAuditAndResearch = "can_read_audit_and_research"
    }

    enum Role: String, Codable, CaseIterable, Sendable {
        case doctor, admin, patient
    }
}

actor APIClient {
    let configuration: Configuration
    private let credentials: any CredentialStore
    private let session: URLSession
    private var tokens: Tokens?
    private var userID: UUID?
    private var pushBinding: PushBinding?
    private var pushRegistration: Task<Data, Error>?
    private var revision = 0
    private var refreshTask: (id: UUID, task: Task<Tokens, Error>)?
    private var signingOut = false
    private var pendingRevocation: Tokens?
    private var needsPersistence = false

    var needsPushCleanup: Bool { pushBinding?.isSigningOut == true }
    var needsDeviceIdentity: Bool { pushBinding?.requiresLegacyLookup == true }

    var hasSession: Bool { tokens != nil && !signingOut && pushBinding?.isSigningOut != true }

    init(configuration: Configuration, credentials: any CredentialStore, session: URLSession = APIClient.makeSession()) {
        self.configuration = configuration
        self.credentials = credentials
        self.session = session
    }

    nonisolated static func makeSession() -> URLSession {
        let settings = URLSessionConfiguration.ephemeral
        settings.httpCookieStorage = nil
        settings.httpShouldSetCookies = false
        settings.httpCookieAcceptPolicy = .never
        settings.urlCache = nil
        settings.requestCachePolicy = .reloadIgnoringLocalCacheData
        settings.timeoutIntervalForRequest = 15
        return URLSession(configuration: settings, delegate: NoRedirects(), delegateQueue: nil)
    }

    func restore(language: AppLanguage) async throws -> User? {
        guard !signingOut else { throw APIError.signedOut }
        do { pushBinding = try credentials.loadPushBinding() }
        catch { throw APIError.credentialsUnavailable }
        if pushBinding?.isSigningOut == true { throw PushCleanupPending() }
        if tokens == nil {
            do { tokens = try credentials.load() }
            catch let error as CredentialClearancePending { throw error }
            catch { throw APIError.credentialsUnavailable }
        }
        guard tokens != nil else {
            if var binding = pushBinding {
                binding.isSigningOut = true
                try credentials.savePushBinding(binding)
                pushBinding = binding
                throw PushCleanupPending()
            }
            return nil
        }
        if credentials.migratedFromFlutter, pushBinding == nil, let previous = tokens?.previousClinicianID {
            // The server verifies ownership before using this locally retained identity.
            try storePushBinding(PushBinding(userID: previous, requiresLegacyLookup: true))
        }
        do {
            let user: User = try await get("auth/me", language: language)
            if var binding = pushBinding, binding.userID != user.id {
                binding.isSigningOut = true
                try credentials.savePushBinding(binding)
                pushBinding = binding
                tokens = nil
                revision += 1
                throw PushCleanupPending()
            }
            if credentials.migratedFromFlutter, user.role != .patient, pushBinding == nil {
                let binding = PushBinding(userID: user.id, requiresLegacyLookup: true)
                try credentials.savePushBinding(binding)
                pushBinding = binding
            }
            userID = user.id
            return user
        } catch APIError.signedOut {
            if needsPushCleanup { throw PushCleanupPending() }
            return nil
        }
    }

    func signIn(email: String, password: String, language: AppLanguage) async throws -> User {
        guard tokens == nil, !signingOut, pushBinding?.isSigningOut != true else { throw APIError.invalidResponse }
        let attempt = revision
        let body = try JSONEncoder().encode(["email": email, "password": password])
        let data = try await send("auth/login", language: language, body: body)
        let pair = try decodeTokens(data)
        let user: User
        let loginUser = try Self.decoder().decode(UserEnvelope.self, from: data).user
        if loginUser.role != .patient {
            let profile = try await send("auth/me", language: language, access: pair.access)
            user = try Self.decoder().decode(User.self, from: profile)
            guard user.id == loginUser.id else { throw APIError.invalidResponse }
        } else {
            user = loginUser
        }
        if var binding = pushBinding, binding.userID != user.id {
            _ = await revokeOnLogout(pair, language: language)
            binding.isSigningOut = true
            try storePushBinding(binding)
            throw PushCleanupPending()
        }
        guard revision == attempt, !signingOut else { throw APIError.signedOut }
        try credentials.removeLegacy()
        try credentials.save(pair)
        revision += 1
        tokens = pair
        userID = user.id
        return user
    }

    func dashboardConnection() async throws -> URLSessionWebSocketTask {
        try await authenticatedSocket(configuration.webSocket.appendingPathComponent("dashboard"))
    }

    func kioskSocket(for id: UUID, resume: String?) async throws -> any KioskSocket {
        var url = configuration.webSocket.appendingPathComponent("sessions/\(id.uuidString.lowercased())/stream")
        if let resume { url.append(queryItems: [URLQueryItem(name: "resumeFrom", value: resume)]) }
        return try await authenticatedSocket(url)
    }

    private func authenticatedSocket(_ url: URL) async throws -> URLSessionWebSocketTask {
        guard hasSession, let pair = tokens else { throw APIError.signedOut }
        let expected = revision
        let socket = session.webSocketTask(with: url)
        let data = try JSONEncoder().encode(["type": "auth", "token": pair.access])
        socket.resume()
        do {
            try await socket.send(.string(String(decoding: data, as: UTF8.self)))
            guard hasSession, revision == expected else { throw APIError.signedOut }
            return socket
        } catch {
            socket.cancel(with: .goingAway, reason: nil)
            throw error
        }
    }

    func registerPush(user: UUID, token: String, apnsToken: String, language: AppLanguage) async throws {
        guard user == userID, hasSession, pushRegistration == nil else { return }
        let expected = revision
        do {
            try await request("notifications/devices/unbind", language: language, method: "POST", body: Data("{}".utf8))
        } catch APIError.status(404), APIError.status(405) {
            throw PushBackendUpgradeRequired()
        }
        guard hasSession, revision == expected, userID == user, pushRegistration == nil else { return }
        var binding = pushBinding ?? PushBinding(userID: user)
        guard binding.userID == user else { throw PushCleanupPending() }
        binding.tokens.insert(token)
        binding.apnsToken = apnsToken
        binding.requiresLegacyLookup = false
        try storePushBinding(binding)

        let payload = ["device_token": token, "apns_token": apnsToken, "platform": "ios",
                       "binding_id": binding.id.uuidString.lowercased()]
        let body = try JSONEncoder().encode(payload)
        let task = Task {
            try await request("notifications/fcm-token", language: language, method: "POST", body: body)
        }
        pushRegistration = task
        defer { pushRegistration = nil }
        _ = try await task.value
        credentials.finishFlutterPushMigration()
    }

    func captureLegacyDevice(apnsToken: String?, fcmToken: String?) throws {
        guard var binding = pushBinding, binding.requiresLegacyLookup == true,
              apnsToken != nil || fcmToken?.isEmpty == false else { return }
        binding.apnsToken = apnsToken
        if let fcmToken, !fcmToken.isEmpty { binding.tokens.insert(fcmToken) }
        binding.requiresLegacyLookup = false
        try storePushBinding(binding)
    }

    func reauthenticateForPushCleanup(email: String, password: String, language: AppLanguage) async throws {
        guard !signingOut, let binding = pushBinding, binding.isSigningOut else { throw APIError.invalidResponse }
        signingOut = true
        defer { signingOut = false }

        let body = try JSONEncoder().encode(["email": email, "password": password])
        let data = try await send("auth/login", language: language, body: body)
        let user = try Self.decoder().decode(UserEnvelope.self, from: data).user
        let pair = try decodeTokens(data)
        guard user.id == binding.userID else {
            _ = await revokeOnLogout(pair, language: language)
            throw PushCleanupReauthentication()
        }
        try credentials.save(pair)
        try await completePushCleanup(binding, pair: pair, language: language)
    }

    func signOut(language: AppLanguage) async throws {
        guard !signingOut else { return }
        signingOut = true
        defer { signingOut = false }
        if pushBinding == nil { pushBinding = try credentials.loadPushBinding() }
        if var binding = pushBinding {
            binding.isSigningOut = true
            try credentials.savePushBinding(binding)
            pushBinding = binding
            let current = tokens
            let pending = refreshTask?.task
            revision += 1
            tokens = nil
            userID = nil
            refreshTask = nil
            needsPersistence = false
            _ = try? await pushRegistration?.value
            let pair: Tokens?
            if let pending, let rotated = try? await pending.value {
                try credentials.save(rotated)
                pair = rotated
            } else if let current {
                pair = current
            } else {
                pair = try credentials.load()
            }
            try await completePushCleanup(binding, pair: pair, language: language)
            return
        }
        let current = tokens ?? pendingRevocation
        let pending = refreshTask?.task
        revision += 1
        tokens = nil
        userID = nil
        refreshTask = nil
        needsPersistence = false
        pendingRevocation = nil
        let clearance = Result { try credentials.clear() }

        var pair = current
        if let pending, let rotated = try? await pending.value { pair = rotated }
        if let pair {
            let remaining = await revokeOnLogout(pair, language: language)
            if case .failure = clearance { pendingRevocation = remaining }
        }
        try clearance.get()
    }

    private func completePushCleanup(_ pending: PushBinding, pair: Tokens?, language: AppLanguage) async throws {
        var binding = pending
        var pair = pair
        if !binding.serverUnbound {
            guard var fresh = pair else { throw PushCleanupReauthentication() }
            do {
                do {
                    try await unbindPush(binding, using: fresh, language: language)
                } catch APIError.status(401) {
                    fresh = try await rotate(fresh, language: language)
                    try credentials.save(fresh)
                    try await unbindPush(binding, using: fresh, language: language)
                }
            } catch APIError.status(401), APIError.status(403) {
                throw PushCleanupReauthentication()
            } catch APIError.status(404), APIError.status(405) {
                throw PushBackendUpgradeRequired()
            } catch APIError.status(409) where binding.requiresLegacyLookup == true {
                throw PushDeviceRecoveryRequired(id: binding.id)
            } catch {
                throw PushCleanupPending()
            }
            pair = fresh
            binding.serverUnbound = true
            try storePushBinding(binding)
        }

        if let pair, let remaining = await revokeOnLogout(pair, language: language) {
            try credentials.save(remaining)
            throw PushCleanupPending()
        }
        try credentials.clear()
        try storePushBinding(nil)
        credentials.finishFlutterPushMigration()
    }

    private func unbindPush(_ binding: PushBinding, using pair: Tokens, language: AppLanguage) async throws {
        let profile = try await send("auth/me", language: language, access: pair.access)
        let user = try Self.decoder().decode(User.self, from: profile)
        guard user.id == binding.userID else { throw APIError.status(403) }
        let tokens = binding.tokens.sorted()
        for start in stride(from: 0, to: max(tokens.count, 1), by: 50) {
            let batch = Array(tokens[start..<min(start + 50, tokens.count)])
            let payload = UnbindPayload(
                device_tokens: batch, apns_token: binding.apnsToken,
                binding_id: binding.id, recovery_id: binding.requiresLegacyLookup == true ? binding.id : nil
            )
            let data = try JSONEncoder().encode(payload)
            _ = try await send("notifications/devices/unbind", language: language, access: pair.access, body: data)
        }
    }

    private struct UnbindPayload: Encodable {
        let device_tokens: [String]
        let apns_token: String?
        let binding_id: UUID
        let recovery_id: UUID?
    }

    private func storePushBinding(_ binding: PushBinding?) throws {
        try credentials.savePushBinding(binding)
        pushBinding = binding
    }

    private func revokeOnLogout(_ pair: Tokens, language: AppLanguage) async -> Tokens? {
        do {
            try await revoke(pair, language: language)
        } catch APIError.status(403) {
            return nil
        } catch APIError.status(401) {
            var latest = pair
            do {
                latest = try await rotate(pair, language: language)
                try await revoke(latest, language: language)
            } catch APIError.status(401), APIError.status(403) {
                return nil
            } catch {
                return latest
            }
        } catch {
            return pair
        }
        return nil
    }

    func get<Value: Decodable & Sendable>(
        _ path: String, language: AppLanguage, query: [URLQueryItem] = []
    ) async throws -> Value {
        let data = try await request(path, language: language, query: query)
        return try Self.decoder().decode(Value.self, from: data)
    }

    func write<Value: Decodable & Sendable, Body: Encodable & Sendable>(
        _ path: String, method: String, language: AppLanguage, body: Body
    ) async throws -> Value {
        let data = try await request(path, language: language, method: method, body: try JSONEncoder().encode(body))
        return try Self.decoder().decode(Value.self, from: data)
    }

    @discardableResult
    func request(
        _ path: String, language: AppLanguage, query: [URLQueryItem] = [],
        method: String = "GET", body: Data? = nil, accept: String = "application/json"
    ) async throws -> Data {
        guard hasSession, let pair = tokens else { throw APIError.signedOut }
        if needsPersistence { persistRotation(pair) }
        let requestRevision = revision
        let data: Data
        do {
            data = try await send(path, language: language, query: query, access: pair.access, body: body, method: method, accept: accept)
        } catch APIError.status(401) {
            let fresh = try await refresh(after: pair, revision: requestRevision, language: language)
            do {
                data = try await send(path, language: language, query: query, access: fresh.access, body: body, method: method, accept: accept)
            } catch let error as APIError
                where error == .status(401) || (path == "auth/me" && error == .status(403)) {
                if requestRevision == revision, tokens == fresh { try discard() }
                throw APIError.signedOut
            }
        } catch APIError.status(403) where path == "auth/me" {
            if requestRevision == revision { try discard() }
            throw APIError.signedOut
        }
        guard revision == requestRevision else { throw APIError.signedOut }
        try Task.checkCancellation()
        return data
    }

    private func refresh(after rejected: Tokens, revision expected: Int, language: AppLanguage) async throws -> Tokens {
        guard revision == expected, let current = tokens else { throw APIError.signedOut }
        if current != rejected { return current }

        let refresh = refreshTask ?? (UUID(), Task { try await rotate(current, language: language) })
        refreshTask = refresh
        let rotated: Tokens
        do {
            rotated = try await refresh.task.value
        } catch {
            guard revision == expected else { throw APIError.signedOut }
            if refreshTask?.id == refresh.id {
                refreshTask = nil
                if let failure = error as? APIError, [.status(401), .status(403)].contains(failure) {
                    try discard()
                    throw APIError.signedOut
                }
            }
            throw error
        }

        guard revision == expected, let active = tokens else { throw APIError.signedOut }
        if active != rejected { return active }
        tokens = rotated
        refreshTask = nil
        credentials.markUnpersistedRotation()
        persistRotation(rotated)
        return rotated
    }

    private func persistRotation(_ pair: Tokens) {
        do {
            try credentials.save(pair)
            needsPersistence = false
        } catch {
            needsPersistence = true
        }
    }

    private func discard() throws {
        if var binding = pushBinding {
            binding.isSigningOut = true
            try credentials.savePushBinding(binding)
            pushBinding = binding
        }
        revision += 1
        tokens = nil
        userID = nil
        refreshTask = nil
        needsPersistence = false
        try credentials.clear()
    }

    private func rotate(_ pair: Tokens, language: AppLanguage) async throws -> Tokens {
        let body = try JSONEncoder().encode(["refresh_token": pair.refresh])
        let data = try await send("auth/refresh", language: language, body: body)
        return try decodeTokens(data)
    }

    private func revoke(_ pair: Tokens, language: AppLanguage) async throws {
        let body = try JSONEncoder().encode(["refresh_token": pair.refresh])
        _ = try await send("auth/logout", language: language, access: pair.access, body: body)
    }

    private func decodeTokens(_ data: Data) throws -> Tokens {
        let pair = try Self.decoder().decode(Tokens.self, from: data)
        guard pair.isComplete else { throw APIError.invalidResponse }
        return pair
    }

    private func send(
        _ path: String, language: AppLanguage, query: [URLQueryItem] = [],
        access: String? = nil, body: Data? = nil, method: String? = nil, accept: String = "application/json"
    ) async throws -> Data {
        let endpoint = configuration.api.appendingPathComponent(path)
        guard var parts = URLComponents(url: endpoint, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidResponse
        }
        if !query.isEmpty {
            parts.queryItems = query
            parts.percentEncodedQuery = parts.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
        }
        guard let url = parts.url else { throw APIError.invalidResponse }

        var request = URLRequest(url: url)
        request.setValue(language.rawValue, forHTTPHeaderField: "Accept-Language")
        request.setValue(language.rawValue, forHTTPHeaderField: "X-Language")
        request.setValue(accept, forHTTPHeaderField: "Accept")
        request.httpShouldHandleCookies = false
        if let access { request.setValue("Bearer \(access)", forHTTPHeaderField: "Authorization") }
        request.httpMethod = method ?? (body == nil ? "GET" : "POST")
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        if path == "auth/change-password", http.statusCode == 401,
           let envelope = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let detail = envelope["error"] as? [String: Any], detail["code"] as? String == "INVALID_CREDENTIALS" {
            throw APIError.incorrectCurrentPassword
        }
        guard (200..<300).contains(http.statusCode) else { throw APIError.status(http.statusCode) }
        return data
    }

    private static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let string = try container.decode(String.self)
            let format = ISO8601DateFormatter()
            format.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = format.date(from: string) { return date }
            format.formatOptions = [.withInternetDateTime]
            if let date = format.date(from: string) { return date }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid ISO 8601 date")
        }
        return decoder
    }

    private struct UserEnvelope: Decodable {
        let user: User
    }

    private final class NoRedirects: NSObject, URLSessionTaskDelegate {
        func urlSession(
            _ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
            newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void
        ) {
            completionHandler(nil)
        }
    }
}
