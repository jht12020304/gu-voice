import SwiftUI

@MainActor @Observable
final class KioskVisit {
    enum Step: Equatable {
        case intake(patient: UUID?)
        case conversation(UUID, AppLanguage)
        case thankYou(String)
    }

    var step: Step?
    private(set) var revision = 0
    var isConversing: Bool {
        if case .conversation = step { true } else { false }
    }

    func resume(_ session: ClinicalSession, fallback: AppLanguage) {
        step = .conversation(session.id, session.language.flatMap(AppLanguage.init(rawValue:)) ?? fallback)
    }

    func close() {
        step = nil
        revision += 1
    }
}

struct KioskVisitScreen: View {
    let visit: KioskVisit
    let account: Account
    let language: AppLanguage
    @AppStorage("appLanguage") private var saved = ""
    @State private var pendingLanguage: AppLanguage?
    @State private var creatingSession = false
    @State private var switching = false
    @State private var switchError = false

    var body: some View {
        NavigationStack {
            Group {
                switch visit.step {
                case let .intake(patient):
                    KioskIntakeScreen(account: account, language: language, patientID: patient,
                                      submitting: $creatingSession, onCancel: visit.close) { id in
                        visit.step = .conversation(id, language)
                    }
                case let .conversation(id, spoken):
                    KioskConversationScreen(account: account, sessionID: id, language: spoken) { status in
                        guard case .conversation(id, _) = visit.step else { return }
                        visit.step = .thankYou(status)
                    } onLeave: { visit.close() }
                    .id(id)
                case let .thankYou(status):
                    KioskThankYou(status: status, language: language, close: visit.close)
                case nil: EmptyView()
                }
            }
            .toolbar {
                if visit.isConversing || isIntake {
                    Menu {
                        ForEach(AppLanguage.allCases) { item in
                            Button(item.name) {
                                if case let .conversation(_, spoken) = visit.step {
                                    if item != spoken { pendingLanguage = item }
                                } else { saved = item.rawValue }
                            }
                        }
                    } label: {
                        Label(language.text("common.language.label"), systemImage: "globe")
                    }
                    .disabled(switching || creatingSession)
                }
            }
        }
        .background {
            if account.currentUser?.role == .patient && !visit.isConversing && account.kioskIdle.seconds > 0 {
                WindowActivityObserver { account.kioskIdle.activity() }.allowsHitTesting(false)
            }
        }
        .interactiveDismissDisabled()
        .confirmationDialog(language.text("common.language.switchModal.title"), isPresented: Binding(
            get: { pendingLanguage != nil }, set: { if !$0 { pendingLanguage = nil } }
        ), titleVisibility: .visible, presenting: pendingLanguage) { target in
            Button(language.text("common.language.switchModal.confirm"), role: .destructive) {
                Task { await switchLanguage(to: target) }
            }
            Button(language.text("common.cancel"), role: .cancel) {}
        } message: { target in
            if case let .conversation(_, spoken) = visit.step {
                Text(language.text("common.language.switchModal.description", args: ["from": spoken.name, "to": target.name]))
            }
        }
        .alert(language.text("common.language.switchModal.switchFailed"), isPresented: $switchError) {}
    }

    private var isIntake: Bool {
        if case .intake = visit.step { true } else { false }
    }

    private func switchLanguage(to target: AppLanguage) async {
        guard case let .conversation(id, _) = visit.step, !switching else { return }
        switching = true
        defer { switching = false }
        do {
            let body = try JSONEncoder().encode(["to_language": target.rawValue])
            try await account.api.request("sessions/\(id)/end-for-language-switch", language: language, method: "POST", body: body)
            guard account.currentUser != nil else { return }
            saved = target.rawValue
            visit.close()
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch { switchError = true }
    }
}

private struct KioskThankYou: View {
    let status: String
    let language: AppLanguage
    let close: () -> Void
    private var aborted: Bool { status == "aborted_red_flag" }

    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: aborted ? "exclamationmark.triangle.fill" : status == "completed" ? "checkmark.circle" : "pause.circle")
                .font(.largeTitle).foregroundStyle(aborted ? Color.red : Color.accentColor)
                .accessibilityHidden(true)
            Text(language.text(aborted ? "session.complete.redFlagTitle" : status == "completed" ? "session.thankYou.title" : "common.patient.home.statusCancelled"))
                .font(.title).accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("kiosk-terminal-\(status)")
            if status != "cancelled" {
                Text(language.text(aborted ? "ws.events.session.aborted_red_flag" : "session.thankYou.message"))
            }
            if status == "completed" { Text(language.text("session.thankYou.autoRedirectHint")).foregroundStyle(.secondary) }
            Button(language.text("session.thankYou.backNowAction"), action: close)
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("kiosk-return")
        }
        .multilineTextAlignment(.center).padding().frame(maxWidth: 580)
        .task {
            if aborted { AccessibilityNotification.Announcement(language.text("ws.events.session.aborted_red_flag")).post() }
            if status == "completed" {
                do { try await Task.sleep(for: .seconds(8)); close() } catch {}
            }
        }
    }
}
