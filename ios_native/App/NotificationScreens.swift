import SwiftUI

private struct InboxNotification: Decodable, Identifiable, Sendable {
    let id: UUID
    let type: String
    let title: String
    let body: String?
    let data: Payload?
    let read: Bool
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id, type, title, body, data
        case read = "is_read", createdAt = "created_at"
    }

    struct Payload: Decodable, Sendable {
        let sessionID: String?
        let alertID: String?
        let reportID: String?

        enum CodingKeys: String, CodingKey {
            case sessionID = "session_id", alertID = "alert_id", reportID = "report_id"
        }
    }

    var route: NotificationRoute? {
        NotificationRoute(type: type, sessionID: data?.sessionID, alertID: data?.alertID, reportID: data?.reportID)
    }
}

struct NotificationsScreen: View {
    let account: Account
    let language: AppLanguage
    @State private var read = Set<UUID>()
    @State private var update = 0
    @State private var busy = false
    @State private var failed = false

    var body: some View {
        List {
            if failed { Text(language.text("common.unknownError")).foregroundStyle(.red) }
            PagedRows(account: account, language: language, endpoint: "notifications",
                      refreshID: update + account.dashboardRevision, emptyKey: "dashboard.notifications.emptyTitle") { (item: InboxNotification) in
                if let route = item.route {
                    NavigationLink {
                        ClinicalDestination(route: route, account: account, language: language)
                            .task { await readIfNeeded(item) }
                    } label: {
                        row(item)
                    }
                } else {
                    Button {
                        Task { await readIfNeeded(item) }
                    } label: {
                        row(item)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .navigationTitle(language.text("dashboard.notifications.title"))
        .refreshable { update += 1 }
        .toolbar {
            Button(language.text("dashboard.notifications.markAllRead")) { Task { await markRead(nil) } }
                .disabled(busy)
        }
    }

    private func row(_ item: InboxNotification) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(item.title).font(.headline)
                if !item.read && !read.contains(item.id) {
                    Text(language.text("dashboard.notifications.unreadBadge"))
                        .font(.caption).foregroundStyle(.tint)
                }
            }
            if let body = item.body { Text(body).foregroundStyle(.secondary) }
            Text(item.createdAt.formatted(.dateTime.month().day().hour().minute()))
                .font(.caption).foregroundStyle(.secondary)
        }
        .foregroundStyle(.primary)
    }

    private func readIfNeeded(_ item: InboxNotification) async {
        if !item.read && read.insert(item.id).inserted { await markRead(item.id) }
    }

    private func markRead(_ id: UUID?) async {
        if id == nil {
            guard !busy else { return }
            busy = true
        }
        defer { if id == nil { busy = false } }
        failed = false
        let endpoint = id.map { "notifications/\($0)/read" } ?? "notifications/read-all"
        do {
            try await account.api.request(endpoint, language: language, method: "PUT")
            if id == nil { update += 1 }
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {
            if let id { read.remove(id) }
            failed = true
        }
    }
}

struct ClinicalSettings: View {
    let user: User
    let account: Account
    let language: AppLanguage
    @AppStorage("appLanguage") private var appLanguage = ""
    @AppStorage("clinicalColorScheme") private var theme = ""
    @AppStorage("clinicalTextScale") private var textScale = 1.0
    @AppStorage("clinicalAlertSound") private var alertSound = true
    @Environment(\.openURL) private var openURL

    var body: some View {
        RecordScreen(account: account, language: language, endpoint: "auth/me", title: "common.doctor.settings.title") {
            (profile: Profile, _) in
            Section(language.text("common.doctor.settings.accountInfo")) {
                LabeledContent(language.text("common.doctor.settings.name"), value: user.name)
                LabeledContent(language.text("common.doctor.settings.email"), value: profile.email)
                LabeledContent(language.text("common.doctor.settings.role"), value: language.text("common.roles.\(user.role.rawValue)"))
                if let department = profile.department {
                    LabeledContent(language.text("common.doctor.settings.department"), value: department)
                }
                if let phone = profile.phone {
                    LabeledContent(language.text("common.doctor.settings.phone"), value: phone)
                }
            }
            Section(language.text("common.doctor.settings.appearance")) {
                Picker(language.text("common.doctor.settings.themeMode"), selection: $theme) {
                    Text(language.text("common.roles.system")).tag("")
                    Text(language.text("common.doctor.settings.themeLight")).tag("light")
                    Text(language.text("common.doctor.settings.themeDark")).tag("dark")
                }
                Picker(language.text("common.fontSize"), selection: $textScale) {
                    ForEach([1.0, 1.2, 1.4], id: \.self) { value in Text(value, format: .percent).tag(value) }
                }
                Picker(language.text("common.doctor.settings.languageLabel"), selection: Binding(
                    get: { language.rawValue }, set: { appLanguage = $0 }
                )) {
                    ForEach(AppLanguage.allCases) { item in Text(item.name).tag(item.rawValue) }
                }
            }
            Section(language.text("common.doctor.settings.notifications")) {
                Toggle(language.text("common.doctor.settings.soundAlerts"), isOn: $alertSound)
                Button(language.text("native.systemNotificationSettings")) {
                    if let url = URL(string: UIApplication.openNotificationSettingsURLString) { openURL(url) }
                }
            }
            Section(language.text("common.doctor.settings.systemInfo")) {
                LabeledContent(language.text("common.doctor.settings.apiEndpoint"), value: account.api.configuration.api.absoluteString)
            }
        }
    }

    private struct Profile: Decodable, Sendable {
        let email: String
        let department: String?
        let phone: String?
    }
}
