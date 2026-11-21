import Foundation

struct Page<Item: Decodable & Sendable>: Decodable, Sendable {
    let data: [Item]
    let pagination: Pagination
    let reviewCounts: [String: Int]?

    enum CodingKeys: String, CodingKey {
        case data, pagination
        case reviewCounts = "review_counts"
    }

    struct Pagination: Decodable, Sendable {
        let nextCursor: String?
        let hasMore: Bool

        enum CodingKeys: String, CodingKey {
            case nextCursor = "next_cursor"
            case hasMore = "has_more"
        }
    }

    func continuation(seen: inout Set<String>) throws -> String? {
        guard pagination.hasMore else { return nil }
        guard let cursor = pagination.nextCursor, !cursor.isEmpty, seen.insert(cursor).inserted else {
            throw APIError.invalidResponse
        }
        return cursor
    }
}

struct Report: Decodable, Identifiable, Sendable {
    let id: UUID
    let sessionID: UUID
    let patientName: String?
    let chiefComplaint: String?
    let doctorName: String?
    let hasRedFlag: Bool?
    let summary: String?
    let confidence: Decimal?
    let createdAt: Date
    let generatedAt: Date?
    let status: Status
    let reviewNotes: String?
    let reviewStatus: Review
    let subjective: [String: ClinicalValue]?
    let objective: [String: ClinicalValue]?
    let assessment: [String: ClinicalValue]?
    let plan: [String: ClinicalValue]?
    let rawTranscript: String?
    let codes: [String]?

    enum Status: String, Decodable, Sendable { case generated, generating, failed }

    enum Review: String, Decodable, Sendable {
        case pending, approved
        case revisionNeeded = "revision_needed"
    }

    enum CodingKeys: String, CodingKey {
        case id, summary, status, subjective, objective, assessment, plan
        case sessionID = "session_id"
        case patientName = "patient_name"
        case chiefComplaint = "chief_complaint_text"
        case hasRedFlag = "session_red_flag"
        case doctorName = "doctor_name"
        case confidence = "ai_confidence_score"
        case createdAt = "created_at"
        case generatedAt = "generated_at"
        case reviewStatus = "review_status"
        case reviewNotes = "review_notes"
        case rawTranscript = "raw_transcript"
        case codes = "icd10_codes"
    }
}

struct ReportSession: Decodable, Sendable {
    let patientName: String?
    let chiefComplaint: String?
    let status: String?
    let redFlag: Bool
    let redFlagReason: String?

    enum CodingKeys: String, CodingKey {
        case patientName = "patient_name"
        case chiefComplaint = "chief_complaint_text"
        case status
        case redFlag = "red_flag"
        case redFlagReason = "red_flag_reason"
    }
}

struct ReportAlert: Decodable, Identifiable, Sendable {
    let id: UUID
    let title: String
    let severity: String
    let triggerReason: String

    enum CodingKeys: String, CodingKey {
        case id, title, severity
        case triggerReason = "trigger_reason"
    }
}

struct ConversationTurn: Decodable, Identifiable, Sendable {
    let id: UUID
    let sequence: Int
    let role: String
    let content: String
    let confidence: Decimal?

    enum CodingKeys: String, CodingKey {
        case id, role
        case sequence = "sequence_number"
        case content = "content_text"
        case confidence = "stt_confidence"
    }
}

enum ClinicalValue: Decodable, Sendable {
    case text(String), number(Decimal), bool(Bool), object([String: Self]), array([Self]), null

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() { self = .null }
        else if let text = try? value.decode(String.self) { self = .text(text) }
        else if let flag = try? value.decode(Bool.self) { self = .bool(flag) }
        else if let number = try? value.decode(Decimal.self) { self = .number(number) }
        else if let rows = try? value.decode([Self].self) { self = .array(rows) }
        else { self = .object(try value.decode([String: Self].self)) }
    }
}

enum Load<Value: Sendable>: Sendable {
    case loading
    case loaded(Value)
    case failed
    case signedOut

    static func fetch(_ operation: @Sendable () async throws -> Value) async -> Self {
        do { return .loaded(try await operation()) }
        catch APIError.signedOut { return .signedOut }
        catch { return .failed }
    }

    var value: Value? {
        if case let .loaded(value) = self { return value }
        return nil
    }

    var isLoading: Bool {
        if case .loading = self { return true }
        return false
    }

    var isSignedOut: Bool {
        if case .signedOut = self { return true }
        return false
    }
}

struct ReportDetails: Sendable {
    var session: Load<ReportSession> = .loading
    var report: Load<Report?> = .loading
    var alerts: Load<[ReportAlert]> = .loading
    var transcript: Load<[ConversationTurn]> = .loading

