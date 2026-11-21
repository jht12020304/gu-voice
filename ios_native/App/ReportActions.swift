import SwiftUI

final class ReportPDF: Identifiable {
    let url: URL

    init(data: Data, id: UUID) throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        url = folder.appendingPathComponent("soap-report-\(id.uuidString.lowercased()).pdf")
        do {
            try data.write(to: url, options: [.atomic, .completeFileProtection])
        } catch {
            try? FileManager.default.removeItem(at: folder)
            throw error
        }
    }

    deinit { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
}

struct ActivitySheet: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

struct ExamItem: Codable, Equatable, Identifiable, Sendable {
    let testName: String
    let urgency: String?
    let rationale: String?
    var id: String { testName }

    enum CodingKeys: String, CodingKey {
        case testName = "test_name"
        case urgency, rationale
    }

    static func candidates(report: Report, previous: [Self]) -> [Self] {
        let tests = report.plan?["recommended_tests"] ?? report.plan?["recommendedTests"]
        let suggested: [Self]
        if case let .array(rows) = tests {
            suggested = rows.compactMap { row in
                guard case let .object(fields) = row,
                      let name = text(fields["test_name"] ?? fields["testName"]) else { return nil }
                return Self(testName: name, urgency: text(fields["urgency"]), rationale: text(fields["rationale"]))
            }
        } else {
            suggested = []
        }
        var seen = Set<String>()
        return (suggested + previous).filter { seen.insert($0.testName).inserted }
    }

    private static func text(_ value: ClinicalValue?) -> String? {
        guard case let .text(raw) = value else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

private struct ExamOrder: Decodable, Sendable {
    let id: UUID
    let items: [ExamItem]
    let note: String?
    let createdAt: Date
    let orderedBy: UUID

    enum CodingKeys: String, CodingKey {
        case id, items, note
        case createdAt = "created_at"
        case orderedBy = "ordered_by"
    }
}

private struct ExamOrderRequest: Encodable, Sendable {
    let items: [ExamItem]
    let note: String?
    let reportID: UUID

    enum CodingKeys: String, CodingKey {
        case items, note
        case reportID = "report_id"
    }
}

struct QuickOrdersScreen: View {
    let sessionID: UUID
    let report: Report
    let account: Account
    let language: AppLanguage
    var linkToReport = false

    @State private var latest: Load<ExamOrder?> = .loading
    @State private var selected: Set<String> = []
    @State private var note = ""
    @State private var submitting = false
    @State private var confirmation = false
    @State private var unresolved: ExamOrderRequest?
    @State private var messageKey: String?

    private var endpoint: String { "sessions/\(sessionID)/exam-orders" }

    var body: some View {
        Form {
            switch latest {
            case .loading, .signedOut:
                ProgressView(language.text("common.loading"))
            case .failed:
                Text(language.text("soap.quickOrders.loadError"))
                Button(language.text("common.retry")) { Task { await load() } }
            case let .loaded(order):
                let candidates = ExamItem.candidates(report: report, previous: order?.items ?? [])
                Section(language.text("soap.quickOrders.summaryTitle")) {
                    Text(report.summary.flatMap { $0.isEmpty ? nil : $0 } ?? language.text("soap.quickOrders.noSummary"))
                    if let order {
                        Text(language.text("soap.quickOrders.lastOrdered")
                            .replacingOccurrences(of: "{{time}}", with: order.createdAt.formatted(.dateTime.hour().minute())))
                    }
                }
                if linkToReport {
                    NavigationLink(language.text("soap.quickOrders.viewFullReport")) {
                        ReportDetailScreen(sessionID: sessionID, account: account, language: language)
                    }
                }
                Section(language.text("soap.quickOrders.testsTitle")) {
                    if candidates.isEmpty { Text(language.text("soap.quickOrders.noTests")) }
                    if !candidates.isEmpty {
                        let all = candidates.allSatisfy { selected.contains($0.id) }
                        Button(language.text(all ? "soap.quickOrders.clearAll" : "soap.quickOrders.selectAll")) {
                            selected = all ? [] : Set(candidates.map(\.id))
                        }
                        .disabled(submitting || unresolved != nil)
                    }
                    ForEach(candidates) { item in
                        Toggle(isOn: Binding(get: { selected.contains(item.id) }, set: {
                            if $0 { selected.insert(item.id) } else { selected.remove(item.id) }
                        })) {
                            VStack(alignment: .leading) {
                                Text(item.testName)
                                if let urgency = item.urgency { Text(urgency).font(.caption) }
                                if let rationale = item.rationale { Text(rationale).font(.subheadline) }
                            }
                        }
                        .disabled(submitting || unresolved != nil)
                    }
                }
                Section(language.text("soap.quickOrders.noteTitle")) {
                    TextField(language.text("soap.quickOrders.noteHint"), text: $note, axis: .vertical)
                        .disabled(submitting || unresolved != nil)
                }
                Section {
                    if selected.isEmpty { Text(language.text("soap.quickOrders.emptySelectionHint")) }
                    if let messageKey { Text(language.text(messageKey)) }
                    if let unresolved {
                        Button(language.text("common.retry")) { Task { await reconcile(unresolved) } }
                            .disabled(submitting)
                    } else {
                        Button(language.text("soap.quickOrders.submit")) { confirmation = true }
                            .disabled(submitting)
                    }
                }
                .confirmationDialog(language.text("soap.quickOrders.submit"), isPresented: $confirmation) {
                    Button(language.text("soap.quickOrders.submit")) {
                        Task { await submit(candidates.filter { selected.contains($0.id) }) }
                    }
                }
            }
        }
        .navigationTitle(language.text("soap.quickOrders.title"))
        .task { await load() }
    }

    private func currentOrder() async throws -> ExamOrder? {
        try await account.api.get("\(endpoint)/latest", language: language)
    }

    private func load() async {
        do {
            let order = try await currentOrder()
            latest = .loaded(order)
            selected = Set((order?.items ?? []).map(\.id))
            note = order?.note ?? ""
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {
            latest = .failed
        }
    }

    private func submit(_ items: [ExamItem]) async {
        guard !submitting, unresolved == nil else { return }
        submitting = true
        let trimmed = note.trimmingCharacters(in: .whitespacesAndNewlines)
        let request = ExamOrderRequest(items: items, note: trimmed.isEmpty ? nil : trimmed, reportID: report.id)
        do {
            let saved: ExamOrder = try await account.api.write(endpoint, method: "POST", language: language, body: request)
            latest = .loaded(saved)
            messageKey = "soap.quickOrders.submitted"
            submitting = false
        } catch {
            messageKey = "soap.quickOrders.submitError"
            unresolved = request
            submitting = false
            await reconcile(request)
        }
    }

    private func reconcile(_ request: ExamOrderRequest) async {
        guard !submitting else { return }
        submitting = true
        defer { submitting = false }
        do {
            let current = try await currentOrder()
            let previous = latest.value ?? nil
            if current?.id != previous?.id {
                latest = .loaded(current)
                if case let .signedIn(user) = account.state,
                   current?.orderedBy == user.id, current?.items == request.items, current?.note == request.note {
                    messageKey = "soap.quickOrders.submitted"
                }
            }
            unresolved = nil
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {}
    }
}
