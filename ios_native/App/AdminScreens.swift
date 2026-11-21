import SwiftUI
import UniformTypeIdentifiers

private struct AdminUserRecord: Decodable, Identifiable, Sendable {
    let id: UUID
    let email: String
    let name: String
    let role: User.Role
    let phone: String?
    let department: String?
    let license: String?
    let active: Bool
    let lastLogin: Date?

    enum CodingKeys: String, CodingKey {
        case id, email, name, role, phone, department
        case license = "license_number", active = "is_active", lastLogin = "last_login_at"
    }
}

struct AdminUsersScreen: View {
    let account: Account
    let language: AppLanguage

    @State private var search = ""
    @State private var role = ""
    @State private var status = ""
    @State private var refresh = 0
    @State private var create = false
    @State private var edit: AdminUserRecord?
    @State private var target: UserAction?
    @State private var temporaryPassword: TemporaryPassword?
    @State private var busy = false
    @State private var errorKey: String?

    private struct UserAction {
        let user: AdminUserRecord
        let reset: Bool
    }

    private struct TemporaryPassword: Decodable, Identifiable, Sendable {
        let id: UUID
        let email: String
        let password: String
        enum CodingKeys: String, CodingKey { case id, email, password = "temp_password" }
    }

    private var query: [URLQueryItem] {
        [("role", role), ("is_active", status), ("search", search.trimmingCharacters(in: .whitespacesAndNewlines))]
            .compactMap { $0.1.isEmpty ? nil : URLQueryItem(name: $0.0, value: $0.1) }
    }

    var body: some View {
        List {
            Section {
                Picker(language.text("admin.users.fieldRole"), selection: $role) {
                    Text(language.text("admin.users.roleTab.all")).tag("")
                    ForEach(User.Role.allCases, id: \.rawValue) { role in
                        Text(language.text("admin.users.role.\(role.rawValue)")).tag(role.rawValue)
                    }
                }
                Picker(language.text("admin.users.colStatus"), selection: $status) {
                    Text(language.text("admin.users.roleTab.all")).tag("")
                    Text(language.text("admin.users.statusActive")).tag("true")
                    Text(language.text("admin.users.statusInactive")).tag("false")
                }
            }
            if let errorKey { Text(language.text(errorKey)).foregroundStyle(.red) }
            PagedRows(account: account, language: language, endpoint: "admin/users",
                      query: query, refreshID: refresh, emptyKey: "admin.users.emptyTitle") { (record: AdminUserRecord) in
                row(record)
            }
        }
        .navigationTitle(language.text("admin.users.title"))
        .refreshable { refresh += 1 }
        .searchable(text: $search, prompt: language.text("admin.users.searchPlaceholder"))
        .toolbar {
            Button(language.text("admin.users.create")) { create = true }.disabled(busy)
        }
        .sheet(isPresented: $create) { editor(nil) }
        .sheet(item: $edit) { editor($0) }
        .sheet(item: $temporaryPassword) { password in
            NavigationStack {
                Form {
                    Section(language.text("admin.users.tempPasswordTitle")) {
                        Text(password.email)
                        Text(password.password).font(.body.monospaced()).privacySensitive()
                        Text(language.text("admin.users.tempPasswordWarning"))
                        Button(language.text("admin.users.tempPasswordCopy")) {
                            UIPasteboard.general.setItems(
                                [[UTType.plainText.identifier: password.password]],
                                options: [.localOnly: true, .expirationDate: Date().addingTimeInterval(60)]
                            )
                        }
                    }
                }
                .toolbar {
                    Button(language.text("admin.users.tempPasswordDone")) { temporaryPassword = nil }
                }
            }
        }
        .confirmationDialog(language.text("session.doctor.detail.confirm"), isPresented: Binding(
            get: { target != nil }, set: { if !$0 { target = nil } }
        ), presenting: target) { action in
            Button(language.text(action.reset ? "admin.users.resetPassword" : activeKey(action.user)), role: .destructive) {
                Task { await perform(action) }
            }
        } message: { action in
            if action.reset {
                Text(language.text("admin.users.resetPasswordConfirm", args: ["name": action.user.name, "email": action.user.email]))
            } else {
                Text(action.user.email)
            }
        }
    }

