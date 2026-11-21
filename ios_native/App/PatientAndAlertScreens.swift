import SwiftUI

private struct ClinicalPatient: Decodable, Identifiable, Sendable {
    let id: UUID
    let name: String
    let recordNumber: String
    let gender: String
    let birthDate: String
    let phone: String?
    let createdAt: Date
    let history: [[String: ClinicalValue]]?
    let allergies: [[String: ClinicalValue]]?
    let medications: [[String: ClinicalValue]]?

    enum CodingKeys: String, CodingKey {
        case id, name, gender, phone, allergies
        case recordNumber = "medical_record_number", birthDate = "date_of_birth", createdAt = "created_at"
        case history = "medical_history", medications = "current_medications"
    }
}

struct PatientsScreen: View {
    let account: Account
    let language: AppLanguage
    @State private var search = ""
    @State private var month: Date?
    @State private var update = 0

    private var query: [URLQueryItem] {
        let text = search.trimmingCharacters(in: .whitespacesAndNewlines)
        var query: [URLQueryItem] = text.isEmpty ? [] : [.init(name: "search", value: text)]
        if let month, let range = Calendar.current.dateInterval(of: .month, for: month) {
            query += LocalDateRange(start: range.start, end: range.end, calendar: .current).query.map {
                URLQueryItem(name: $0.name == "date_from" ? "created_from" : "created_to", value: $0.value)
            }
        }
        return query
    }

