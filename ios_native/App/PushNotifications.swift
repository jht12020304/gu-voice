@preconcurrency import FirebaseCore
@preconcurrency import FirebaseMessaging
import SwiftUI
import UserNotifications

enum NotificationRoute: Hashable, Sendable {
    case order(UUID), session(UUID), alert(UUID)

    init?(type: String?, sessionID: String?, alertID: String?, reportID: String?) {
        if let alertID, let id = UUID(uuidString: alertID) {
            self = .alert(id)
        } else if let sessionID, let id = UUID(uuidString: sessionID) {
            self = (type == "report_ready" || (type == nil && reportID != nil)) ? .order(id) : .session(id)
        } else {
            return nil
        }
    }
}

@MainActor @Observable
final class PushNotifications: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate, MessagingDelegate {
    private(set) var tappedRoute: NotificationRoute?
    private var account: Account?
    private var owner: UUID?
    private var acceptsColdTap = true
    private var cleanupAccount: Account?
    private var language: AppLanguage = .traditionalChinese
    private var apnsToken: Data?
    private var latestToken: String?
    private var completed: String?
    private var syncing = false

    func application(
        _ application: UIApplication, didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func activate(account: Account, user: User, language: AppLanguage) async {
        guard user.role != .patient, account.currentUser?.id == user.id else { return }
        self.account = account
        self.owner = user.id
        self.language = language
        acceptsColdTap = false
        guard configureFirebase() else { return }
        let center = UNUserNotificationCenter.current()
        let settings = await center.notificationSettings()
        if settings.authorizationStatus == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .badge, .sound])
        }
        guard owner == user.id, account.currentUser?.id == user.id else { return }
        UIApplication.shared.registerForRemoteNotifications()
        if apnsToken != nil { await fetchToken() }
    }

    func prepareCleanup(account: Account, language: AppLanguage) async {
        guard await account.api.needsDeviceIdentity, configureFirebase() else { return }
        cleanupAccount = account
        self.language = language
        if let apnsToken {
            await captureForCleanup(apnsToken)
        } else {
            UIApplication.shared.registerForRemoteNotifications()
        }
    }

    private func configureFirebase() -> Bool {
        let environment = ProcessInfo.processInfo.environment
        guard environment["GUVOICE_DISABLE_REMOTE_PUSH"] != "1", environment["XCTestConfigurationFilePath"] == nil else {
            return false
        }
        if FirebaseApp.app() == nil {
            FirebaseApp.configure()
            Messaging.messaging().delegate = self
        }
        return true
    }

    private func captureForCleanup(_ token: Data) async {
        guard let account = cleanupAccount else { return }
        do {
            try await account.api.captureLegacyDevice(apnsToken: hex(token), fcmToken: Messaging.messaging().fcmToken)
            cleanupAccount = nil
            await account.signOut(language)
        } catch {}
    }

    func deactivate() {
        account = nil
        owner = nil
        completed = nil
        acceptsColdTap = false
        tappedRoute = nil
        UNUserNotificationCenter.current().removeAllDeliveredNotifications()
        UNUserNotificationCenter.current().removeAllPendingNotificationRequests()
        Task { try? await UNUserNotificationCenter.current().setBadgeCount(0) }
    }

    func takeRoute() -> NotificationRoute? {
        defer { tappedRoute = nil }
        return tappedRoute
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken token: Data) {
        guard FirebaseApp.app() != nil else { return }
        if apnsToken != token {
            apnsToken = token
            latestToken = nil
            completed = nil
        }
        Messaging.messaging().apnsToken = token
        Task {
            await captureForCleanup(token)
            await fetchToken()
        }
    }

    private func fetchToken() async {
        guard owner != nil, apnsToken != nil else { return }
        guard let token = try? await Messaging.messaging().token() else { return }
        latestToken = token
        await sync()
    }

    nonisolated func messaging(_ messaging: Messaging, didReceiveRegistrationToken token: String?) {
        guard let token, !token.isEmpty else { return }
        Task { @MainActor in
            guard apnsToken != nil else { return }
            latestToken = token
            await sync()
        }
    }

    private func sync() async {
        guard !syncing else { return }
        syncing = true
        defer { syncing = false }
        while let account, let owner, let apnsToken, let token = latestToken,
              completed != token, account.currentUser?.id == owner {
            do {
                try await account.api.registerPush(
                    user: owner, token: token,
                    apnsToken: hex(apnsToken), language: language
                )
                if self.owner == owner, self.apnsToken == apnsToken { completed = token }
            } catch {
                if self.owner == owner { break }
            }
        }
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse
    ) async {
        let payload = response.notification.request.content.userInfo
        guard let route = NotificationRoute(
            type: payload["type"] as? String, sessionID: payload["session_id"] as? String,
            alertID: payload["alert_id"] as? String, reportID: payload["report_id"] as? String
        ) else { return }
        await setRoute(route)
    }

    private func setRoute(_ route: NotificationRoute) {
        guard acceptsColdTap || account?.currentUser?.id == owner && owner != nil else { return }
        tappedRoute = route
    }

    private func hex(_ token: Data) -> String {
        token.map { String(format: "%02x", $0) }.joined()
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        await presentation()
    }

    private func presentation() -> UNNotificationPresentationOptions {
        guard owner != nil, account?.currentUser?.id == owner else { return [] }
        let audible = UserDefaults.standard.object(forKey: "clinicalAlertSound") as? Bool ?? true
        return audible ? [.banner, .list, .badge, .sound] : [.banner, .list, .badge]
    }
}
