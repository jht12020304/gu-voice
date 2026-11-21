import Charts
import SwiftUI

struct SecondaryActionsMenu<Content: View>: View {
    let language: AppLanguage
    @ViewBuilder let content: () -> Content
    @State private var isPresented = false

    var body: some View {
        Button {
            isPresented = true
        } label: {
            Label(language.text("common.header.more"), systemImage: "ellipsis.circle")
        }
        .accessibilityIdentifier("secondary-actions-menu")
        .confirmationDialog(language.text("common.header.more"), isPresented: $isPresented,
                            titleVisibility: .hidden) {
            content()
        }
    }
}

struct PagedRows<Item: Decodable & Identifiable & Sendable, Row: View>: View {
    let account: Account
    let language: AppLanguage
    let endpoint: String
    var query: [URLQueryItem] = []
    var refreshID = 0
    var emptyKey = "common.common.emptyTitle"
    var sectionTitle: String?
    var matches: (Item) -> Bool = { _ in true }
    @ViewBuilder let row: (Item) -> Row

    @State private var items: [Item] = []
    @State private var cursor: String?
    @State private var seen = Set<String>()
    @State private var loading = true
    @State private var failedReset: Bool?
    @State private var generation = UUID()
    @State private var requested: RequestKey?
    @State private var displayed: RequestKey?

    var body: some View {
        Section {
            ForEach(items.filter(matches)) { item in row(item) }
            if loading {
                ProgressView(language.text("common.loading"))
            } else if let failedReset {
                Button(language.text("common.retry")) { Task { await load(reset: failedReset) } }
            } else if let cursor {
                Button(language.text("common.pagination.loadMore")) {
                    Task { if self.cursor == cursor { await load(reset: false) } }
                }
            } else if items.filter(matches).isEmpty {
                Text(language.text(emptyKey)).foregroundStyle(.secondary)
            }
        } header: {
            if let sectionTitle { Text(sectionTitle) }
        }
        .task(id: requestKey) {
            let key = requestKey
            guard requested != key else { return }
            requested = key
            await load(reset: true)
            if Task.isCancelled && requested == key { requested = nil }
        }
    }

    private var requestKey: RequestKey {
        RequestKey(endpoint: endpoint, query: query, language: language, refresh: refreshID)
    }

    private struct RequestKey: Equatable {
        let endpoint: String
        let query: [URLQueryItem]
        let language: AppLanguage
        let refresh: Int

        func hasSameQuery(as other: Self) -> Bool {
            endpoint == other.endpoint && query == other.query && language == other.language
        }
    }

    private func load(reset: Bool) async {
        if !reset && loading { return }
        let id = UUID()
        generation = id
        let key = requestKey
        if reset && displayed?.hasSameQuery(as: key) != true {
            items = []
            cursor = nil
            seen = []
        }
        let requestedCursor = reset ? nil : cursor
        loading = true
        failedReset = nil
        defer { if generation == id { loading = false } }
        var parameters = query
        if let requestedCursor { parameters.append(.init(name: "cursor", value: requestedCursor)) }
        do {
            let page: Page<Item> = try await account.api.get(endpoint, language: language, query: parameters)
            guard generation == id, !Task.isCancelled else { return }
            var traversed = reset ? Set<String>() : seen
            let next = try page.continuation(seen: &traversed)
            if reset { items = [] }
            var existing = Set(items.map(\.id))
            items.append(contentsOf: page.data.filter { existing.insert($0.id).inserted })
            cursor = next
            seen = traversed
            displayed = key
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {
            if generation == id && !Task.isCancelled { failedReset = reset }
        }
    }
}

struct RecordScreen<Value: Decodable & Sendable, Content: View>: View {
    let account: Account
    let language: AppLanguage
    let endpoint: String
    let title: String
    @ViewBuilder let content: (Value, @escaping () async -> Void) -> Content

    @State private var result: Load<Value> = .loading
    @State private var generation = UUID()