    private func row(_ record: AdminUserRecord) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(record.name).font(.headline)
                Text(record.email).font(.subheadline)
                Text(language.text("admin.users.role.\(record.role.rawValue)"))
                Text(language.text(record.active ? "admin.users.statusActive" : "admin.users.statusInactive"))
                    .font(.caption).foregroundStyle(.secondary)
                if let date = record.lastLogin {
                    LabeledContent(language.text("admin.users.colLastLogin"),
                                   value: date.formatted(.dateTime.year().month().day().hour().minute()))
                        .font(.caption)
                }
            }
            Spacer()
            Menu(language.text("admin.users.colActions")) {
                Button(language.text("admin.users.edit")) { edit = record }
                if account.currentUser?.id != record.id {
                    Button(language.text(activeKey(record)), role: .destructive) {
                        target = UserAction(user: record, reset: false)
                    }
                    Button(language.text("admin.users.resetPassword"), role: .destructive) {
                        target = UserAction(user: record, reset: true)
                    }
                }
            }
            .disabled(busy)
        }
    }

    private func editor(_ user: AdminUserRecord?) -> some View {
        AdminUserEditor(account: account, language: language, user: user) { refresh += 1 }
    }

    private func activeKey(_ user: AdminUserRecord) -> String {
        user.active ? "admin.users.deactivate" : "admin.users.activate"
    }

    private func perform(_ action: UserAction) async {
        guard !busy, account.currentUser?.isSystemAdmin == true else { return }
        busy = true
        errorKey = nil
        defer { busy = false }
        do {
            let base = "admin/users/\(action.user.id)"
            if action.reset {
                temporaryPassword = try await account.api.write(
                    "\(base)/reset-password", method: "POST", language: language, body: [String: String]()
                )
            } else {
                try await account.api.request("\(base)/toggle-active", language: language, method: "PUT")
                refresh += 1
            }
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {
            if !action.reset { refresh += 1 }
            errorKey = action.reset ? "admin.users.resetPasswordFailed" : "admin.users.toggleFailed"
        }
    }
}

private struct AdminUserEditor: View {
    let account: Account
    let language: AppLanguage
    let user: AdminUserRecord?
    let onSave: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var email = ""
    @State private var password = ""
    @State private var phone = ""
    @State private var department = ""
    @State private var license = ""
    @State private var role: User.Role = .patient
    @State private var active = true
    @State private var saving = false
    @State private var errorKey: String?

    var body: some View {
        NavigationStack {
            Form {
                TextField(language.text("admin.users.fieldName"), text: $name)
                TextField(language.text("admin.users.fieldEmail"), text: $email)
                    .keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                if user == nil {
                    SecureField(language.text("admin.users.fieldPassword"), text: $password)
                        .textContentType(.newPassword)
                }
                Picker(language.text("admin.users.fieldRole"), selection: $role) {
                    ForEach(User.Role.allCases, id: \.rawValue) { role in
                        Text(language.text("admin.users.role.\(role.rawValue)")).tag(role)
                    }
                }
                TextField(language.text("admin.users.fieldPhone"), text: $phone).keyboardType(.phonePad)
                TextField(language.text("common.doctor.settings.department"), text: $department)
                TextField(language.text("native.licenseNumber"), text: $license)
                Toggle(language.text("admin.users.fieldIsActive"), isOn: $active)
                if let errorKey { Text(language.text(errorKey)).foregroundStyle(.red) }
            }
            .disabled(saving)
            .navigationTitle(language.text(user == nil ? "admin.users.createTitle" : "admin.users.editTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(language.text("admin.users.cancel")) { dismiss() }.disabled(saving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(language.text(user == nil ? "admin.users.createConfirm" : "admin.users.update")) {
                        Task { await submit() }
                    }
                    .disabled(saving)
                }
            }
        }
        .interactiveDismissDisabled(saving)
        .onAppear {
            guard let user else { return }
            name = user.name
            email = user.email
            phone = user.phone ?? ""
            department = user.department ?? ""
            license = user.license ?? ""
            role = user.role
            active = user.active
        }
    }

    private struct Payload: Encodable, Sendable {
        let name: String
        let email: String
        let role: User.Role
        let phone: String?
        let department: String?
        let license: String?
        let active: Bool
        let password: String?

        enum CodingKeys: String, CodingKey {
            case name, email, role, phone, department, password
            case license = "license_number", active = "is_active"
        }
    }

    private func submit() async {
        guard !saving, account.currentUser?.isSystemAdmin == true else { return }
        let cleanName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanName.isEmpty, cleanEmail.contains("@") else {
            errorKey = "admin.users.validationNameEmail"
            return
        }
        guard user != nil || password.count >= 8 else {
            errorKey = "admin.users.validationPassword"
            return
        }
        saving = true
        errorKey = nil
        defer { saving = false }
        let body = Payload(
            name: cleanName, email: cleanEmail, role: role,
            phone: changedField(phone, previous: user?.phone),
            department: changedField(department, previous: user?.department),
            license: changedField(license, previous: user?.license),
            active: active, password: user == nil ? password : nil
        )
        let endpoint = user.map { "admin/users/\($0.id)" } ?? "admin/users"
        do {
            _ = try await account.api.write(endpoint, method: user == nil ? "POST" : "PUT", language: language, body: body)
                as AdminUserRecord
            password = ""
            onSave()
            dismiss()
            if user?.id == account.currentUser?.id, user != nil { await account.signOut(language) }
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {
            errorKey = "admin.users.operationFailed"
        }
    }

    private func changedField(_ value: String, previous: String?) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed == (previous ?? "") ? nil : trimmed
    }

}
