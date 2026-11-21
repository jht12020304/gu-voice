import SwiftUI

struct ReportListScreen: View {
    let account: Account
    let language: AppLanguage

    @State private var reports: [Report] = []
    @State private var search = ""
    @State private var filter = ""
    @State private var counts: [String: Int]?
    private let filters = [("", "all"), ("pending", "pending"), ("approved", "approved"), ("revision_needed", "revisionNeeded")]
    @State private var cursor: String?
    @State private var seenCursors: Set<String> = []
    @State private var isLoading = true
    @State private var failedReset: Bool?
    @State private var loadedLanguage: AppLanguage?
    @State private var requestID = UUID()

    var body: some View {
        List {
            Section {
                Picker(language.text("dashboard.sidebar.nav.soapReports"), selection: $filter) {
                    ForEach(filters, id: \.0) { key, suffix in
                        let label = language.text("dashboard.reportList.tabs.\(suffix)")
                        let count = key.isEmpty ? counts.map { $0.values.reduce(0, +) } : counts.map { $0[key, default: 0] }
                        Text(count.map { "\(label) (\($0))" } ?? label).tag(key)
                    }
                }
            }
            if failedReset == true {
                FailureRow(key: "native.reportsFailed", language: language) { await load(reset: true) }
            } else if reports.isEmpty {
                if isLoading || loadedLanguage != language {
                    ProgressView(language.text("common.loading"))
                } else {
                    ContentUnavailableView(
                        language.text("dashboard.reportList.emptyTitle"), systemImage: "doc.text",
                        description: Text(language.text("dashboard.reportList.emptyMessage"))
                    )
                }
            }

            ForEach(reports.filter(matches)) { report in
                NavigationLink {
                    ReportDetailScreen(sessionID: report.sessionID, account: account, language: language)
                } label: {
                    reportRow(report)
                }
            }
            if !reports.isEmpty, reports.filter(matches).isEmpty, cursor == nil {
                Text(language.text("dashboard.reportList.emptyTitle"))
            }

            if !reports.isEmpty, let cursor {
                if failedReset == false {
                    FailureRow(key: "native.reportsFailed", language: language) { await load(reset: false) }
                } else if failedReset == nil {
                    ProgressView(language.text("common.pagination.loadingMore"))
                        .task(id: cursor) { await load(reset: false) }
                }
            }
        }
        .navigationTitle(language.text("dashboard.sidebar.nav.soapReports"))
        .searchable(text: $search, prompt: language.text("dashboard.reportList.searchPlaceholder"))
        .task(id: [language.rawValue, filter, String(account.dashboardRevision)]) {
            await load(reset: true)
        }
        .refreshable { await load(reset: true) }
    }

    private func matches(_ report: Report) -> Bool {
        let value = search.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty || [report.patientName, report.chiefComplaint, report.doctorName, report.summary]
            .compactMap { $0 }.contains { $0.localizedCaseInsensitiveContains(value) }
    }

    private func reportRow(_ report: Report) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(report.patientName ?? language.text("native.patientNameUnavailable"))
                .font(.headline)
                .accessibilityIdentifier("report-patient")
            if let complaint = report.chiefComplaint, !complaint.isEmpty {
                Text(complaint)
            }
            if report.hasRedFlag == true {
                Label(language.text("dashboard.reportList.redFlagBadge"), systemImage: "flag.fill")
                    .foregroundStyle(.red)
            } else if report.hasRedFlag == nil {
                Label(language.text("native.redFlagUnknown"), systemImage: "questionmark.circle")
                    .foregroundStyle(.secondary)
            }
            if let notes = report.reviewNotes, report.reviewStatus == .revisionNeeded {
                Text(language.text("dashboard.reportList.revisionReason")).font(.subheadline.bold())
                Text(notes).lineLimit(2)
            }
            ViewThatFits(in: .horizontal) {
                HStack {
                    reportDate(report)
                    Spacer()
                    reportStatus(report)
                }
                VStack(alignment: .leading) {
                    reportDate(report)
                    reportStatus(report)
                }
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 6)
    }

    private func reportDate(_ report: Report) -> some View {
        Text((report.generatedAt ?? report.createdAt).formatted(
            .dateTime.year().month().day().hour().minute().locale(Locale(identifier: language.rawValue))
        ))
    }

    private func reportStatus(_ report: Report) -> some View {
        let review = report.reviewStatus == .revisionNeeded ? "revisionNeeded" : report.reviewStatus.rawValue
        return Text(language.text(report.status == .generated
            ? "soap.reviewStatus.\(review)" : "soap.reportStatus.\(report.status.rawValue)"))
    }

    private func load(reset: Bool) async {
        if !reset, isLoading { return }
        let id = UUID()
        requestID = id
        isLoading = true
        failedReset = nil
        defer { if id == requestID { isLoading = false } }
        let previous = reset ? nil : cursor
        do {
            let page = try await Reports(api: account.api, language: language).page(after: previous, review: filter)
            guard id == requestID, !Task.isCancelled else { return }
            var visited = reset ? Set<String>() : seenCursors
            let next = try page.continuation(seen: &visited)
            if reset { reports = [] }
            seenCursors = visited
            loadedLanguage = language
            counts = page.reviewCounts
            var existing = Set(reports.map(\.id))
            reports.append(contentsOf: page.data.filter { existing.insert($0.id).inserted })
            cursor = next
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {
            guard id == requestID, !Task.isCancelled else { return }
            failedReset = reset
        }
    }
}

