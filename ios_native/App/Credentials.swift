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

struct PushBinding: Codable, Sendable {
    let userID: UUID
    var tokens: Set<String> = []
    var isSigningOut = false
    var requiresLegacyLookup: Bool?
    var apnsToken: String?
}

struct PushCleanupPending: Error {}
struct PushCleanupReauthentication: Error {}

protocol CredentialStore: Sendable {
    func load() throws -> Tokens?
    func save(_ tokens: Tokens) throws
    func markUnpersistedRotation()
    func clear() throws
    func removeLegacy() throws
    func loadPushBinding() throws -> PushBinding?
    func savePushBinding(_ binding: PushBinding?) throws
    var migratedFromFlutter: Bool { get }
    func finishFlutterPushMigration()
}

struct Credentials: CredentialStore {
    static let flutterService = "flutter_secure_storage_service"
    private let service: String
    private let legacyService: String
    private let account = "tokens"
    private var clearingKey: String { "\(service).clearing" }
    private var flutterMigrationKey: String { "\(service).flutterPushMigration" }
    var migratedFromFlutter: Bool { UserDefaults.standard.bool(forKey: flutterMigrationKey) }

    func finishFlutterPushMigration() { UserDefaults.standard.removeObject(forKey: flutterMigrationKey) }

    private var rotationKey: String { "\(service).rotationPending" }

    init(service: String, legacyService: String = Self.flutterService) {
        self.service = service
        self.legacyService = legacyService
    }

    func load() throws -> Tokens? {
        if UserDefaults.standard.bool(forKey: clearingKey) {
            do { try clear() }
            catch { throw CredentialClearancePending() }
            return nil
        }

        if let access = try readLegacy("access_token"),
           let refresh = try readLegacy("refresh_token") {
            let tokens = Tokens(access: access, refresh: refresh)
            if tokens.isComplete {
                UserDefaults.standard.set(true, forKey: flutterMigrationKey)
                do { try save(tokens) }
                catch { return nil }
                try removeLegacy()
                return tokens
            }
        }

        if UserDefaults.standard.bool(forKey: rotationKey) {
            try clear()
            return nil
        }
        guard let data = try read(service: service, account: account) else { return nil }
        let tokens = try JSONDecoder().decode(Tokens.self, from: data)
        return tokens.isComplete ? tokens : nil
    }

    func save(_ tokens: Tokens) throws {
        try saveData(JSONEncoder().encode(tokens), account: account)
        UserDefaults.standard.removeObject(forKey: rotationKey)
    }

    private func saveData(_ data: Data, account: String) throws {
        let key = query(service: service, account: account, legacy: false)
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

    func loadPushBinding() throws -> PushBinding? {
        guard let data = try read(service: service, account: "push-binding") else { return nil }
        return try JSONDecoder().decode(PushBinding.self, from: data)
    }

    func savePushBinding(_ binding: PushBinding?) throws {
        guard let binding else {
            try remove(service: service, account: "push-binding")
            return
        }
        try saveData(JSONEncoder().encode(binding), account: "push-binding")
    }

    func markUnpersistedRotation() {
        UserDefaults.standard.set(true, forKey: rotationKey)
    }

    func clear() throws {
        let defaults = UserDefaults.standard
        defaults.set(true, forKey: clearingKey)
        try removeLegacy()
        try remove(service: service, account: account)
        defaults.removeObject(forKey: rotationKey)
        defaults.removeObject(forKey: clearingKey)
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

struct CredentialClearancePending: Error {}
