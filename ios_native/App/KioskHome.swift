import SwiftUI

private enum PatientRoute: Hashable {
    case history, settings, record(UUID)
}

struct KioskHome: View {
    let user: User
    let account: Account
    let language: AppLanguage
    @Binding var path: NavigationPath
    @Environment(KioskVisit.self) private var visit

    var body: some View {
        List {
            Section {
                let hour = Calendar.current.component(.hour, from: Date())
                let greeting = hour < 12 ? "greetingMorning" : hour < 18 ? "greetingAfternoon" : "greetingEvening"
                Text(language.text("common.patient.home.\(greeting)") + "，" + user.name).font(.title2.bold())
                Text(language.text("common.patient.home.subtitle"))
                Button {
                    visit.step = .intake(patient: nil)
                } label: {
                    Label(language.text("common.patient.home.startTitle"), systemImage: "waveform.badge.plus")
                }
                .buttonStyle(.borderedProminent).controlSize(.large)
                .accessibilityIdentifier("kiosk-start")
            }
            Section(language.text("common.patient.home.recent")) {
                PatientSessions(account: account, language: language, recent: true)
                NavigationLink(language.text("common.patient.home.viewAll"), value: PatientRoute.history)
            }
            NavigationLink(language.text("common.patientLayout.personalSettings"), value: PatientRoute.settings)
        }
        .navigationTitle(language.text("common.appTitle"))
        .navigationDestination(for: PatientRoute.self) { route in
            switch route {
            case .history:
                List { PatientSessions(account: account, language: language, recent: false) }
                    .navigationTitle(language.text("common.patientLayout.history"))
            case .settings:
                KioskPatientSettings(user: user, account: account, language: language)
            case let .record(id):
                KioskPatientRecord(id: id, account: account, language: language) {
                    path = NavigationPath()
                } onHistory: {
                    path = NavigationPath([PatientRoute.history])
                }
            }
        }
    }
}

private struct PatientSessions: View {
    let account: Account
    let language: AppLanguage
    let recent: Bool
    @Environment(KioskVisit.self) private var visit
    @State private var result: Load<Page<ClinicalSession>> = .loading
    @State private var filter = "all"

    var body: some View {
        Group {
            if !recent {
                Picker(language.text("common.patientLayout.history"), selection: $filter) {
                    ForEach(["all", "completed", "in_progress", "cancelled"], id: \.self) { status in
                        Text(language.text("session.patientHistory.filters." + (status == "in_progress" ? "inProgress" : status))).tag(status)
                    }
                }
            }
            switch result {
            case let .loaded(page):
                let rows = page.data.filter { filter == "all" || $0.status == filter }
                if !recent { Text(language.text("session.patientHistory.sessionCount", args: ["count": String(page.data.count)])) }
                if rows.isEmpty {
                    Text(language.text(recent ? "common.patient.home.empty" : filter == "all" ? "session.patientHistory.emptyAll" : "session.patientHistory.emptyFiltered")).foregroundStyle(.secondary)
                }
                ForEach(rows) { session in
                    if ["waiting", "in_progress"].contains(session.status) {
                        Button { visit.resume(session, fallback: language) } label: { row(session) }
                    } else if ["completed", "aborted_red_flag"].contains(session.status) {
                        NavigationLink(value: PatientRoute.record(session.id)) { row(session) }
                    } else { row(session) }
                }
            case .loading, .signedOut: ProgressView()
            case .failed:
                Button(language.text("common.retry")) { Task { await load() } }
            }
        }
        .task(id: "\(language.rawValue)/\(visit.revision)") { await load() }
    }

    private func row(_ session: ClinicalSession) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(session.complaint ?? language.text("common.patient.home.defaultComplaint")).font(.headline)
            Text(session.createdAt.formatted(date: .abbreviated, time: .shortened))
            Text(language.text(sessionStatusKey(session.status)))
            if let seconds = session.duration {
                Text(language.text("common.patient.home.durationMinutes", args: ["minutes": String(Int((Double(seconds) / 60).rounded()))]))
            }
        }
    }

    private func load() async {
        let next = await Load<Page<ClinicalSession>>.fetch {
            // The API scopes patient requests by users.id -> patients.user_id. A user UUID is not a patient UUID.
            try await account.api.get("sessions", language: language, query: [.init(name: "limit", value: recent ? "5" : "50")])
        }
        guard !Task.isCancelled else { return }
        result = next
        if next.isSignedOut { await account.noticeAuthorizationLoss(language) }
    }
}
