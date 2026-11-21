import SwiftUI

struct KioskPatientSettings: View {
    let user: User
    let account: Account
    let language: AppLanguage
    @AppStorage("appLanguage") private var appLanguage = ""
    @AppStorage("clinicalTextScale") private var textScale = 1.0
    @State private var tab = "tabProfile"
    @State private var phone: String?
    @State private var emailNotifications = true
    @State private var pushNotifications = false
    @State private var changingPassword = false
    @State private var saving = false
    @State private var message: String?

    private struct Profile: Decodable, Sendable {
        let email: String
        let phone: String?
    }

    private func t(_ key: String) -> String { language.text("common.patient.settings." + key) }

    var body: some View {
        RecordScreen(account: account, language: language, endpoint: "auth/me", title: "common.patient.settings.tabProfile") {
            (profile: Profile, _) in
            Picker(t("tabProfile"), selection: $tab) {
                ForEach(["tabProfile", "tabNotifications", "tabSecurity"], id: \.self) { key in
                    Text(t(key)).tag(key)
                }
            }
            .pickerStyle(.segmented)
            switch tab {
            case "tabNotifications":
                Section(t("notificationsTitle")) {
                    // Flutter keeps these two switches on the settings page for this visit.
                    Toggle(isOn: $emailNotifications) { Text(t("emailNotifications")); Text(t("emailNotificationsHint")) }
                    Toggle(isOn: $pushNotifications) { Text(t("pushNotifications")); Text(t("pushNotificationsHint")) }
                }
            case "tabSecurity":
                Section(t("securityTitle")) {
                    Button(t("changePassword")) { changingPassword = true }
                    Text(t("changePasswordHint")).font(.footnote).foregroundStyle(.secondary)
                }
            default:
                Section(t("profileTitle")) {
                    LabeledContent(t("fullName"), value: user.name)
                    LabeledContent(t("emailLabel"), value: profile.email)
                    TextField(t("phoneLabel"), text: Binding(
                        get: { phone ?? profile.phone ?? "" }, set: { phone = $0 }
                    ))
                    .keyboardType(.phonePad)
                    .textContentType(.telephoneNumber)
                    Picker(t("preferredLanguage"), selection: Binding(
                        get: { language.rawValue }, set: { appLanguage = $0 }
                    )) {
                        ForEach(AppLanguage.allCases) { item in Text(item.name).tag(item.rawValue) }
                    }
                    Picker(language.text("common.fontSize"), selection: $textScale) {
                        ForEach([1.0, 1.2, 1.4], id: \.self) { size in Text(size, format: .percent).tag(size) }
                    }
                    Text(language.text("common.fontSizeHint")).font(.footnote).foregroundStyle(.secondary)
                    Button(saving ? language.text("common.saving") : t("saveChanges")) {
                        let value = (phone ?? profile.phone ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                        saving = true
                        message = nil
                        Task { await savePhone(value) }
                    }
                    .disabled(saving)
                }
            }
            if let message { Text(t(message)).accessibilityAddTraits(.isStaticText) }
        }
        .sheet(isPresented: $changingPassword) {
            KioskPasswordForm(account: account, language: language) { message = "passwordChanged" }
        }
    }

    private func savePhone(_ value: String) async {
        defer { saving = false }
        do {
            let result: Profile = try await account.api.write("auth/me", method: "PUT", language: language, body: ["phone": value])
            phone = result.phone ?? ""
            message = "savedMessage"
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {
            message = "saveFailedMessage"
        }
    }
}

private struct KioskPasswordForm: View {
    let account: Account
    let language: AppLanguage
    let saved: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var current = ""
    @State private var replacement = ""
    @State private var confirmation = ""
    @State private var errorKey: String?
    @State private var saving = false

    private func t(_ key: String) -> String { language.text("common.patient.settings." + key) }

    var body: some View {
        NavigationStack {
            Form {
                SecureField(t("currentPassword"), text: $current).textContentType(.password)
                SecureField(t("newPassword"), text: $replacement).textContentType(.newPassword)
                SecureField(t("confirmPassword"), text: $confirmation).textContentType(.newPassword)
                Text(t("passwordHint")).font(.footnote).foregroundStyle(.secondary)
                if let errorKey { Text(t(errorKey)).foregroundStyle(.red) }
            }
            .navigationTitle(t("changePassword"))
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(language.text("common.cancel")) { dismiss() }.disabled(saving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? language.text("common.saving") : t("changePassword")) { submit() }.disabled(saving)
                }
            }
        }
        .interactiveDismissDisabled(saving)
    }

    private func submit() {
        guard !saving else { return }
        guard !current.isEmpty, !replacement.isEmpty, !confirmation.isEmpty else { errorKey = "passwordRequired"; return }
        guard replacement.count >= 8 else { errorKey = "passwordTooShort"; return }
        guard replacement == confirmation else { errorKey = "passwordMismatch"; return }
        saving = true
        errorKey = nil
        Task {
            defer { saving = false }
            do {
                let payload = ["current_password": current, "new_password": replacement]
                try await account.api.request("auth/change-password", language: language, method: "POST", body: JSONEncoder().encode(payload))
                current = ""
                replacement = ""
                confirmation = ""
                saved()
                dismiss()
            } catch APIError.signedOut {
                dismiss()
                await account.noticeAuthorizationLoss(language)
            } catch {
                errorKey = "passwordChangeFailed"
            }
        }
    }
}