    var body: some View {
        List {
            switch result {
            case let .loaded(value): content(value, load)
            case .loading, .signedOut: ProgressView(language.text("common.loading"))
            case .failed:
                Text(language.text("common.unknownError"))
                Button(language.text("common.retry")) { Task { await load() } }
            }
        }
        .navigationTitle(language.text(title))
        .task(id: language) { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        let id = UUID()
        generation = id
        let api = account.api
        let language = self.language
        let endpoint = self.endpoint
        let next: Load<Value> = await Load.fetch { try await api.get(endpoint, language: language) }
        guard generation == id, !Task.isCancelled else { return }
        result = next
        if next.isSignedOut { await account.noticeAuthorizationLoss(language) }
    }
}

struct ClinicalHome: View {
    let user: User
    let account: Account
    let language: AppLanguage

    @Environment(\.scenePhase) private var scenePhase
    @State private var month = Date()
    @State private var summary: Load<MonthlySummary> = .loading
    @State private var unread = 0
    @State private var unacknowledged = 0

    var body: some View {
        List {
            Section(user.name) {
                HStack {
                    Button { shift(-1) } label: { Image(systemName: "chevron.left") }
                        .buttonStyle(.borderless).accessibilityLabel(language.text("common.doctor.dashboard.prevMonth"))
                    Spacer()
                    Text(month.formatted(.dateTime.year().month(.wide)))
                    Spacer()
                    Button { shift(1) } label: { Image(systemName: "chevron.right") }
                        .buttonStyle(.borderless).accessibilityLabel(language.text("common.doctor.dashboard.nextMonth"))
                }
                switch summary {
                case let .loaded(summary):
                    LabeledContent(language.text("common.doctor.dashboard.totalSessions"), value: String(summary.totalSessions))
                    LabeledContent(language.text("common.doctor.dashboard.redFlagMetric"), value: String(summary.totalRedFlagAlerts))
                case .loading, .signedOut:
                    ProgressView(language.text("common.loading"))
                case .failed:
                    Button(language.text("common.retry")) { Task { await load() } }
                }
            }
            Section {
                link("dashboard.sidebar.nav.soapReports", icon: "doc.text", to: ReportListScreen(account: account, language: language))
                link("session.doctor.list.title", icon: "list.bullet", to: SessionsScreen(account: account, language: language))
                link("dashboard.sidebar.nav.patients", icon: "person.2", to: PatientsScreen(account: account, language: language))
                link("dashboard.sidebar.nav.redFlagAlerts", icon: "flag", badge: unacknowledged,
                     to: AlertsScreen(account: account, language: language))
                link("dashboard.notifications.title", icon: "bell", badge: unread,
                     to: NotificationsScreen(account: account, language: language))
                link("common.doctor.settings.title", icon: "gearshape", to: ClinicalSettings(user: user, account: account, language: language))
            }
            Section(language.text("dashboard.sidebar.sections.admin")) {
                if user.isSystemAdmin {
                    link("dashboard.sidebar.nav.userManagement", icon: "person.badge.key",
                         to: AdminUsersScreen(account: account, language: language))
                }
                if user.canOpenAuditAndResearch {
                    link("dashboard.sidebar.nav.auditLogs", icon: "doc.text.magnifyingglass",
                         to: AuditScreen(account: account, language: language))
                    link("dashboard.sidebar.nav.research", icon: "chart.bar",
                         to: ResearchScreen(account: account, language: language))
                }
                link("dashboard.sidebar.nav.complaintTemplates", icon: "list.clipboard",
                     to: ComplaintTemplatesScreen(account: account, language: language))
                link("dashboard.sidebar.nav.systemHealth", icon: "heart.text.clipboard",
                     to: HealthScreen(account: account, language: language))
            }
            if let summary = summary.value {
                if !summary.complaints.isEmpty {
                    Section(language.text("common.doctor.dashboard.chiefComplaintDistribution")) {
                        Chart(summary.complaints) { row in
                            BarMark(x: .value(language.text("common.doctor.dashboard.totalSessions"), row.count),
                                    y: .value(language.text("common.doctor.dashboard.chiefComplaintDistribution"), row.label))
                        }
                        .frame(minHeight: 180)
                    }
                }
                Section(language.text("common.doctor.dashboard.dailyTrend")) {
                    Chart(summary.trend) { row in
                        LineMark(x: .value(language.text("common.doctor.dashboard.dailyTrend"), row.label),
                                 y: .value(language.text("common.doctor.dashboard.totalSessions"), row.sessions))
                    }
                    .chartXAxis(.hidden)
                    .frame(minHeight: 150)
                }
            }
        }
        .navigationTitle(language.text("common.doctor.dashboard.title"))
        .task(id: [monthKey, language.rawValue, String(account.dashboardRevision)]) {
            await load()
            await loadBadges()
        }
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                await loadBadges()
                do { try await Task.sleep(for: .seconds(20)) } catch { return }
            }
        }
        .refreshable { await load(); await loadBadges() }
    }

