import SwiftUI

struct HealthScreen: View {
    let account: Account
    let language: AppLanguage

    var body: some View {
        RecordScreen(account: account, language: language, endpoint: "admin/system/health", title: "admin.systemHealth.title") {
            (health: Health, reload) in
            Section(language.text("admin.systemHealth.dependencyTitle")) {
                status("apiStatus", health.status)
                status("database", health.database)
                status("redis", health.redis)
                status("openai", health.openai)
                LabeledContent(language.text("admin.systemHealth.metrics.version"), value: health.version)
                LabeledContent(language.text("admin.systemHealth.lastHealthCheck"),
                               value: health.timestamp.formatted(.dateTime.year().month().day().hour().minute()))
            }
            Button(language.text("admin.systemHealth.refresh")) { Task { await reload() } }
        }
    }

    private struct Health: Decodable, Sendable {
        let status: String
        let database: String
        let redis: String
        let openai: String
        let version: String
        let timestamp: Date
    }

    private func status(_ key: String, _ value: String) -> some View {
        LabeledContent(language.text("admin.systemHealth.metrics.\(key)")) {
            Label(value, systemImage: value == "ok" ? "checkmark.circle" : "exclamationmark.circle")
                .foregroundStyle(value == "ok" ? .green : .orange)
        }
    }
}

private struct AuditEntry: Decodable, Identifiable, Sendable {
    let id: Int
    let userID: UUID?
    let action: String
    let resource: String
    let resourceID: String?
    let details: [String: ClinicalValue]?
    let ip: String?
    let userAgent: String?
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id, action, details
        case userID = "user_id", resource = "resource_type", resourceID = "resource_id", ip = "ip_address"
        case userAgent = "user_agent", createdAt = "created_at"
    }
}

struct AuditScreen: View {
    let account: Account
    let language: AppLanguage
    @State private var action = ""
    @State private var operatorID = ""
    @State private var filterDates = false
    @State private var from = Date()
    @State private var through = Date()
    @State private var refresh = 0

