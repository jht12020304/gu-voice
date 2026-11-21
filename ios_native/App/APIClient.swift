import Foundation

enum APIError: Error, Equatable {
    case status(Int)
    case invalidResponse
    case signedOut
    case credentialsUnavailable
}

struct User: Decodable, Sendable {
    let id: UUID
    let name: String
    let role: Role

    enum Role: String, Decodable, Sendable {
        case doctor, admin, patient
    }
}

actor APIClient {
    let configuration: Configuration
    private let credentials: any CredentialStore
    private let session: URLSession
    private var tokens: Tokens?
    private var revision = 0
    private var refreshTask: (id: UUID, task: Task<Tokens, Error>)?
    private var signingOut = false
    private var pendingRevocation: Tokens?
    private var needsPersistence = false

    var hasSession: Bool { tokens != nil }

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
        if tokens == nil {
            do { tokens = try credentials.load() }
            catch let error as CredentialClearancePending { throw error }
            catch { throw APIError.credentialsUnavailable }
        }
        guard tokens != nil else { return nil }
        do {
            return try await get("auth/me", language: language)
        } catch APIError.signedOut {
            return nil
        }
    }

    func signIn(email: String, password: String, language: AppLanguage) async throws -> User {
        guard tokens == nil, !signingOut else { throw APIError.invalidResponse }
        let attempt = revision
        let body = try JSONEncoder().encode(["email": email, "password": password])
        let data = try await send("auth/login", language: language, body: body)
        let user = try Self.decoder().decode(UserEnvelope.self, from: data).user
        let pair = try decodeTokens(data)
        guard revision == attempt, !signingOut else { throw APIError.signedOut }
        try credentials.removeLegacy()
        try credentials.save(pair)
        revision += 1
        tokens = pair
        return user
    }

    func signOut(language: AppLanguage) async throws {
        guard !signingOut else { return }
        signingOut = true
        defer { signingOut = false }
        let current = tokens ?? pendingRevocation
        let pending = refreshTask?.task
        revision += 1
        tokens = nil
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

    private func revokeOnLogout(_ pair: Tokens, language: AppLanguage) async -> Tokens? {
        do {
            try await revoke(pair, language: language)
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
        guard let pair = tokens else { throw APIError.signedOut }
        if needsPersistence { persistRotation(pair) }
        let requestRevision = revision
        let data: Data
        do {
            data = try await send(path, language: language, query: query, access: pair.access)
        } catch APIError.status(401) {
            let fresh = try await refresh(after: pair, revision: requestRevision, language: language)
            do {
                data = try await send(path, language: language, query: query, access: fresh.access)
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
        return try Self.decoder().decode(Value.self, from: data)
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
        revision += 1
        tokens = nil
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
        access: String? = nil, body: Data? = nil
    ) async throws -> Data {
        let endpoint = configuration.api.appendingPathComponent(path)
        guard var parts = URLComponents(url: endpoint, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidResponse
        }
        if !query.isEmpty { parts.queryItems = query }
        guard let url = parts.url else { throw APIError.invalidResponse }

        var request = URLRequest(url: url)
        request.setValue(language.rawValue, forHTTPHeaderField: "Accept-Language")
        request.setValue(language.rawValue, forHTTPHeaderField: "X-Language")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpShouldHandleCookies = false
        if let access { request.setValue("Bearer \(access)", forHTTPHeaderField: "Authorization") }
        if let body {
            request.httpMethod = "POST"
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
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
