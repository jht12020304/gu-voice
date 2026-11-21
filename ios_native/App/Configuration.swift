import Foundation

struct Configuration: Sendable {
    let api: URL
    let webSocket: URL
    let web: URL

    init(settings: [String: Any]) throws {
        api = try Self.endpoint("API_BASE", in: settings, secure: "https", local: "http", suffix: "/api/v1")
        webSocket = try Self.endpoint("WS_BASE", in: settings, secure: "wss", local: "ws", suffix: "/api/v1/ws")
        web = try Self.endpoint("WEB_BASE", in: settings, secure: "https", local: "http", suffix: nil)
    }

    private static func endpoint(
        _ key: String, in settings: [String: Any], secure: String, local: String, suffix: String?
    ) throws -> URL {
        #if DEBUG
        let allowsLocal = true
        #else
        let allowsLocal = false
        #endif
        guard let value = settings[key] as? String,
              let url = URL(string: value), let host = url.host, !host.isEmpty,
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              url.scheme == secure || (allowsLocal && url.scheme == local && ["localhost", "127.0.0.1"].contains(host)),
              suffix == nil || url.path.hasSuffix(suffix ?? "") else {
            throw ConfigurationError.invalidEndpoint(key)
        }
        return url
    }

    func reportLink(sessionID: UUID, language: AppLanguage) -> URL {
        web.appendingPathComponent(language.rawValue)
            .appendingPathComponent("reports")
            .appendingPathComponent(sessionID.uuidString.lowercased())
    }

    enum ConfigurationError: Error, Equatable {
        case invalidEndpoint(String)
    }
}

enum AppLanguage: String, CaseIterable, Identifiable, Sendable {
    case traditionalChinese = "zh-TW"
    case english = "en-US"
    case japanese = "ja-JP"
    case korean = "ko-KR"
    case vietnamese = "vi-VN"

    var id: String { rawValue }

    var localization: String {
        switch self {
        case .traditionalChinese: "zh-Hant"
        case .english: "en-US"
        case .japanese: "ja"
        case .korean: "ko"
        case .vietnamese: "vi"
        }
    }

    var name: String { text("common.language.names.\(rawValue)") }

    static func resolve(saved: String, preferred: [String] = Locale.preferredLanguages) -> Self {
        if let explicit = Self(rawValue: saved) { return explicit }
        guard let first = preferred.first else { return .traditionalChinese }
        let code = Locale(identifier: first).language.languageCode?.identifier
        return allCases.first {
            Locale(identifier: $0.rawValue).language.languageCode?.identifier == code
        } ?? .traditionalChinese
    }

    func text(_ key: String) -> String {
        let bundle = Bundle.main.url(forResource: localization, withExtension: "lproj").flatMap(Bundle.init(url:))
        return (bundle ?? .main).localizedString(forKey: key, value: nil, table: nil)
    }
}
