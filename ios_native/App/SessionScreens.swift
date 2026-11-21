import SwiftUI

struct ClinicalSession: Decodable, Identifiable, Sendable {
    let id: UUID
    let language: String?
    let doctorID: UUID?
    let patientID: UUID
    let patientName: String?
    let complaint: String?
    let status: String
    let flagged: Bool
    let reason: String?
    let createdAt: Date
    let startedAt: Date?
    let duration: Int?
    let conversations: [ConversationTurn]?

    enum CodingKeys: String, CodingKey {
        case id, status, conversations, language
        case doctorID = "doctor_id"
        case patientID = "patient_id", patientName = "patient_name", complaint = "chief_complaint_text"
        case flagged = "red_flag", reason = "red_flag_reason", createdAt = "created_at", startedAt = "started_at"
        case duration = "duration_seconds"
    }

    func matches(_ search: String) -> Bool {
        let text = search.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty || [patientName, complaint].compactMap { $0 }
            .contains { $0.localizedCaseInsensitiveContains(text) }
    }
}

struct SessionRow: View {
    let session: ClinicalSession
    let account: Account
    let language: AppLanguage

    var body: some View {
        NavigationLink {
            SessionDetailScreen(id: session.id, account: account, language: language)
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                Text(session.patientName ?? language.text("session.doctor.list.unknownPatient"))
                    .font(.headline)
                if let complaint = session.complaint { Text(complaint) }
                Text((session.startedAt ?? session.createdAt).formatted(.dateTime.month().day().hour().minute()))
                    .font(.subheadline).foregroundStyle(.secondary)
                Text(language.text(sessionStatusKey(session.status))).font(.subheadline)
                if session.flagged {
                    Label(language.text("session.doctor.list.redFlagBadge"), systemImage: "flag.fill")
                        .font(.caption).foregroundStyle(.red)
                }
            }
        }
    }
}

func sessionStatusKey(_ value: String) -> String {
    let suffix = switch value {
    case "in_progress": "InProgress"
    case "waiting": "Waiting"
    case "aborted_red_flag": "AbortedRedFlag"
    case "cancelled": "Cancelled"
    default: "Completed"
    }
    return "common.patient.home.status" + suffix
}

struct LocalDateRange {
    let start: Date
    let end: Date
    let calendar: Calendar

    var query: [URLQueryItem] {
        [.init(name: "date_from", value: iso(start, lastMicrosecond: false)),
         .init(name: "date_to", value: iso(end.addingTimeInterval(-1), lastMicrosecond: true))]
    }

    private func iso(_ date: Date, lastMicrosecond: Bool) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = lastMicrosecond ? "yyyy-MM-dd'T'HH:mm:ss'.999999'xxx" : "yyyy-MM-dd'T'HH:mm:ss'.000000'xxx"
        return formatter.string(from: date)
    }
}

struct SessionsScreen: View {
    let account: Account
    let language: AppLanguage

    @State private var mode = false
    @State private var search = ""
    @State private var day = Date()
    @State private var allDates = false
    @State private var status = ""
    @State private var month = Date()
    @State private var calendarState: Load<[CalendarDay]> = .loading
    @State private var update = 0

