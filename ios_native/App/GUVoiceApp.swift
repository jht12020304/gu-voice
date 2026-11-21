import OSLog
import SwiftUI

@main
struct GUVoiceApp: App {
    @UIApplicationDelegateAdaptor(PushNotifications.self) private var push
    @AppStorage("appLanguage") private var savedLanguage = ""
    @AppStorage("clinicalColorScheme") private var theme = ""
    @AppStorage("clinicalTextScale") private var textScale = 1.0
    @Environment(\.dynamicTypeSize) private var dynamicType
    @State private var account: Account?

    init() {
        #if DEBUG
        if ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil { return }
        #endif
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
                    RootScreen(account: account, push: push, savedLanguage: $savedLanguage, language: language)
                } else {
                    ContentUnavailableView(
                        language.text("native.configurationError"), systemImage: "exclamationmark.triangle"
                    )
                }
            }
            .environment(\.locale, Locale(identifier: language.rawValue))
            .environment(\.dynamicTypeSize, scaledType)
            .preferredColorScheme(theme == "dark" ? .dark : theme == "light" ? .light : nil)
        }
    }

    private var scaledType: DynamicTypeSize {
        let sizes = DynamicTypeSize.allCases
        guard let index = sizes.firstIndex(of: dynamicType) else { return dynamicType }
        let steps = textScale >= 1.4 ? 2 : textScale >= 1.2 ? 1 : 0
        return sizes[min(index + steps, sizes.count - 1)]
    }
}

@MainActor @Observable
final class Account {
    enum State {
        case starting, signedOut, unavailable, clearanceFailed, reauthenticate, signedIn(User)
    }

    let api: APIClient
    private(set) var state: State = .starting
    private(set) var dashboardRevision = 0
    private(set) var isWorking = false
    private(set) var credentialsUnavailable = false

    var currentUser: User? {
        if case let .signedIn(user) = state { return user }
        return nil
    }

    init(api: APIClient) {
        self.api = api
    }

    func restore(_ language: AppLanguage) async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false }
        credentialsUnavailable = false
        do {
            if let user = try await api.restore(language: language) { state = .signedIn(user) }
            else { state = .signedOut }
        } catch is PushCleanupPending {
            do {
                try await api.signOut(language: language)
                state = .signedOut
            } catch is PushCleanupReauthentication {
                state = .reauthenticate
            } catch {
                state = .clearanceFailed
            }
        } catch is CredentialClearancePending {
            state = .clearanceFailed
        } catch APIError.credentialsUnavailable {
            credentialsUnavailable = true
            state = .signedOut
        } catch {
            state = .unavailable
        }
    }

    func signIn(email: String, password: String, language: AppLanguage) async throws {
        guard !isWorking, !credentialsUnavailable else { return }
        isWorking = true
        defer { isWorking = false }
        if case .reauthenticate = state {
            do {
                try await api.reauthenticateForPushCleanup(email: email, password: password, language: language)
                state = .signedOut
            } catch is PushCleanupPending {
                state = .clearanceFailed
            }
        } else {
            do { state = .signedIn(try await api.signIn(email: email, password: password, language: language)) }
            catch is PushCleanupPending { state = .clearanceFailed }
        }
    }

    func signOut(_ language: AppLanguage) async {
        guard !isWorking else { return }
        isWorking = true
        state = .starting
        credentialsUnavailable = false
        defer { isWorking = false }
        do {
            try await api.signOut(language: language)
            state = .signedOut
        } catch is PushCleanupReauthentication {
            state = .reauthenticate
        } catch {
            state = .clearanceFailed
        }
    }

    func watchDashboard(user: UUID, language: AppLanguage) async {
        let logger = Logger(subsystem: "com.guvoice.guVoice", category: "dashboard")
        while !Task.isCancelled, currentUser?.id == user {
            do {
                let socket = try await api.dashboardConnection()
                await withTaskCancellationHandler {
                    await receiveDashboardEvents(socket, user: user)
                } onCancel: {
                    socket.cancel(with: .goingAway, reason: nil)
                }
                if socket.closeCode.rawValue == 4003 { return }
                if socket.closeCode.rawValue == 4001 {
                    let _: User = try await api.get("auth/me", language: language)
                }
            } catch APIError.signedOut {
                await noticeAuthorizationLoss(language)
                return
            } catch is CancellationError {
                return
            } catch {
                logger.debug("Dashboard socket connection failed (\((error as NSError).code, privacy: .public))")
            }
            do { try await Task.sleep(for: .seconds(8)) } catch { return }
        }
    }

    private func receiveDashboardEvents(_ socket: URLSessionWebSocketTask, user: UUID) async {
        let heartbeat = Task {
            while !Task.isCancelled {
                try await Task.sleep(for: .seconds(25))
                try await socket.send(.string("{\"type\":\"ping\"}"))
            }
        }
        defer {
            heartbeat.cancel()
            socket.cancel(with: .goingAway, reason: nil)
        }
        do {
            while !Task.isCancelled, currentUser?.id == user {
                let message = try await socket.receive()
                handleDashboardMessage(message, user: user)
            }
        } catch {}
    }

    private func handleDashboardMessage(_ message: URLSessionWebSocketTask.Message, user: UUID) {
        guard currentUser?.id == user else { return }
        struct Envelope: Decodable { let type: String }
        let data: Data
        switch message {
        case let .string(value): data = Data(value.utf8)
        case let .data(value): data = value
        @unknown default: return
        }
        guard let event = try? JSONDecoder().decode(Envelope.self, from: data),
              event.type != "pong" else { return }
        dashboardRevision += 1
    }

    func noticeAuthorizationLoss(_ language: AppLanguage) async {
        let active = await api.hasSession
        guard !isWorking, !active else { return }
        if await api.needsPushCleanup { await signOut(language) }
        else { state = .signedOut }
    }
}