struct ReportDetailScreen: View {
    let sessionID: UUID
    let account: Account
    let language: AppLanguage
    @State private var details = ReportDetails()
    @State private var displayedLanguage: AppLanguage?
    @State private var requestID = UUID()
    @State private var tab: Tab = .report
    @State private var decision: Report.Review?
    @State private var notes = ""
    @State private var submitting = false
    @State private var uncertainReview: Report.Review?
    @State private var regenerating = false
    @State private var confirmGeneration = false
    @State private var exporting = false
    @State private var pdf: ReportPDF?
    @State private var errorKey: String?

    private var reports: Reports { Reports(api: account.api, language: language) }
    private var canGenerate: Bool {
        ["completed", "aborted_red_flag"].contains(details.session.value?.status ?? "")
        && report?.status != .generating
    }

    private enum Tab: String, CaseIterable { case report, transcript }

    private var report: Report? { details.report.value ?? nil }

    var body: some View {
        List {
            Section {
                if case let .loaded(session) = details.session {
                    Text(session.patientName ?? report?.patientName ?? language.text("native.patientNameUnavailable"))
                        .font(.title2.bold())
                        .accessibilityAddTraits(.isHeader)
                    if let complaint = session.chiefComplaint, !complaint.isEmpty { Text(complaint) }
                } else if case .failed = details.session {
                    FailureRow(key: "session.doctor.detail.loadError", language: language, retry: load)
                } else {
                    ProgressView(language.text("session.doctor.detail.loading"))
                }
                Link(destination: account.api.configuration.reportLink(sessionID: sessionID, language: language)) {
                    Label(language.text("soap.page.openInWeb"), systemImage: "arrow.up.right.square")
                }
            }

            Section(language.text("soap.redFlag.title")) {
                switch details.redFlagStatus {
                case .loading:
                    ProgressView(language.text("common.loading"))
                case .clear:
                    Label(language.text("native.noRedFlags"), systemImage: "checkmark.circle")
                case .flagged:
                    Label(language.text("soap.meta.redFlagSession"), systemImage: "flag.fill")
                        .font(.headline)
                        .foregroundStyle(.red)
                    if details.session.value?.redFlag == true {
                        Text(details.session.value?.redFlagReason ?? language.text("soap.redFlag.defaultReason"))
                    }
                    ForEach(details.alerts.value ?? []) { alert in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(alert.title).font(.headline)
                            Text(language.text("native.severity.\(alert.severity)"))
                                .font(.subheadline).foregroundStyle(.secondary)
                            Text(alert.triggerReason)
                        }
                    }
                    if case .failed = details.alerts {
                        FailureRow(key: "soap.redFlag.loadFailedTitle", language: language, retry: load)
                    }
                case .unavailable:
                    FailureRow(key: "soap.redFlag.loadFailedTitle", language: language, retry: load)
                }
            }

            Picker(language.text("soap.page.title"), selection: $tab) {
                Text(language.text("soap.tabs.report")).tag(Tab.report)
                Text(language.text("soap.tabs.transcript")).tag(Tab.transcript)
            }
            .pickerStyle(.segmented)
            .listRowInsets(EdgeInsets(top: 0, leading: 0, bottom: 0, trailing: 0))
            .listRowBackground(Color.clear)

            switch tab {
            case .report: soapContent
            case .transcript: transcriptContent
            }
        }
        .navigationTitle(language.text("soap.page.title"))
        .navigationBarTitleDisplayMode(.inline)
        .task(id: language) { await load() }
        .refreshable { await load() }
        .task(id: report?.status) {
            while report?.status == .generating {
                do { try await Task.sleep(for: .seconds(3)) }
                catch { return }
                await load()
            }
        }
        .sheet(isPresented: Binding(get: { decision != nil }, set: { if !$0 { decision = nil } })) {
            if let decision { reviewForm(decision) }
        }
        .sheet(item: $pdf) { pdf in
            ActivitySheet(items: [pdf.url])
        }
        .confirmationDialog(language.text("soap.regenerate.title"), isPresented: $confirmGeneration) {
            Button(language.text("soap.regenerate.confirm")) { Task { await generate() } }
        } message: {
            Text(language.text("soap.regenerate.description"))
        }
    }

    @ViewBuilder private var soapContent: some View {
        switch details.report {
        case .loaded(let report):
            if let report, report.status == .generated {
                Section {
                    Button { Task { await export(report) } } label: {
                        Label(language.text("soap.export.button"), systemImage: "doc")
                    }
                    .disabled(exporting)
                    NavigationLink {
                        QuickOrdersScreen(sessionID: sessionID, report: report, account: account, language: language)
                    } label: {
                        Label(language.text("soap.quickOrders.title"), systemImage: "checklist")
                    }
                    Text(language.text("soap.reviewStatus.\(report.reviewStatus == .revisionNeeded ? "revisionNeeded" : report.reviewStatus.rawValue)"))
                    if let uncertainReview {
                        Button(language.text("common.retry")) { decision = uncertainReview }
                    } else if report.reviewStatus == .pending {
                        Button(language.text("soap.review.approveButton")) { startReview(.approved) }
                        Button(language.text("soap.review.rejectButton"), role: .destructive) { startReview(.revisionNeeded) }
                    }
                }
                if let notes = report.reviewNotes, !notes.isEmpty {
                    Section(language.text("soap.reviewNotesCard.title")) { Text(notes) }
                }
                if let summary = report.summary, !summary.isEmpty {
                    Section(language.text("soap.page.clinicalSummaryEyebrow")) { Text(summary) }
                }
                clinicalSection("subjective", fields: report.subjective)
                clinicalSection("objective", fields: report.objective)
                clinicalSection("assessment", fields: report.assessment)
                clinicalSection("plan", fields: report.plan)
                if let codes = report.codes, !codes.isEmpty {
                    Section(language.text("soap.diagnosis.title")) { Text(codes.joined(separator: ", ")) }
                }
            } else {
                let key = report.map { "soap.reportStatus.\($0.status.rawValue)" } ?? "native.reportUnavailable"
                Text(language.text(key)).foregroundStyle(.secondary)
            }
            if canGenerate {
                Button(language.text("soap.regenerate.button")) { confirmGeneration = true }
                    .disabled(regenerating)
            }
            if let errorKey, decision == nil { Text(language.text(errorKey)).foregroundStyle(.red) }
        case .failed:
            FailureRow(key: "native.reportFailed", language: language, retry: load)
        case .loading, .signedOut:
            ProgressView(language.text("soap.page.loadingReport"))
        }
    }

    private func startReview(_ value: Report.Review) {
        guard !submitting else { return }
        decision = value
        notes = ""
        errorKey = nil
    }

    private func reviewForm(_ value: Report.Review) -> some View {
        let approving = value == .approved
        let action = language.text(approving ? "soap.review.approveButton" : "soap.review.rejectButton")
        return NavigationStack {
            Form {
                Text(language.text(approving ? "soap.review.approveDescription" : "soap.review.rejectDescription"))
                TextField(
                    language.text(approving ? "soap.review.approveNotesPlaceholder" : "soap.review.rejectNotesPlaceholder"),
                    text: $notes, axis: .vertical
                )
                .disabled(submitting || uncertainReview != nil)
                if let errorKey { Text(language.text(errorKey)).foregroundStyle(.red) }
                if uncertainReview != nil {
                    Button(language.text("common.retry")) {
                        Task {
                            guard !submitting else { return }
                            submitting = true
                            defer { submitting = false }
                            await reconcileReview(value)
                        }
                    }
                        .disabled(submitting)
                } else {
                    Button(action) { Task { await submitReview(value) } }
                        .disabled(submitting || (!approving && notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
                }
            }
            .navigationTitle(action)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(language.text("common.cancel")) { decision = nil }
                        .disabled(submitting)
                }
            }
        }
        .interactiveDismissDisabled(submitting)
    }

    private func submitReview(_ value: Report.Review) async {
        guard !submitting, uncertainReview == nil, let report else { return }
        submitting = true
        defer { submitting = false }
        do {
            let updated = try await reports.review(report, decision: value, notes: notes)
            requestID = UUID()
            details.report = .loaded(updated)
            decision = nil
        } catch {
            errorKey = "soap.review.submitError"
            uncertainReview = value
            await reconcileReview(value)
        }
    }

    private func reconcileReview(_ value: Report.Review) async {
        do {
            let refreshed: Report = try await account.api.get("sessions/\(sessionID)/report", language: language)
            requestID = UUID()
            details.report = .loaded(refreshed)
            uncertainReview = nil
            if refreshed.reviewStatus != .pending {
                decision = nil
                if refreshed.reviewStatus == value { errorKey = nil }
            }
        } catch APIError.status(403), APIError.status(404) {
            decision = nil
            uncertainReview = nil
            await load()
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {}
    }

    private func generate() async {
        guard canGenerate, !regenerating else { return }
        regenerating = true
        errorKey = nil
        defer { regenerating = false }
        do {
            details.report = .loaded(try await reports.generate(sessionID))
        } catch {
            errorKey = "soap.regenerate.error"
            await load()
        }
    }

    private func export(_ report: Report) async {
        guard !exporting else { return }
        exporting = true
        errorKey = nil
        defer { exporting = false }
        do {
            pdf = try ReportPDF(data: await reports.pdf(report), id: report.id)
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {
            errorKey = "soap.export.error"
        }
    }

    private func clinicalSection(_ name: String, fields: [String: ClinicalValue]?) -> some View {
        Section(language.text("soap.section.\(name).title")) {
            let rows = ClinicalRows(language: language, section: name).fields(fields ?? [:])
            if rows.isEmpty {
                Text(language.text("soap.common.empty")).foregroundStyle(.secondary)
            } else {
                ForEach(rows) { row in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(row.label).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                        Text(row.content)
                    }
                }
            }
        }
    }

    @ViewBuilder private var transcriptContent: some View {
        Section(language.text("soap.tabs.transcript")) {
            switch details.transcript {
            case let .loaded(turns) where !turns.isEmpty:
                ForEach(turns) { turn in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(language.text("common.roles.\(turn.role)"))
                            .font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                        Text(turn.content)
                    }
                }
            case .loaded:
                if let raw = report?.rawTranscript, !raw.isEmpty {
                    Text(language.text("native.transcriptSnapshot")).font(.subheadline).foregroundStyle(.secondary)
                    Text(raw)
                } else {
                    Text(language.text("session.doctor.detail.conversationsEmpty")).foregroundStyle(.secondary)
                }
            case .failed:
                FailureRow(key: "native.transcriptFailed", language: language, retry: load)
            case .loading, .signedOut:
                ProgressView(language.text("common.loading"))
            }
        }
    }

    private func load() async {
        let id = UUID()
        requestID = id
        if displayedLanguage != language {
            details = ReportDetails()
            displayedLanguage = language
        }
        let result = await Reports(api: account.api, language: language).details(for: sessionID) { result in
            guard id == requestID, !Task.isCancelled else { return }
            details.apply(result)
        }
        guard id == requestID, !Task.isCancelled else { return }
        if result.isSignedOut { await account.noticeAuthorizationLoss(language) }
    }
}

private struct FailureRow: View {
    let key: String
    let language: AppLanguage
    let retry: () async -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(language.text(key), systemImage: "exclamationmark.triangle")
                .foregroundStyle(.primary)
            Button(language.text("common.retry")) { Task { await retry() } }
                .buttonStyle(.borderless)
        }
    }
}