    private let filters = [("", "tabAll"), ("in_progress", "tabInProgress"), ("waiting", "tabWaiting"), ("completed", "tabCompleted")]
    private var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .autoupdatingCurrent
        calendar.locale = Locale(identifier: language.rawValue)
        return calendar
    }

    private var monthDays: [Date] {
        guard let range = calendar.dateInterval(of: .month, for: month),
              let count = calendar.range(of: .day, in: .month, for: month)?.count else { return [] }
        let boundaries = (0..<count).compactMap {
            calendar.date(byAdding: .day, value: $0, to: range.start).map { calendar.startOfDay(for: $0) }
        }
        return Set(boundaries + [range.end]).sorted()
    }

    private var dayQuery: [URLQueryItem] {
        let range = calendar.dateInterval(of: .day, for: day)
        var items = range.flatMap { allDates && !mode ? nil : LocalDateRange(start: $0.start, end: $0.end, calendar: calendar).query } ?? []
        if !mode, !status.isEmpty { items.append(.init(name: "status", value: status)) }
        if !allDates || mode { items.append(.init(name: "sort_order", value: "asc")) }
        return items
    }

    var body: some View {
        List {
            Picker(language.text("session.doctor.list.title"), selection: $mode) {
                Text(language.text("session.doctor.list.title")).tag(false)
                Text(language.text("session.doctor.calendar.viewCalendar")).tag(true)
            }
            .pickerStyle(.segmented)
            if mode {
                Section {
                    calendarGrid
                }
            } else {
                Section {
                    Toggle(language.text("session.doctor.list.allDates"), isOn: $allDates)
                    if !allDates {
                        DatePicker(language.text("session.doctor.list.today"), selection: $day, in: ...Date(), displayedComponents: .date)
                    }
                    Picker(language.text("session.doctor.list.title"), selection: $status) {
                        ForEach(filters, id: \.0) { key, label in
                            Text(language.text("session.doctor.list.\(label)")).tag(key)
                        }
                    }
                }
            }
            PagedRows(account: account, language: language, endpoint: "sessions", query: dayQuery,
                      refreshID: update + account.dashboardRevision,
                      emptyKey: "session.doctor.list.emptyTitle", matches: { $0.matches(search) }) { (session: ClinicalSession) in
                SessionRow(session: session, account: account, language: language)
            }
        }
        .navigationTitle(language.text("session.doctor.list.title"))
        .searchable(text: $search, prompt: language.text("session.doctor.list.searchPlaceholder"))
        .task(id: CalendarQuery(days: monthDays, mode: mode, revision: account.dashboardRevision)) {
            if mode { await loadMonth() }
        }
        .refreshable {
            update += 1
            if mode { await loadMonth() }
        }
    }

    private var calendarGrid: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Button { shiftMonth(-1) } label: { Image(systemName: "chevron.left") }
                    .buttonStyle(.borderless).accessibilityLabel(language.text("session.doctor.calendar.previousMonth"))
                Spacer()
                Text(month.formatted(.dateTime.year().month(.wide))).font(.headline)
                Spacer()
                Button { shiftMonth(1) } label: { Image(systemName: "chevron.right") }
                    .buttonStyle(.borderless).accessibilityLabel(language.text("session.doctor.calendar.nextMonth"))
            }
            let start = monthDays.first ?? month
            let blanks = (calendar.component(.weekday, from: start) - calendar.firstWeekday + 7) % 7
            let weekdays = calendar.veryShortStandaloneWeekdaySymbols
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 1), count: 7), spacing: 4) {
                ForEach(0..<7) { column in
                    Text(weekdays[(calendar.firstWeekday - 1 + column) % 7]).font(.caption)
                        .accessibilityHidden(true)
                }
                ForEach(0..<blanks, id: \.self) { _ in Color.clear.accessibilityHidden(true) }
                ForEach(Array(monthDays.dropLast().enumerated()), id: \.element) { index, date in
                    dayButton(date, summary: calendarState.value?.first { $0.index == index })
                }
            }
            switch calendarState {
            case .loading, .signedOut: ProgressView(language.text("common.loading"))
            case .failed: Button(language.text("common.retry")) { Task { await loadMonth() } }
            case .loaded: EmptyView()
            }
            Text(day.formatted(.dateTime.weekday(.wide).month().day())).font(.headline)
        }
    }

    private func dayButton(_ date: Date, summary: CalendarDay?) -> some View {
        let selected = calendar.isDate(date, inSameDayAs: day)
        return Button {
            day = date
        } label: {
            VStack(spacing: 1) {
                Text(date.formatted(.dateTime.day()))
                if let summary, summary.total > 0 {
                    Text(summary.total, format: .number).font(.caption2)
                        .foregroundStyle(summary.redFlags > 0 ? .red : .secondary)
                }
            }
            .frame(maxWidth: .infinity, minHeight: 44)
            .background(selected ? Color.accentColor.opacity(0.16) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.borderless)
        .accessibilityLabel(date.formatted(.dateTime.weekday(.wide).month().day()))
        .accessibilityValue(summary.map { language.text("session.doctor.calendar.sessionsCount", args: ["count": String($0.total)]) } ?? "")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func shiftMonth(_ delta: Int) {
        guard let start = calendar.dateInterval(of: .month, for: month)?.start,
              let next = calendar.date(byAdding: .month, value: delta, to: start) else { return }
        month = next
        day = next
    }

    private func loadMonth() async {
        let days = monthDays
        guard days.count > 1 else { return }
        calendarState = .loading
        let query = days.map { URLQueryItem(name: "day_starts", value: $0.ISO8601Format()) }
        let next: Load<[CalendarDay]> = await Load.fetch {
            try await account.api.get("dashboard/calendar", language: language, query: query)
        }
        guard days == monthDays, !Task.isCancelled else { return }
        calendarState = next
        if next.isSignedOut { await account.noticeAuthorizationLoss(language) }
    }

    private struct CalendarQuery: Equatable {
        let days: [Date]
        let mode: Bool
        let revision: Int
    }

    private struct CalendarDay: Decodable, Sendable {
        let index: Int
        let total: Int
        let redFlags: Int
        enum CodingKeys: String, CodingKey { case total, index = "day_index", redFlags = "red_flags" }
    }
}

struct SessionDetailScreen: View {
    let id: UUID
    let account: Account
    let language: AppLanguage

    @Environment(KioskVisit.self) private var visit
    @Environment(\.dismiss) private var dismiss
    @State private var action: Action?
    @State private var busy = false
    @State private var errorKey: String?

    private enum Action: String { case completed, cancelled, delete }
    private var endpoint: String { "sessions/\(id)" }

    var body: some View {
        RecordScreen(account: account, language: language, endpoint: endpoint, title: "session.doctor.detail.title") {
            (session: ClinicalSession, reload) in
            Section(session.patientName ?? language.text("session.doctor.list.unknownPatient")) {
                if let complaint = session.complaint { Text(complaint) }
                Text(language.text(sessionStatusKey(session.status)))
                Text(session.createdAt.formatted(.dateTime.year().month().day().hour().minute()))
                if session.flagged {
                    Label(language.text("session.doctor.list.redFlagBadge"), systemImage: "flag.fill")
                        .foregroundStyle(.red)
                    if let reason = session.reason { Text(reason) }
                }
                if ["completed", "aborted_red_flag"].contains(session.status) {
                    NavigationLink(language.text("soap.page.title")) {
                        ReportDetailScreen(sessionID: id, account: account, language: language)
                    }
                }
            }
            Section(language.text("soap.tabs.transcript")) {
                let turns = (session.conversations ?? []).sorted { $0.sequence < $1.sequence }
                if turns.isEmpty { Text(language.text("session.doctor.detail.conversationsEmpty")) }
                ForEach(turns) { turn in
                    VStack(alignment: .leading) {
                        Text(language.text("common.roles.\(turn.role)")).font(.caption)
                        Text(turn.content)
                    }
                }
            }
            Section {
                if ["waiting", "in_progress"].contains(session.status) {
                    Button(language.text("conversation.title")) { visit.resume(session, fallback: language) }
                    Button(language.text("session.doctor.detail.markCompleted")) { action = .completed }.disabled(busy)
                    Button(language.text("session.doctor.detail.cancelSession")) { action = .cancelled }.disabled(busy)
                }
                if account.currentUser?.role == .admin {
                    Button(language.text("session.doctor.detail.deleteSession"), role: .destructive) { action = .delete }.disabled(busy)
                }
                if let errorKey { Text(language.text(errorKey)).foregroundStyle(.red) }
            }
            .confirmationDialog(language.text(actionKey(action)), isPresented: Binding(
                get: { action != nil }, set: { if !$0 { action = nil } }
            ), presenting: action) { action in
                Button(language.text(actionKey(action)), role: action == .delete ? .destructive : nil) {
                    Task { await perform(action, reload: reload) }
                }
            } message: { action in
                Text(language.text(actionMessage(action)))
            }
        }
    }

    private func actionKey(_ action: Action?) -> String {
        switch action {
        case .completed: "session.doctor.detail.markCompleted"
        case .cancelled: "session.doctor.detail.cancelSession"
        default: "session.doctor.detail.deleteSession"
        }
    }

    private func actionMessage(_ action: Action) -> String {
        switch action {
        case .completed: "session.doctor.detail.markCompletedConfirm"
        case .cancelled: "session.doctor.detail.cancelSessionConfirm"
        case .delete: "session.doctor.detail.deleteSessionConfirm"
        }
    }

    private func perform(_ action: Action, reload: () async -> Void) async {
        guard !busy else { return }
        busy = true
        errorKey = nil
        defer { busy = false }
        do {
            if action == .delete {
                try await account.api.request(endpoint, language: language, method: "DELETE")
                dismiss()
            } else {
                let body = try JSONEncoder().encode(["status": action.rawValue])
                try await account.api.request("\(endpoint)/status", language: language, method: "PUT", body: body)
                await reload()
            }
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {
            errorKey = action == .delete ? "session.doctor.detail.deleteError" : "session.doctor.detail.statusUpdateError"
            await reload()
        }
    }
}