    var body: some View {
        List {
            Section {
                Toggle(language.text("common.patientList.newPatientsInMonth", args: [
                    "month": (month ?? Date()).formatted(.dateTime.year().month(.wide).locale(Locale(identifier: language.rawValue)))
                ]), isOn: Binding(
                    get: { month != nil }, set: { month = $0 ? Date() : nil }
                ))
                if let month {
                    HStack {
                        Button { shift(-1) } label: { Image(systemName: "chevron.left") }
                            .accessibilityLabel(language.text("common.patientList.previousMonth"))
                        Spacer()
                        Text(month.formatted(.dateTime.year().month(.wide)))
                        Spacer()
                        Button { shift(1) } label: { Image(systemName: "chevron.right") }
                            .accessibilityLabel(language.text("common.patientList.nextMonth"))
                    }
                    .buttonStyle(.borderless)
                }
            }
            PagedRows(account: account, language: language, endpoint: "patients", query: query, refreshID: update,
                      emptyKey: "common.patientList.emptySearchMessage") { (patient: ClinicalPatient) in
                NavigationLink {
                    PatientDetailScreen(id: patient.id, account: account, language: language) { update += 1 }
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(patient.name).font(.headline)
                        Text(verbatim: patient.recordNumber).font(.subheadline)
                        Text(patient.phone ?? language.text("common.patientList.noPhone"))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .navigationTitle(language.text("common.patientList.title"))
        .searchable(text: $search, prompt: language.text("common.patientList.searchPlaceholder"))
        .refreshable { update += 1 }
    }

    private func shift(_ amount: Int) {
        if let month { self.month = Calendar.current.date(byAdding: .month, value: amount, to: month) }
    }
}

private struct PatientDetailScreen: View {
    let id: UUID
    let account: Account
    let language: AppLanguage
    let onDelete: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var confirm = false
    @State private var busy = false
    @State private var failed = false

    var body: some View {
        RecordScreen(account: account, language: language, endpoint: "patients/\(id)", title: "common.doctor.patient.title") {
            (patient: ClinicalPatient, _) in
            Section(patient.name) {
                Text(verbatim: patient.recordNumber)
                Text(language.text("common.gender.\(patient.gender)"))
                LabeledContent(language.text("common.doctor.patient.labels.dateOfBirth"), value: patient.birthDate)
                Text(patient.phone ?? language.text("common.doctor.patient.noPhone"))
                LabeledContent(language.text("common.doctor.patient.labels.createdAt"),
                               value: patient.createdAt.formatted(.dateTime.year().month().day()))
            }
            history(patient.history, key: "medicalHistory")
            history(patient.allergies, key: "allergies")
            history(patient.medications, key: "currentMedications")
            PagedRows(account: account, language: language, endpoint: "patients/\(id)/sessions",
                      emptyKey: "common.doctor.patient.noSessions",
                      sectionTitle: language.text("common.doctor.patient.historyTitle")) { (session: ClinicalSession) in
                SessionRow(session: session, account: account, language: language)
            }
            Section {
                Button(language.text("common.doctor.patient.delete"), role: .destructive) { confirm = true }
                    .disabled(busy)
                if failed { Text(language.text("common.doctor.patient.deleteError")).foregroundStyle(.red) }
            }
            .confirmationDialog(language.text("common.doctor.patient.deleteTitle"), isPresented: $confirm) {
                Button(language.text("common.doctor.patient.confirmDelete"), role: .destructive) {
                    Task { await delete() }
                }
            } message: {
                Text(language.text("common.doctor.patient.deleteConfirm", args: ["name": patient.name]))
            }
        }
    }

    @ViewBuilder private func history(_ rows: [[String: ClinicalValue]]?, key: String) -> some View {
        if let rows, !rows.isEmpty {
            Section(language.text("common.doctor.patient.\(key)")) {
                ForEach(Array(rows.enumerated()), id: \.offset) { _, values in
                    let fields = ClinicalRows(language: language, section: "subjective").fields(values)
                    ForEach(fields) { field in LabeledContent(field.label, value: field.content) }
                }
            }
        }
    }

    private func delete() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            try await account.api.request("patients/\(id)", language: language, method: "DELETE")
            onDelete()
            dismiss()
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch { failed = true }
    }
}

private struct ClinicalAlert: Decodable, Identifiable, Sendable {
    let id: UUID
    let sessionID: UUID
    let title: String
    let severity: String
    let triggerReason: String
    let createdAt: Date
    let description: String?
    let actions: [String]?
    let keywords: [String]?
    let acknowledgedAt: Date?
    let actionTaken: String?
    let notes: String?
    let analysis: [String: ClinicalValue]?
    let confidence: String?

    enum CodingKeys: String, CodingKey {
        case id, title, severity, description, confidence
        case sessionID = "session_id", triggerReason = "trigger_reason", createdAt = "created_at"
        case actions = "suggested_actions", keywords = "trigger_keywords", acknowledgedAt = "acknowledged_at"
        case actionTaken = "action_taken", notes = "acknowledge_notes", analysis = "llm_analysis"
    }
}

struct AlertsScreen: View {
    let account: Account
    let language: AppLanguage
    @State private var filter = ""
    @State private var search = ""
    @State private var awaitingConfirm = false
    @State private var busy = false
    @State private var failed = false
    @State private var update = 0

    var body: some View {
        List {
            Section {
                Picker(language.text("dashboard.sidebar.nav.redFlagAlerts"), selection: $filter) {
                    Text(language.text("dashboard.alertList.filters.all")).tag("")
                    Text(language.text("dashboard.alert.pending")).tag("false")
                    Text(language.text("dashboard.alert.detail.acknowledgedBadge")).tag("true")
                }
                Button(language.text("dashboard.alertList.acknowledgeAll")) { awaitingConfirm = true }
                    .disabled(busy)
                if failed { Text(language.text("dashboard.alert.detail.acknowledgeError")).foregroundStyle(.red) }
            }
            PagedRows(account: account, language: language, endpoint: "alerts",
                      query: filter.isEmpty ? [] : [.init(name: "is_acknowledged", value: filter)], refreshID: update + account.dashboardRevision,
                      emptyKey: "dashboard.alertList.emptyTitle", matches: { alert in
                search.isEmpty || alert.title.localizedCaseInsensitiveContains(search)
                    || alert.triggerReason.localizedCaseInsensitiveContains(search)
            }) { (alert: ClinicalAlert) in
                NavigationLink {
                    AlertDetailScreen(id: alert.id, account: account, language: language, onChange: { update += 1 })
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(alert.title).font(.headline)
                        Text(alert.triggerReason).lineLimit(2)
                        Text(language.text("native.severity.\(alert.severity)")).font(.caption).foregroundStyle(.red)
                        Text(alert.createdAt.formatted(.dateTime.month().day().hour().minute())).font(.caption)
                    }
                }
            }
        }
        .navigationTitle(language.text("dashboard.sidebar.nav.redFlagAlerts"))
        .searchable(text: $search, prompt: language.text("dashboard.alertList.searchPlaceholder"))
        .refreshable { update += 1 }
        .confirmationDialog(language.text("dashboard.alertList.acknowledgeAll"), isPresented: $awaitingConfirm) {
            Button(language.text("dashboard.alertList.acknowledgeAll")) { Task { await acknowledgeAll() } }
        } message: {
            Text(language.text("dashboard.alertList.acknowledgeAllConfirm"))
        }
    }

    private func acknowledgeAll() async {
        guard !busy else { return }
        busy = true
        failed = false
        defer { busy = false; update += 1 }
        do {
            try await account.api.request("alerts/acknowledge-all", language: language, method: "POST")
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch { failed = true }
    }
}

struct AlertDetailScreen: View {
    let id: UUID
    let account: Account
    let language: AppLanguage
    var onChange: () -> Void = {}

    @State private var action = ""
    @State private var notes = ""
    @State private var busy = false
    @State private var failed = false

    var body: some View {
        RecordScreen(account: account, language: language, endpoint: "alerts/\(id)", title: "dashboard.alert.detail.title") {
            (alert: ClinicalAlert, reload) in
            Section(alert.title) {
                Text(language.text("native.severity.\(alert.severity)")).foregroundStyle(.red)
                if let description = alert.description { Text(description) }
                Text(language.text("dashboard.alert.triggerLabel", args: ["value": alert.triggerReason]))
                LabeledContent(language.text("dashboard.alert.detail.occurredAt"),
                               value: alert.createdAt.formatted(.dateTime.month().day().hour().minute()))
                NavigationLink(language.text("session.doctor.detail.title")) {
                    SessionDetailScreen(id: alert.sessionID, account: account, language: language)
                }
            }
            Section(language.text("dashboard.alert.detail.triggerKeywords")) {
                let keywords = alert.keywords ?? []
                Text(keywords.isEmpty ? language.text("dashboard.alert.detail.noKeywords") : keywords.joined(separator: ", "))
            }
            Section(language.text("dashboard.alert.detail.suggestedActions")) {
                let actions = alert.actions ?? []
                if actions.isEmpty { Text(language.text("dashboard.alert.detail.noSuggestedActions")) }
                ForEach(Array(actions.enumerated()), id: \.offset) { _, action in Text(action) }
            }
            if let values = alert.analysis, !values.isEmpty {
                Section(language.text("dashboard.alert.detail.llmAnalysis")) {
                    ForEach(ClinicalRows(language: language, section: "assessment").fields(values)) { field in
                        LabeledContent(field.label, value: field.content)
                    }
                }
            }
            if let date = alert.acknowledgedAt {
                Section(language.text("dashboard.alert.detail.acknowledgedHeading")) {
                    Text(date.formatted(.dateTime.month().day().hour().minute()))
                    if let action = alert.actionTaken { Text(action) }
                    if let notes = alert.notes { Text(notes) }
                }
            } else {
                Section(language.text("dashboard.alert.acknowledge")) {
                    TextField(language.text("dashboard.alert.detail.actionTakenPlaceholder"), text: $action, axis: .vertical)
                    TextField(language.text("dashboard.alert.detail.notesPlaceholder"), text: $notes, axis: .vertical)
                    Button(language.text("dashboard.alert.acknowledge")) { Task { await acknowledge(reload) } }
                        .disabled(busy)
                    if failed { Text(language.text("dashboard.alert.detail.acknowledgeError")).foregroundStyle(.red) }
                }
            }
        }
    }

    private func acknowledge(_ reload: () async -> Void) async {
        guard !busy else { return }
        busy = true
        failed = false
        defer { busy = false }
        do {
            let fields = ["action_taken": action, "acknowledge_notes": notes]
                .mapValues { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.value.isEmpty }
            let body = try JSONEncoder().encode(fields)
            try await account.api.request("alerts/\(id)/acknowledge", language: language, method: "POST", body: body)
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
            return
        } catch { failed = true }
        onChange()
        await reload()
    }
}
