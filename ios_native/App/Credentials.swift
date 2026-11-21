import Foundation
import Security

struct Tokens: Codable, Equatable, Sendable {
    let access: String
    let refresh: String

    enum CodingKeys: String, CodingKey {
        case access = "access_token"
        case refresh = "refresh_token"
    }

    var isComplete: Bool { !access.isEmpty && !refresh.isEmpty }
}

struct Credentials: Sendable {
    static let flutterService = "flutter_secure_storage_service"
    private let service: String
    private let legacyService: String
    private let account = "tokens"

    init(service: String, legacyService: String = Self.flutterService) {
        self.service = service
        self.legacyService = legacyService
    }

    func load() throws -> Tokens? {
        if let data = try read(service: service, account: account) {
            let tokens = try JSONDecoder().decode(Tokens.self, from: data)
            try? removeLegacy()
            return tokens.isComplete ? tokens : nil
        }

        guard let access = try readLegacy("access_token"),
              let refresh = try readLegacy("refresh_token") else { return nil }
        let tokens = Tokens(access: access, refresh: refresh)
        guard tokens.isComplete else { return nil }
        do {
            try save(tokens)
        } catch {
            return nil
        }
        try? removeLegacy()
        return tokens
    }

    func save(_ tokens: Tokens) throws {
        let key = query(service: service, account: account, legacy: false)
        let data = try JSONEncoder().encode(tokens)
        let status = SecItemUpdate(key as CFDictionary, [kSecValueData: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = key
            item[kSecValueData] = data
            item[kSecAttrAccessible] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            try requireSuccess(SecItemAdd(item as CFDictionary, nil))
        } else {
            try requireSuccess(status)
        }
    }

    func clear() throws {
        try removeLegacy()
        try remove(service: service, account: account)
    }

    func removeLegacy() throws {
        try remove(service: legacyService, account: "access_token", legacy: true)
        try remove(service: legacyService, account: "refresh_token", legacy: true)
    }

    private func readLegacy(_ account: String) throws -> String? {
        try read(service: legacyService, account: account, legacy: true)
            .flatMap { String(data: $0, encoding: .utf8) }
    }

    private func query(service: String, account: String, legacy: Bool) -> [CFString: Any] {
        var key: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
        ]
        if legacy { key[kSecAttrSynchronizable] = kSecAttrSynchronizableAny }
        return key
    }

    private func read(service: String, account: String, legacy: Bool = false) throws -> Data? {
        var key = query(service: service, account: account, legacy: legacy)
        key[kSecReturnData] = true
        key[kSecMatchLimit] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(key as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        try requireSuccess(status)
        return result as? Data
    }

    private func remove(service: String, account: String, legacy: Bool = false) throws {
        let status = SecItemDelete(query(service: service, account: account, legacy: legacy) as CFDictionary)
        if status != errSecItemNotFound { try requireSuccess(status) }
    }

    private func requireSuccess(_ status: OSStatus) throws {
        guard status == errSecSuccess else { throw KeychainError(status: status) }
    }
}

struct KeychainError: Error, Equatable {
    let status: OSStatus
}
