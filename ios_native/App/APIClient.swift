import Foundation

enum APIError: Error, Equatable {
    case status(Int)
    case invalidResponse
    case signedOut
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
    private let credentials: Credentials
    private let session: URLSession
    private var tokens: Tokens?
    private var revision = 0
    private var refreshTask: (id: UUID, task: Task<Tokens, Error>)?
    private var signingOut = false

    var hasSession: Bool { tokens != nil }

    init(configuration: Configuration, credentials: Credentials, session: URLSession = APIClient.makeSession()) {
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
        if tokens == nil { tokens = try credentials.load() }
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
        try credentials.save(pair)
        try? credentials.removeLegacy()
        revision += 1
        tokens = pair
        return user
    }

    func signOut(language: AppLanguage) async throws {
        guard !signingOut else { return }
        signingOut = true
        defer { signingOut = false }
        let current = tokens
        let pending = refreshTask?.task
        revision += 1
        tokens = nil
        refreshTask = nil
        try credentials.clear()

        var pair = current
        if let pending, let rotated = try? await pending.value { pair = rotated }
        guard let pair else { return }
        do {
            try await revoke(pair, language: language)
        } catch APIError.status(401) {
            if let newPair = try? await rotate(pair, language: language) {
                try? await revoke(newPair, language: language)
            }
        } catch {
            // The local account is already cleared even when the server is unreachable.
        }
    }

    func get<Value: Decodable & Sendable>(
        _ path: String, language: AppLanguage, query: [URLQueryItem] = []
    ) async throws -> Value {
        guard let pair = tokens else { throw APIError.signedOut }
        let requestRevision = revision
        let data: Data
        do {
            data = try await send(path, language: language, query: query, access: pair.access)
        } catch APIError.status(401) {
            let fresh = try await refresh(after: pair, revision: requestRevision, language: language)
            do {
                data = try await send(path, language: language, query: query, access: fresh.access)
            } catch APIError.status(401) {
                if requestRevision == revision, tokens == fresh { try discard() }
                throw APIError.signedOut
            }
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
                if error as? APIError == .status(401) {
                    try discard()
                    throw APIError.signedOut
                }
            }
            throw error
        }

        guard revision == expected, let active = tokens else { throw APIError.signedOut }
        if active != rejected { return active }
        // Keep the server's rotated pair in memory if Keychain is temporarily unavailable.
        tokens = rotated
        refreshTask = nil
        try credentials.save(rotated)
        return rotated
    }

    private func discard() throws {
        revision += 1
        tokens = nil
        refreshTask = nil
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