private struct RootScreen: View {
    @Environment(\.scenePhase) private var scenePhase
    let account: Account
    let push: PushNotifications
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
                case .reauthenticate:
                    LoginScreen(account: account, language: language, recovering: true)
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
                        .navigationDestination(for: NotificationRoute.self) { route in
                            ClinicalDestination(route: route, account: account, language: language)
                        }
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
                                    path = NavigationPath()
                                    push.deactivate()
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
        .onChange(of: activeUserID) {
            path = NavigationPath()
            if activeUserID == nil { push.deactivate() }
            openPush()
        }
        .onChange(of: push.tappedRoute) { openPush() }
        .onChange(of: accountHasNoAccessibleSession) {
            if accountHasNoAccessibleSession { push.deactivate() }
        }
        .task(id: waitingForCleanup && scenePhase == .active) {
            if waitingForCleanup && scenePhase == .active { await push.prepareCleanup(account: account, language: language) }
        }
        .task { await account.restore(language) }
        .task(id: [activeUserID?.uuidString ?? "", language.rawValue]) {
            guard let user = account.currentUser, user.role != .patient else { return }
            await account.watchDashboard(user: user.id, language: language)
        }
        .task(id: PushActivation(user: activeUserID, phase: scenePhase, language: language)) {
            guard scenePhase == .active else { return }
            if case .clearanceFailed = account.state { await account.signOut(language) }
            if let user = account.currentUser {
                await push.activate(account: account, user: user, language: language)
            }
        }
    }

    private var waitingForCleanup: Bool {
        if case .clearanceFailed = account.state { return true }
        return false
    }

    private var accountHasNoAccessibleSession: Bool {
        switch account.state {
        case .signedOut, .unavailable, .clearanceFailed, .reauthenticate: true
        case .signedIn, .starting: false
        }
    }

    private var activeUserID: UUID? {
        if case let .signedIn(user) = account.state { return user.id }
        return nil
    }

    private struct PushActivation: Equatable {
        let user: UUID?
        let phase: ScenePhase
        let language: AppLanguage
    }

    private func openPush() {
        guard let user = account.currentUser, user.role != .patient,
              let route = push.takeRoute() else { return }
        path.append(route)
    }

    @ViewBuilder
    private func landing(_ user: User) -> some View {
        switch user.role {
        case .doctor, .admin:
            ClinicalHome(user: user, account: account, language: language)
        case .patient:
            ContentUnavailableView(
                language.text("native.patientKiosk"), systemImage: "ipad",
                description: Text(language.text("native.kioskPlaceholder"))
            )
            .navigationTitle(user.name)
        }
    }
}

private struct LoginScreen: View {
    let account: Account
    let language: AppLanguage
    var recovering = false
    @State private var email = ""
    @State private var password = ""
    @State private var errorKey: String?
    @FocusState private var focus: Field?

    private enum Field { case email, password }

    var body: some View {
        Form {
            Section(language.text(recovering ? "native.pushReauthentication" : "common.login.prompt")) {
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
                .disabled(account.isWorking || account.credentialsUnavailable || email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || password.isEmpty)
                .accessibilityIdentifier("login-submit")
            } footer: {
                if let errorKey {
                    Text(language.text(errorKey)).foregroundStyle(.red)
                } else if account.credentialsUnavailable {
                    Text(language.text("native.restoreFailed"))
                    Button(language.text("common.retry")) { Task { await account.restore(language) } }
                }
            }
        }
        .navigationTitle("UroSense")
    }

    private func submit() {
        let address = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !account.isWorking, !account.credentialsUnavailable, !address.isEmpty, !password.isEmpty else { return }
        errorKey = nil
        focus = nil
        Task {
            do {
                try await account.signIn(email: address, password: password, language: language)
                password = ""
            } catch is PushCleanupReauthentication {
                errorKey = "native.pushReauthentication"
            } catch APIError.status(401) {
                errorKey = "native.invalidLogin"
            } catch APIError.status(403) {
                errorKey = "native.accountDisabled"
            } catch APIError.status(429) {
                errorKey = "native.loginThrottled"
            } catch {
                errorKey = "native.loginFailed"
            }
        }
    }
}