    private var query: [URLQueryItem] {
        var query = [URLQueryItem]()
        let trimmed = action.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { query.append(.init(name: "action", value: trimmed)) }
        if let id = UUID(uuidString: operatorID) { query.append(.init(name: "user_id", value: id.uuidString)) }
        let calendar = Calendar.current
        if filterDates, let end = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: through)) {
            query += LocalDateRange(start: calendar.startOfDay(for: from), end: end, calendar: calendar).query
        }
        return query
    }

    var body: some View {
        List {
            Section(language.text("admin.audit.filter")) {
                TextField(language.text("admin.audit.filterActionPlaceholder"), text: $action)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField(language.text("admin.audit.filterUserPlaceholder"), text: $operatorID)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                Toggle(language.text("admin.audit.filterStartDate"), isOn: $filterDates)
                if filterDates {
                    DatePicker(language.text("admin.audit.filterStartDate"), selection: $from, in: ...through, displayedComponents: .date)
                    DatePicker(language.text("admin.audit.filterEndDate"), selection: $through, in: from..., displayedComponents: .date)
                }
            }
            PagedRows(account: account, language: language, endpoint: "audit-logs", query: query,
                      refreshID: refresh, emptyKey: "admin.audit.emptyTitle") { (entry: AuditEntry) in
                NavigationLink {
                    RecordScreen(account: account, language: language, endpoint: "audit-logs/\(entry.id)",
                                 title: "admin.audit.title") { (value: AuditEntry, _) in
                        metadata(value)
                        if let details = value.details {
                            ForEach(ClinicalRows(language: language, section: "audit").fields(details)) { field in
                                LabeledContent(field.label, value: field.content)
                            }
                        }
                    }
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(entry.action).font(.headline)
                        Text(entry.resource)
                        Text(entry.createdAt.formatted(.dateTime.year().month().day().hour().minute()))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .navigationTitle(language.text("admin.audit.title"))
        .refreshable { refresh += 1 }
        .toolbar { Button(language.text("admin.audit.refresh")) { refresh += 1 } }
    }

    @ViewBuilder private func metadata(_ entry: AuditEntry) -> some View {
        LabeledContent(language.text("admin.audit.colAction"), value: entry.action)
        LabeledContent(language.text("admin.audit.colTime"), value: entry.createdAt.formatted())
        LabeledContent(language.text("admin.audit.colResourceType"), value: entry.resource)
        if let id = entry.userID { LabeledContent(language.text("admin.audit.colUser"), value: id.uuidString) }
        if let id = entry.resourceID { LabeledContent(language.text("admin.audit.colResourceId"), value: id) }
        if let ip = entry.ip { LabeledContent(language.text("admin.audit.colIp"), value: ip) }
    }
}

private struct ComplaintTemplate: Decodable, Identifiable, Sendable {
    let id: UUID
    let name: String
    let category: String
    let description: String?
    let nameEn: String?
    let nameByLanguage: [String: String]?
    let categoryByLanguage: [String: String]?
    let descriptionByLanguage: [String: String]?
    let active: Bool
    let isDefault: Bool
    let order: Int

    enum CodingKeys: String, CodingKey {
        case id, name, description, category
        case nameEn = "name_en", nameByLanguage = "name_by_lang", categoryByLanguage = "category_by_lang"
        case descriptionByLanguage = "description_by_lang", active = "is_active", isDefault = "is_default"
        case order = "display_order"
    }
}

struct ComplaintTemplatesScreen: View {
    let account: Account
    let language: AppLanguage

    @State private var search = ""
    @State private var update = 0
    @State private var create = false
    @State private var edit: ComplaintTemplate?
    @State private var delete: ComplaintTemplate?
    @State private var activeOnly = true
    @State private var busy = false
    @State private var failed = false

    var body: some View {
        List {
            if failed { Text(language.text("admin.complaints.deleteFailed")).foregroundStyle(.red) }
            Picker(language.text("admin.complaints.colStatus"), selection: $activeOnly) {
                Text(language.text("admin.complaints.statusActive")).tag(true)
                Text(language.text("admin.complaints.statusInactive")).tag(false)
            }
            let query = [.init(name: "is_active", value: String(activeOnly))] as [URLQueryItem]
            PagedRows(account: account, language: language, endpoint: "complaints",
                      query: search.isEmpty ? query : query + [.init(name: "search", value: search)],
                      refreshID: update, emptyKey: "admin.complaints.emptyTitle") { (template: ComplaintTemplate) in
                Button { edit = template } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(template.name).font(.headline)
                        Text(template.category)
                        Text(language.text(template.active ? "admin.complaints.statusActive" : "admin.complaints.statusInactive"))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .foregroundStyle(.primary)
                }
                .swipeActions {
                    Button(role: .destructive) { if !busy { delete = template } } label: {
                        Label(language.text("admin.complaints.delete"), systemImage: "trash")
                    }
                }
            }
        }
        .navigationTitle(language.text("admin.complaints.title"))
        .refreshable { update += 1 }
        .searchable(text: $search, prompt: language.text("admin.complaints.searchPlaceholder"))
        .toolbar { Button(language.text("admin.complaints.create")) { create = true }.disabled(busy) }
        .sheet(isPresented: $create) { editor(nil) }
        .sheet(item: $edit) { editor($0) }
        .confirmationDialog(language.text("admin.complaints.deleteTitle"), isPresented: Binding(
            get: { delete != nil }, set: { if !$0 { delete = nil } }
        ), presenting: delete) { template in
            Button(language.text("admin.complaints.confirmDelete"), role: .destructive) {
                Task { await remove(template) }
            }
        } message: { template in
            Text(language.text("admin.complaints.deleteConfirm", args: ["name": template.name]))
        }
    }

    private func editor(_ template: ComplaintTemplate?) -> some View {
        ComplaintEditor(account: account, language: language, template: template) { update += 1 }
    }

    private func remove(_ template: ComplaintTemplate) async {
        guard !busy else { return }
        busy = true
        failed = false
        defer { busy = false; update += 1 }
        do {
            try await account.api.request("complaints/\(template.id)", language: language, method: "DELETE")
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch { failed = true }
    }
}

private struct ComplaintEditor: View {
    let account: Account
    let language: AppLanguage
    let template: ComplaintTemplate?
    let onSave: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var names: [String: String] = [:]
    @State private var categories: [String: String] = [:]
    @State private var descriptions: [String: String] = [:]
    @State private var position = 0
    @State private var active = true
    @State private var isDefault = false
    @State private var saving = false
    @State private var errorKey: String?

    var body: some View {
        NavigationStack {
            Form {
                ForEach(AppLanguage.allCases) { locale in
                    Section(locale.name) {
                        TextField(language.text("admin.complaints.fieldName"), text: binding($names, locale))
                        TextField(language.text("admin.complaints.fieldCategory"), text: binding($categories, locale))
                        TextField(language.text("admin.complaints.fieldDescription"), text: binding($descriptions, locale), axis: .vertical)
                    }
                }
                Section {
                    TextField(language.text("admin.complaints.fieldDisplayOrder"), value: $position, format: .number)
                        .keyboardType(.numbersAndPunctuation)
                    Toggle(language.text("admin.complaints.fieldIsActive"), isOn: $active)
                    Toggle(language.text("admin.complaints.colDefault"), isOn: $isDefault)
                    if let errorKey { Text(language.text(errorKey)).foregroundStyle(.red) }
                }
            }
            .disabled(saving)
            .navigationTitle(language.text(template == nil ? "admin.complaints.createTitle" : "admin.complaints.editTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(language.text("admin.complaints.cancel")) { dismiss() }.disabled(saving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(language.text("admin.complaints.save")) { Task { await save() } }.disabled(saving)
                }
            }
        }
        .interactiveDismissDisabled(saving)
        .onAppear {
            guard let template else { return }
            names = template.nameByLanguage ?? [language.rawValue: template.name]
            if let english = template.nameEn, names["en-US"] == nil { names["en-US"] = english }
            categories = template.categoryByLanguage ?? [language.rawValue: template.category]
            descriptions = template.descriptionByLanguage ?? [language.rawValue: template.description ?? ""]
            position = template.order
            active = template.active
            isDefault = template.isDefault
        }
    }

    private func binding(_ values: Binding<[String: String]>, _ locale: AppLanguage) -> Binding<String> {
        Binding(get: { values.wrappedValue[locale.rawValue] ?? "" }, set: { values.wrappedValue[locale.rawValue] = $0 })
    }

    private struct Payload: Encodable, Sendable {
        let name: String
        let name_en: String?
        let category: String
        let description: String?
        let name_by_lang: [String: String]
        let category_by_lang: [String: String]
        let description_by_lang: [String: String]
        let display_order: Int
        let is_active: Bool
        let is_default: Bool
    }

    private func save() async {
        guard !saving else { return }
        let names = clean(names)
        let categories = clean(categories)
        let descriptions = clean(descriptions)
        guard let name = names["zh-TW"] ?? names[language.rawValue] ?? names["en-US"],
              let category = categories["zh-TW"] ?? categories[language.rawValue] ?? categories["en-US"] else {
            errorKey = "admin.complaints.validationRequired"
            return
        }
        saving = true
        errorKey = nil
        defer { saving = false }
        let body = Payload(name: name, name_en: names["en-US"], category: category,
                        description: descriptions["zh-TW"] ?? descriptions[language.rawValue],
                        name_by_lang: names, category_by_lang: categories, description_by_lang: descriptions,
                        display_order: position, is_active: active, is_default: isDefault)
        let endpoint = template.map { "complaints/\($0.id)" } ?? "complaints"
        do {
            _ = try await account.api.write(endpoint, method: template == nil ? "POST" : "PUT",
                                            language: language, body: body) as ComplaintTemplate
            onSave()
            dismiss()
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch { errorKey = "admin.complaints.saveFailed" }
    }

    private func clean(_ values: [String: String]) -> [String: String] {
        values.mapValues { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.value.isEmpty }
    }
}
