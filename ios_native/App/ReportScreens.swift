import SwiftUI

struct ReportListScreen: View {
    let account: Account
    let language: AppLanguage

    @State private var reports: [Report] = []
    @State private var cursor: String?
    @State private var seenCursors: Set<String> = []
    @State private var isLoading = true
    @State private var failedReset: Bool?
    @State private var loadedLanguage: AppLanguage?
    @State private var requestID = UUID()

    var body: some View {
        List {
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

            ForEach(reports) { report in
                NavigationLink(value: report.sessionID) { reportRow(report) }
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
        .navigationDestination(for: UUID.self) { id in
            ReportDetailScreen(sessionID: id, account: account, language: language)
        }
        .task(id: language) {
            if loadedLanguage != language { await load(reset: true) }
        }
        .refreshable { await load(reset: true) }
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
            let page = try await Reports(api: account.api, language: language).page(after: previous)
            guard id == requestID, !Task.isCancelled else { return }
            var visited = reset ? Set<String>() : seenCursors
            let next = try page.continuation(seen: &visited)
            if reset { reports = [] }
            seenCursors = visited
            loadedLanguage = language
            var existing = Set(reports.map(\.id))
            reports.append(contentsOf: page.data.filter { existing.insert($0.id).inserted })
            cursor = next
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss()
        } catch {
            guard id == requestID, !Task.isCancelled else { return }
            failedReset = reset
        }
    }
}

private struct ReportDetailScreen: View {
    let sessionID: UUID
    let account: Account
    let language: AppLanguage
    @State private var details = ReportDetails()
    @State private var displayedLanguage: AppLanguage?
    @State private var requestID = UUID()
    @State private var tab: Tab = .report

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
    }

    @ViewBuilder private var soapContent: some View {
        switch details.report {
        case .loaded(let report):
            if let report, report.status == .generated {
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
        case .failed:
            FailureRow(key: "native.reportFailed", language: language, retry: load)
        case .loading, .signedOut:
            ProgressView(language.text("soap.page.loadingReport"))
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
        if result.isSignedOut { await account.noticeAuthorizationLoss() }
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
