import XCTest

final class LocalizationTests: XCTestCase {
    func testKioskStringsHaveIdenticalFiveLocaleKeySets() throws {
        let app = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("App")
        let locales = ["en-US", "zh-Hant", "ja", "ko", "vi"]
        let keySets = try locales.map { locale -> Set<String> in
            let text = try String(contentsOf: app.appendingPathComponent("\(locale).lproj/Kiosk.strings"), encoding: .utf8)
            return Set(text.split(separator: "\n").compactMap { line in
                let parts = line.split(separator: "=", maxSplits: 1)
                guard parts.count == 2, parts[0].trimmingCharacters(in: .whitespaces).hasPrefix("\"") else { return nil }
                return parts[0].trimmingCharacters(in: .whitespaces).trimmingCharacters(in: CharacterSet(charactersIn: "\""))
            })
        }
        XCTAssertTrue(keySets.dropFirst().allSatisfy { $0 == keySets[0] })
    }

    func testCatalogEntriesHaveAllFiveLocales() throws {
        let app = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("App")
        let data = try Data(contentsOf: app.appendingPathComponent("Localizable.xcstrings"))
        let root = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let strings = try XCTUnwrap(root["strings"] as? [String: Any])
        let locales = Set(["en-US", "zh-Hant", "ja", "ko", "vi"])
        for (key, raw) in strings {
            let entry = try XCTUnwrap(raw as? [String: Any], "Invalid entry \(key)")
            let localizations = try XCTUnwrap(entry["localizations"] as? [String: Any], "Missing localizations \(key)")
            XCTAssertEqual(Set(localizations.keys), locales, "Incomplete localization \(key)")
        }
    }
}
