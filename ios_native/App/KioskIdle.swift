import SwiftUI
import UIKit

@MainActor
final class KioskIdleTimer {
    let seconds: TimeInterval
    private var deadline: Date?
    private let defaults: UserDefaults?
    private var key: String?
    private var lastPersisted: Date?
    init(setting: String? = Bundle.main.object(forInfoDictionaryKey: "KIOSK_IDLE_TIMEOUT_SECONDS") as? String, defaults: UserDefaults? = nil) {
        self.defaults = defaults
        seconds = TimeInterval(max(0, setting.flatMap(Int.init) ?? 180))
    }

    func start(patient: UUID, restoring: Bool, at now: Date = Date()) {
        lastPersisted = nil
        key = "kioskDeadline.\(patient.uuidString)"
        if restoring, seconds > 0, let key, let stored = defaults?.object(forKey: key) as? Date {
            deadline = stored
        } else {
            deadline = nil
            activity(at: now)
        }
    }

    func activity(at now: Date = Date()) {
        guard seconds > 0, deadline.map({ $0 > now }) ?? true else { return }
        deadline = now.addingTimeInterval(seconds)
        if let key, lastPersisted.map({ now.timeIntervalSince($0) >= 1 }) ?? true {
            defaults?.set(deadline, forKey: key)
            lastPersisted = now
        }
    }

    func clear() {
        if let key { defaults?.removeObject(forKey: key) }
        key = nil
        deadline = nil
    }

    func cancel() { deadline = nil }

    func remaining(at now: Date = Date()) -> TimeInterval? {
        deadline.map { max(0, $0.timeIntervalSince(now)) }
    }
}

struct KioskIdleLogout: ViewModifier {
    let account: Account
    let language: AppLanguage
    let enabled: Bool
    @Environment(\.scenePhase) private var scenePhase
    private var timer: KioskIdleTimer { account.kioskIdle }

    func body(content: Content) -> some View {
        content
            .background {
                if enabled && timer.seconds > 0 {
                    WindowActivityObserver { timer.activity() }.allowsHitTesting(false)
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: UITextField.textDidChangeNotification)) { _ in
                if enabled { timer.activity() }
            }
            .onReceive(NotificationCenter.default.publisher(for: UITextView.textDidChangeNotification)) { _ in
                if enabled { timer.activity() }
            }
            .task(id: enabled ? account.currentUser?.id : nil) { await waitForIdleLogout() }
            .onChange(of: scenePhase) {
                if enabled, scenePhase == .active, let patient = account.currentUser?.id, timer.remaining() == 0 {
                    signOutIfExpired(patient)
                }
            }
    }

    func waitForIdleLogout() async {
        guard enabled, let patient = account.currentUser?.id else { timer.cancel(); return }
        if timer.remaining() == nil { timer.activity() }
        while !Task.isCancelled, let delay = timer.remaining() {
            if delay == 0 {
                await signOutIfExpired(patient).value
                return
            }
            do { try await Task.sleep(for: .seconds(delay)) } catch { return }
        }
    }

    @discardableResult
    private func signOutIfExpired(_ patient: UUID) -> Task<Void, Never> {
        // Clearing currentUser cancels the view's timer task. Revocation must finish independently.
        Task {
            guard account.currentUser?.id == patient, timer.remaining() == 0 else { return }
            await account.signOut(language)
        }
    }
}

// Observe the window so sheets, scrolling and native controls reset the same deadline.
struct WindowActivityObserver: UIViewRepresentable {
    let activity: () -> Void
    func makeUIView(context: Context) -> Observer {
        let view = Observer()
        view.observer.activity = activity
        return view
    }
    func updateUIView(_ view: Observer, context: Context) { view.observer.activity = activity }
    static func dismantleUIView(_ view: Observer, coordinator: Void) { view.observer.view?.removeGestureRecognizer(view.observer) }

    final class Observer: UIView {
        let observer = ActivityRecognizer()
        override func didMoveToWindow() {
            super.didMoveToWindow()
            observer.view?.removeGestureRecognizer(observer)
            window?.addGestureRecognizer(observer)
        }
    }

    final class ActivityRecognizer: UIGestureRecognizer {
        var activity: (() -> Void)?
        override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent) { activity?(); state = .failed }
        override func pressesBegan(_ presses: Set<UIPress>, with event: UIPressesEvent) { activity?(); state = .failed }
        override func canPrevent(_ other: UIGestureRecognizer) -> Bool { false }
        override func canBePrevented(by other: UIGestureRecognizer) -> Bool { false }
    }
}
