import SwiftUI

@main
struct GUVoiceApp: App {
    @AppStorage("appLanguage") private var savedLanguage = ""
    @State private var account: Account?

    init() {
        if let settings = Bundle.main.infoDictionary,
           let configuration = try? Configuration(settings: settings) {
            let credentials = Credentials(service: "com.guvoice.guVoice.native.\(configuration.api.absoluteString)")
            _account = State(initialValue: Account(api: APIClient(configuration: configuration, credentials: credentials)))
        }
    }

    var body: some Scene {
        WindowGroup {
            let language = AppLanguage.resolve(saved: savedLanguage)
            Group {
                if let account {
                    RootScreen(account: account, savedLanguage: $savedLanguage, language: language)
                } else {
                    ContentUnavailableView(
                        language.text("native.configurationError"), systemImage: "exclamationmark.triangle"
                    )
                }
            }
            .environment(\.locale, Locale(identifier: language.rawValue))
        }
    }
}

@MainActor @Observable
final class Account {
    enum State {
        case starting, signedOut, unavailable, clearanceFailed, signedIn(User)
    }

    let api: APIClient
    private(set) var state: State = .starting
    private(set) var isWorking = false

    init(api: APIClient) {
        self.api = api
    }

    func restore(_ language: AppLanguage) async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false }
        do {
            if let user = try await api.restore(language: language) { state = .signedIn(user) }
            else { state = .signedOut }
        } catch {
            state = .unavailable
        }
    }

    func signIn(email: String, password: String, language: AppLanguage) async throws {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false }
        state = .signedIn(try await api.signIn(email: email, password: password, language: language))
    }

    func signOut(_ language: AppLanguage) async {
        guard !isWorking else { return }
        isWorking = true
        state = .starting
        defer { isWorking = false }
        do {
            try await api.signOut(language: language)
            state = .signedOut
        } catch {
            state = .clearanceFailed
        }
    }

    func noticeAuthorizationLoss() async {
        let active = await api.hasSession
        guard !isWorking, !active else { return }
        state = .signedOut
    }
}

private struct RootScreen: View {
    let account: Account
    @Binding var savedLanguage: String
    let language: AppLanguage
    @State private var path = NavigationPath()

    var body: some View {
        NavigationStack(path: $path) {
            Group {
                switch account.state {
                case .starting:
                    ProgressView(language.text("common.loading"))
                case .signedOut:
                    LoginScreen(account: account, language: language)
                case .unavailable:
                    ContentUnavailableView {
                        Label(language.text("native.restoreFailed"), systemImage: "exclamationmark.triangle")
                    } actions: {
                        Button(language.text("common.retry")) { Task { await account.restore(language) } }
                        Button(language.text("common.header.logout"), role: .destructive) {
                            Task { await account.signOut(language) }
                        }
                    }
                case .clearanceFailed:
                    ContentUnavailableView {
                        Label(language.text("native.logoutFailed"), systemImage: "exclamationmark.triangle")
                    } actions: {
                        Button(language.text("common.retry")) { Task { await account.signOut(language) } }
                    }
                case let .signedIn(user):
                    landing(user)
                        .id(user.id)
                }
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Picker(
                            language.text("common.language.label"),
                            selection: Binding(get: { language.rawValue }, set: { savedLanguage = $0 })
                        ) {
                            ForEach(AppLanguage.allCases) { item in
                                Text(item.name).tag(item.rawValue)
                            }
                        }
                        if case let .signedIn(user) = account.state {
                            Section(user.name) {
                                Button(role: .destructive) {
                                    Task { await account.signOut(language) }
                                } label: {
                                    Label(language.text("common.header.logout"), systemImage: "rectangle.portrait.and.arrow.right")
                                }
                                .accessibilityIdentifier("sign-out")
                            }
                        }
                    } label: {
                        Label(language.text("common.header.settings"), systemImage: "ellipsis.circle")
                    }
                    .accessibilityIdentifier("account-menu")
                }
            }
        }
        .onChange(of: activeUserID) { path = NavigationPath() }
        .task { await account.restore(language) }
    }

    private var activeUserID: UUID? {
        if case let .signedIn(user) = account.state { return user.id }
        return nil
    }

    @ViewBuilder
    private func landing(_ user: User) -> some View {
        switch user.role {
        case .doctor:
            ReportListScreen(account: account, language: language)
        case .admin, .patient:
            let isAdmin = user.role == .admin
            ContentUnavailableView(
                language.text(isAdmin ? "common.roles.admin" : "native.patientKiosk"),
                systemImage: isAdmin ? "person.badge.key" : "ipad",
                description: Text(language.text(isAdmin ? "native.adminPlaceholder" : "native.kioskPlaceholder"))
            )
            .navigationTitle(user.name)
        }
    }
}

private struct LoginScreen: View {
    let account: Account
    let language: AppLanguage
    @State private var email = ""
    @State private var password = ""
    @State private var errorKey: String?
    @FocusState private var focus: Field?

    private enum Field { case email, password }

    var body: some View {
        Form {
            Section(language.text("common.login.prompt")) {
                TextField(language.text("common.login.emailLabel"), text: $email)
                    .textContentType(.username)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.next)
                    .focused($focus, equals: .email)
                    .onSubmit { focus = .password }
                    .accessibilityIdentifier("login-email")
                SecureField(language.text("common.login.passwordLabel"), text: $password)
                    .textContentType(.password)
                    .submitLabel(.go)
                    .focused($focus, equals: .password)
                    .onSubmit { submit() }
                    .accessibilityIdentifier("login-password")
            }
            Section {
                Button(action: submit) {
                    if account.isWorking {
                        ProgressView(language.text("common.login.submitting"))
                    } else {
                        Text(language.text("common.login.submit"))
                            .fontWeight(.semibold)
                    }
                }
                .disabled(account.isWorking || email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || password.isEmpty)
                .accessibilityIdentifier("login-submit")
            } footer: {
                if let errorKey {
                    Text(language.text(errorKey)).foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("UroSense")
    }

    private func submit() {
        let address = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !account.isWorking, !address.isEmpty, !password.isEmpty else { return }
        errorKey = nil
        focus = nil
        Task {
            do {
                try await account.signIn(email: address, password: password, language: language)
                password = ""
            } catch APIError.status(401) {
                errorKey = "native.invalidLogin"
            } catch APIError.status(429) {
                errorKey = "native.loginThrottled"
            } catch {
                errorKey = "native.loginFailed"
            }
        }
    }
}