    enum RedFlagStatus: Equatable {
        case loading, flagged, clear, unavailable
    }

    var redFlagStatus: RedFlagStatus {
        if session.value?.redFlag == true || alerts.value?.isEmpty == false { return .flagged }
        if case .failed = session { return .unavailable }
        if case .failed = alerts { return .unavailable }
        if session.value != nil, alerts.value != nil { return .clear }
        return .loading
    }

    mutating func apply(_ update: ReportDetails) {
        if !update.session.isLoading { session = update.session }
        if !update.report.isLoading { report = update.report }
        if !update.alerts.isLoading { alerts = update.alerts }
        if !update.transcript.isLoading { transcript = update.transcript }
    }

    var isSignedOut: Bool {
        session.isSignedOut || report.isSignedOut || alerts.isSignedOut || transcript.isSignedOut
    }
}

struct Reports: Sendable {
    let api: APIClient
    let language: AppLanguage

    func page(after cursor: String?, review: String = "") async throws -> Page<Report> {
        var query = cursor.map { [URLQueryItem(name: "cursor", value: $0)] } ?? []
        if !review.isEmpty { query.append(.init(name: "review_status", value: review)) }
        return try await api.get("reports", language: language, query: query)
    }

    func review(_ report: Report, decision: Report.Review, notes: String) async throws -> Report {
        let notes = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        guard decision == .approved || decision == .revisionNeeded && !notes.isEmpty else {
            throw APIError.invalidResponse
        }
        let body = ReviewRequest(review_status: decision.rawValue, review_notes: notes.isEmpty ? nil : notes)
        return try await api.write("reports/\(report.id)/review", method: "PUT", language: language, body: body)
    }

    private struct ReviewRequest: Encodable, Sendable {
        let review_status: String
        let review_notes: String?
        let pending_only = true
    }

    func pdf(_ report: Report) async throws -> Data {
        let data = try await api.request(
            "reports/\(report.id)/pdf", language: language,
            query: [.init(name: "include_transcript", value: "true"), .init(name: "language", value: language.rawValue)],
            accept: "application/pdf"
        )
        guard data.starts(with: Data("%PDF-".utf8)) else { throw APIError.invalidResponse }
        return data
    }

    func generate(_ sessionID: UUID) async throws -> Report {
        try await api.write(
            "sessions/\(sessionID)/reports/generate", method: "POST", language: language, body: ["regenerate": true]
        )
    }

    private enum DetailUpdate: Sendable {
        case session(Load<ReportSession>)
        case report(Load<Report?>)
        case alerts(Load<[ReportAlert]>)
        case transcript(Load<[ConversationTurn]>)
    }

    func details(
        for id: UUID, onUpdate: (@MainActor @Sendable (ReportDetails) -> Void)? = nil
    ) async -> ReportDetails {
        let id = id.uuidString.lowercased()
        let sessionPath = "sessions/\(id)"
        return await withTaskGroup(of: DetailUpdate.self) { group in
            group.addTask {
                .session(await Load.fetch { try await api.get(sessionPath, language: language) })
            }
            group.addTask {
                .report(await Load.fetch {
                    do { return try await api.get("\(sessionPath)/report", language: language) }
                    catch APIError.status(404) { return nil }
                })
            }
            group.addTask {
                .alerts(await Load.fetch {
                    try await allPages("alerts", query: [URLQueryItem(name: "session_id", value: id)])
                })
            }
            group.addTask {
                .transcript(await Load.fetch {
                    let turns: [ConversationTurn] = try await allPages("\(sessionPath)/conversations")
                    return turns.sorted { $0.sequence < $1.sequence }
                })
            }

            var details = ReportDetails()
            for await update in group {
                switch update {
                case let .session(value): details.session = value
                case let .report(value): details.report = value
                case let .alerts(value): details.alerts = value
                case let .transcript(value): details.transcript = value
                }
                await onUpdate?(details)
            }
            return details
        }
    }

    private func allPages<Item: Decodable & Sendable>(
        _ path: String, query: [URLQueryItem] = []
    ) async throws -> [Item] {
        var items: [Item] = []
        var cursor: String?
        var seen = Set<String>()
        repeat {
            var parameters = query + [URLQueryItem(name: "limit", value: "100")]
            if let cursor { parameters.append(URLQueryItem(name: "cursor", value: cursor)) }
            let page: Page<Item> = try await api.get(path, language: language, query: parameters)
            items.append(contentsOf: page.data)
            cursor = try page.continuation(seen: &seen)
        } while cursor != nil
        return items
    }
}