    private func link<Destination: View>(_ key: String, icon: String, badge: Int = 0, to destination: Destination) -> some View {
        NavigationLink {
            destination
        } label: {
            Label(language.text(key), systemImage: icon)
        }
        .badge(badge)
    }

    private var monthKey: String {
        let current = Calendar.current.dateComponents([.year, .month], from: month)
        return String(format: "%04d-%02d", current.year ?? 0, current.month ?? 0)
    }

    private func shift(_ value: Int) {
        if let shifted = Calendar.current.date(byAdding: .month, value: value, to: month) { month = shifted }
    }

    private func load() async {
        let key = monthKey
        let next: Load<MonthlySummary> = await Load.fetch {
            try await account.api.get("dashboard/monthly-summary", language: language, query: [.init(name: "month", value: key)])
        }
        guard !Task.isCancelled, key == monthKey else { return }
        summary = next
        if next.isSignedOut { await account.noticeAuthorizationLoss(language) }
    }

    private func loadBadges() async {
        struct Count: Decodable { let count: Int }
        do {
            async let notifications: Count = account.api.get("notifications/unread-count", language: language)
            async let flags: Count = account.api.get("alerts/unacknowledged/count", language: language)
            (unread, unacknowledged) = try await (notifications.count, flags.count)
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {}
    }
}

private struct MonthlySummary: Decodable, Sendable {
    let totalSessions: Int
    let totalRedFlagAlerts: Int
    let complaints: [Bucket]
    let trend: [Day]

    enum CodingKeys: String, CodingKey {
        case totalSessions = "total_sessions", totalRedFlagAlerts = "total_red_flag_alerts"
        case complaints = "chief_complaint_distribution", trend = "daily_trend"
    }

    struct Bucket: Decodable, Identifiable, Sendable {
        let key: String
        let label: String
        let count: Int
        var id: String { key }
    }

    struct Day: Decodable, Identifiable, Sendable {
        let date: String
        let label: String
        let sessions: Int
        var id: String { date }
    }
}

struct ClinicalDestination: View {
    let route: NotificationRoute
    let account: Account
    let language: AppLanguage

    var body: some View {
        switch route {
        case let .order(id):
            OrderDestination(sessionID: id, account: account, language: language)
        case let .session(id):
            SessionDetailScreen(id: id, account: account, language: language)
        case let .alert(id):
            AlertDetailScreen(id: id, account: account, language: language)
        }
    }
}

private struct OrderDestination: View {
    let sessionID: UUID
    let account: Account
    let language: AppLanguage
    @State private var report: Load<Report> = .loading

    var body: some View {
        Group {
            switch report {
            case .loading, .signedOut: ProgressView(language.text("common.loading"))
            case .failed:
                VStack {
                    Text(language.text("soap.quickOrders.loadError"))
                    Button(language.text("common.retry")) { Task { await load() } }
                }
            case let .loaded(record):
                QuickOrdersScreen(sessionID: sessionID, report: record, account: account, language: language, linkToReport: true)
            }
        }
        .task(id: language) { await load() }
    }

    private func load() async {
        report = await Load.fetch { try await account.api.get("sessions/\(sessionID)/report", language: language) }
        if report.isSignedOut { await account.noticeAuthorizationLoss(language) }
    }
}
