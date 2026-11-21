import SwiftUI

struct KioskIntakeScreen: View {
    let account: Account
    let language: AppLanguage
    var patientID: UUID? = nil
    @Binding var submitting: Bool
    let onCancel: () -> Void
    let onCreated: (UUID) -> Void

    @State private var complaints: Load<[KioskComplaint]> = .loading
    @State private var selection = KioskComplaintSelection()
    @State private var selectionError: String?
    @State private var loadedLanguage: AppLanguage?
    @State private var medical = false
    @State private var patient = KioskPatientDraft()
    @State private var reload = 0

    var body: some View {
        Group {
            if medical {
                KioskIntakeForm(account: account, language: language, patientID: patientID, selection: selection,
                                ready: loadedLanguage == language && selection.ready, patient: $patient,
                                submitting: $submitting, onCreated: onCreated)
                    .safeAreaInset(edge: .top) {
                        if loadedLanguage != language { loadStatus }
                    }
            } else {
                Form {
                    Section {
                        if case let .loaded(rows) = complaints, loadedLanguage == language {
                            ForEach(rows) { item in complaintRow(item) }
                        } else {
                            loadStatus
                        }
                    } header: {
                        Text(language.text("intake.selectComplaint.multiHint"))
                    }
                    if !selection.items.isEmpty {
                        let hasOther = selection.items.contains { $0.id == KioskComplaint.otherID }
                        Section(language.text(hasOther ? "intake.selectComplaint.customLabelRequired" : "intake.selectComplaint.customLabel")) {
                            let placeholder = hasOther ? language.text("intake.selectComplaint.otherPlaceholder")
                                : language.text("intake.selectComplaint.customPlaceholder", args: ["name": selection.items.first?.name ?? ""])
                            TextField(placeholder,
                                      text: $selection.note.limited(to: 200), axis: .vertical)
                                .accessibilityIdentifier("kiosk.complaint.note")
                            if selection.needsNote {
                                Text(language.text("intake.selectComplaint.otherRequired")).foregroundStyle(.red)
                            }
                        }
                    }
                }
                .safeAreaInset(edge: .bottom) {
                    Button(selection.items.isEmpty ? language.text("intake.selectComplaint.cta")
                           : language.text("intake.selectComplaint.ctaCount", args: ["count": String(selection.items.count)])) {
                        medical = true
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .padding()
                    .disabled(!selection.ready || loadedLanguage != language)
                    .accessibilityIdentifier("kiosk.complaints.next")
                }
            }
        }
        .navigationTitle(language.text(medical ? "intake.medicalInfo.title" : "intake.selectComplaint.title"))
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button(language.text(medical ? "intake.medicalInfo.nav.back" : "common.cancel")) {
                    if medical { medical = false } else { onCancel() }
                }
                .disabled(submitting)
                .accessibilityIdentifier("kiosk.intake.back")
            }
        }
        .alert(selectionError ?? "", isPresented: Binding(get: { selectionError != nil }, set: { if !$0 { selectionError = nil } })) {
            Button(language.text("session.doctor.detail.confirm")) { selectionError = nil }
        }
        .task(id: "\(language.rawValue)-\(reload)") {
            let api = account.api, language = self.language
            loadedLanguage = nil
            complaints = .loading
            let result = await Load<[KioskComplaint]>.fetch {
                let page: Page<KioskComplaint> = try await api.get("complaints", language: language, query: [
                    .init(name: "limit", value: "100"), .init(name: "is_active", value: "true")
                ])
                return page.data.sorted { $0.displayOrder < $1.displayOrder }
            }
            guard !Task.isCancelled else { return }
            complaints = result
            if let fresh = result.value {
                selection.relocalize(from: fresh)
                if !selection.ready { medical = false }
                loadedLanguage = language
            }
            if result.isSignedOut { await account.noticeAuthorizationLoss(language) }
        }
    }

    @ViewBuilder private var loadStatus: some View {
        if case .failed = complaints {
            Button(language.text("common.retry")) { reload += 1 }
        } else {
            ProgressView(language.text("intake.selectComplaint.loading"))
        }
    }

    private func complaintRow(_ item: KioskComplaint) -> some View {
        let index = selection.items.firstIndex { $0.id == item.id }
        return Button {
            selectionError = selection.toggle(item, language: language)
        } label: {
            HStack {
                Image(systemName: index.map { "\($0 + 1).circle.fill" } ?? "circle")
                VStack(alignment: .leading) {
                    Text(item.name)
                    if let description = item.description, !description.isEmpty {
                        Text(description).font(.subheadline).foregroundStyle(.secondary)
                    }
                }
                if index == 0 {
                    Spacer()
                    Text(language.text("intake.selectComplaint.primaryBadge")).font(.caption.bold())
                }
            }
        }
        .accessibilityAddTraits(index == nil ? [] : .isSelected)
        .accessibilityIdentifier("kiosk.complaint.\(item.id.uuidString.lowercased())")
    }
}

private struct KioskDoctor: Decodable, Identifiable, Sendable {
    let id: UUID
    let name: String
    let department: String?
}

extension Binding where Value == String {
    fileprivate func limited(to max: Int) -> Self {
        Self(get: { wrappedValue }, set: { wrappedValue = String($0.unicodeScalars.prefix(max)) })
    }
}

private struct KioskPatientDraft {
    var doctorID: UUID?
    var name = ""
    var gender: String?
    var dob: Date?
    var phone = ""
    var intake = KioskIntake()
}

private struct KioskIntakeForm: View {
    let account: Account
    let language: AppLanguage
    let patientID: UUID?
    let selection: KioskComplaintSelection
    let ready: Bool
    @Binding var patient: KioskPatientDraft
    @Binding var submitting: Bool
    let onCreated: (UUID) -> Void

    @State private var doctors: Load<[KioskDoctor]> = .loading
    @State private var doctorReload = 0
    @State private var choosingBirthDate = false
    @State private var pickedDate = Calendar(identifier: .gregorian).date(from: .init(year: 1980, month: 1, day: 1))!
    @State private var showErrors = false
    @State private var submitFailed = false

    var body: some View {
        Form {
            Section(language.text("intake.medicalInfo.patient.title")) {
                Text(language.text("intake.medicalInfo.complaintLabel", args: [
                    "name": selection.items.map(\.name).joined(separator: language.text("intake.selectComplaint.nameSeparator"))
                ]))
                doctorField
                TextField(t("patient.nameLabel"), text: $patient.name.limited(to: 100))
                    .accessibilityIdentifier("kiosk.intake.name")
                validation("patient.nameError", when: patient.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Text(t("patient.genderLabel"))
                HStack {
                    ForEach(["male", "female", "other"], id: \.self) { option in
                        Button(t("patient.gender\(option.capitalized)")) { patient.gender = option }
                            .buttonStyle(.bordered)
                            .tint(patient.gender == option ? .accentColor : .secondary)
                            .accessibilityAddTraits(patient.gender == option ? .isSelected : [])
                            .accessibilityIdentifier("kiosk.intake.gender.\(option)")
                    }
                }
                validation("patient.genderError", when: patient.gender == nil)
                Button {
                    if let dob = patient.dob { pickedDate = dob }
                    choosingBirthDate = true
                } label: {
                    LabeledContent(t("patient.dobLabel"), value: patient.dob?.formatted(date: .abbreviated, time: .omitted) ?? "")
                }
                .accessibilityIdentifier("kiosk.intake.dob")
                validation("patient.dobError", when: patient.dob == nil)
                TextField(t("patient.phoneLabel"), text: $patient.phone.limited(to: 20)).keyboardType(.phonePad)
            }
            historySections
        }
        .scrollDismissesKeyboard(.interactively)
        .disabled(submitting)
        .sheet(isPresented: $choosingBirthDate) {
            NavigationStack {
                DatePicker(t("patient.dobLabel"), selection: $pickedDate,
                           in: Calendar(identifier: .gregorian).date(from: .init(year: 1900))!...Date(),
                           displayedComponents: .date)
                    .datePickerStyle(.wheel)
                    .labelsHidden()
                    .navigationTitle(t("patient.dobLabel"))
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button(language.text("common.cancel")) { choosingBirthDate = false }
                        }
                        ToolbarItem(placement: .confirmationAction) {
                            Button(language.text("session.doctor.detail.confirm")) {
                                patient.dob = pickedDate
                                choosingBirthDate = false
                            }
                            .accessibilityIdentifier("kiosk.intake.dob.confirm")
                        }
                    }
            }
            .presentationDetents([.medium])
        }
        .safeAreaInset(edge: .bottom) {
            VStack {
                if submitFailed { Text(t("errors.createSession")).foregroundStyle(.red) }
                Button(t(submitting ? "nav.submitting" : "nav.submit")) {
                    showErrors = true
                    submitFailed = false
                    if !patient.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                       patient.gender != nil, patient.dob != nil, patient.doctorID != nil { submitting = true }
                }
                .disabled(submitting || !ready || doctors.value?.isEmpty != false)
                .accessibilityIdentifier("kiosk.intake.submit")
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            .padding()
            .frame(maxWidth: .infinity)
            .background(.bar)
        }
        .task(id: doctorReload) {
            let api = account.api, language = self.language
            doctors = .loading
            let result = await Load<[KioskDoctor]>.fetch { try await api.get("sessions/doctors", language: language) }
            guard !Task.isCancelled else { return }
            doctors = result
            if let list = result.value, !list.contains(where: { $0.id == patient.doctorID }) {
                patient.doctorID = list.first { $0.id == account.currentUser?.id }?.id ?? (list.count == 1 ? list.first?.id : nil)
            }
            if result.isSignedOut { await account.noticeAuthorizationLoss(language) }
        }
        .task(id: submitting) { if submitting { await submit() } }
    }

    @ViewBuilder private var doctorField: some View {
        switch doctors {
        case .failed: doctorRetry
        case .loading, .signedOut: ProgressView(t("patient.doctorLabel"))
        case let .loaded(list):
            if list.isEmpty { doctorRetry }
            else {
                Picker(t("patient.doctorLabel"), selection: $patient.doctorID) {
                    Text(t("patient.doctorPlaceholder")).tag(nil as UUID?)
                    ForEach(list) { doctor in
                        Text([doctor.name, doctor.department].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                            .tag(Optional(doctor.id))
                    }
                }
                .accessibilityIdentifier("kiosk.intake.doctor")
                Text(t("patient.doctorHint")).font(.footnote).foregroundStyle(.secondary)
                validation("patient.doctorError", when: patient.doctorID == nil)
            }
        }
    }

    private var doctorRetry: some View {
        VStack(alignment: .leading) {
            Text(t("patient.doctorLoadFailed"))
            Button(language.text("common.retry")) { doctorReload += 1 }
        }
    }

    @ViewBuilder private func validation(_ key: String, when invalid: Bool) -> some View {
        if showErrors && invalid { Text(t(key)).font(.footnote).foregroundStyle(.red) }
    }

    private func t(_ key: String) -> String { language.text("intake.medicalInfo." + key) }

    private func submit() async {
        defer { submitting = false }
        guard let complaint = selection.items.first, let doctorID = patient.doctorID,
              let gender = patient.gender, let dob = patient.dob else { return }
        let dateFormat = Date.ISO8601FormatStyle(timeZone: .current).year().month().day().dateSeparator(.dash)
        var info: [String: String] = [
            "name": patient.name.trimmingCharacters(in: .whitespacesAndNewlines), "gender": gender,
            "date_of_birth": dob.formatted(dateFormat)
        ]
        let number = patient.phone.trimmingCharacters(in: .whitespacesAndNewlines)
        if !number.isEmpty { info["phone"] = number }
        var body: [String: Any] = [
            "chief_complaint_id": complaint.id.uuidString,
            "chief_complaint_text": selection.complaintText(language: language),
            "doctor_id": doctorID.uuidString, "language": language.rawValue,
            "patient_info": info, "intake": patient.intake.payload(language: language)
        ]
        if let patientID { body["patient_id"] = patientID.uuidString }
        struct Created: Decodable { let id: UUID }
        do {
            let data = try JSONSerialization.data(withJSONObject: body)
            let response = try await account.api.request("sessions", language: language, method: "POST", body: data)
            let id = try JSONDecoder().decode(Created.self, from: response).id
            if !Task.isCancelled { onCreated(id) }
        } catch APIError.signedOut {
            await account.noticeAuthorizationLoss(language)
        } catch {
            if !Task.isCancelled { submitFailed = true }
        }
    }

    @ViewBuilder private var historySections: some View {
        Section(t("allergy.title")) {
            Toggle(t("allergy.noneLabel"), isOn: $patient.intake.allergies.denied)
            if !patient.intake.allergies.denied {
                quickAdd(label: "allergy.quickAddLabel", group: "commonAllergies",
                         keys: ["penicillin", "aspirin", "nsaid", "sulfa", "seafood", "peanut", "milk", "dust", "pollen"],
                         existing: patient.intake.allergies.rows.map(\.name)) { patient.intake.allergies.rows.append(.init(name: $0)) }
                ForEach($patient.intake.allergies.rows) { $row in
                    VStack(alignment: .leading) {
                        TextField(t("allergy.placeholder"), text: $row.name.limited(to: 100))
                        Toggle(t("allergy.hospitalized"), isOn: $row.hospitalized)
                        remove { [id = row.id] in patient.intake.allergies.rows.removeAll { $0.id == id } }
                    }
                }
                Button(t("allergy.add"), systemImage: "plus") { patient.intake.allergies.rows.append(.init()) }
            }
        }
        Section(t("medication.title")) {
            Toggle(t("medication.noneLabel"), isOn: $patient.intake.medications.denied)
            if !patient.intake.medications.denied {
                ForEach($patient.intake.medications.rows) { $row in
                    VStack(alignment: .leading) {
                        TextField(t("medication.placeholder"), text: $row.name.limited(to: 100))
                        choices("medication.title", group: "frequency", value: $row.frequency,
                                options: ["onceDaily", "twiceDaily", "thriceDaily", "asNeeded", "weekly", "other"])
                        remove { [id = row.id] in patient.intake.medications.rows.removeAll { $0.id == id } }
                    }
                }
                Button(t("medication.add"), systemImage: "plus") { patient.intake.medications.rows.append(.init()) }
            }
        }
        Section(t("history.title")) {
            Toggle(t("history.noneLabel"), isOn: $patient.intake.history.denied)
            if !patient.intake.history.denied {
                quickAdd(label: "history.quickAddLabel", group: "commonConditions",
                         keys: ["hypertension", "diabetes", "heartDisease", "stroke", "kidneyDisease", "gout", "bph", "urinaryStones", "cancer"],
                         existing: patient.intake.history.rows.map(\.condition)) { patient.intake.history.rows.append(.init(condition: $0)) }
                ForEach($patient.intake.history.rows) { $row in
                    VStack(alignment: .leading) {
                        TextField(t("history.placeholder"), text: $row.condition.limited(to: 100))
                        choices("history.yearsAgoLabel", group: "yearsAgo", value: $row.yearsAgo,
                                options: ["within1", "oneToFive", "overFive", "unsure"])
                        Toggle(t("history.stillHas"), isOn: $row.stillHas)
                        remove { [id = row.id] in patient.intake.history.rows.removeAll { $0.id == id } }
                    }
                }
                Button(t("history.add"), systemImage: "plus") { patient.intake.history.rows.append(.init()) }
            }
        }
        Section {
            Toggle(t("family.noneLabel"), isOn: $patient.intake.family.denied)
            if !patient.intake.family.denied {
                ForEach($patient.intake.family.rows) { $row in
                    VStack(alignment: .leading) {
                        choices("family.title", group: "relations", value: $row.relation,
                                options: ["father", "mother", "brother", "sister", "paternalGrandfather", "paternalGrandmother", "maternalGrandfather", "maternalGrandmother"])
                        TextField(t("family.conditionPlaceholder"), text: $row.condition.limited(to: 100))
                        remove { [id = row.id] in patient.intake.family.rows.removeAll { $0.id == id } }
                    }
                }
                Button(t("family.add"), systemImage: "plus") { patient.intake.family.rows.append(.init()) }
            }
        } header: { Text("\(t("family.title")) · \(t("family.optional"))") }
          footer: { Text(t("family.hint")) }
    }

    private func choices(_ label: String, group: String, value: Binding<String>, options: [String]) -> some View {
        Picker(t(label), selection: value) {
            ForEach(options, id: \.self) { key in Text(t("\(group).\(key)")).tag(key) }
        }
    }

    @ViewBuilder private func quickAdd(label: String, group: String, keys: [String], existing: [String],
                                        add: @escaping (String) -> Void) -> some View {
        let values = Set(existing.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) })
        let options = keys.map { t("\(group).\($0)") }.filter { !values.contains($0) }
        if !options.isEmpty {
            Menu(t(label)) {
                ForEach(options, id: \.self) { name in Button(name) { add(name) } }
            }
        }
    }

    private func remove(_ action: @escaping () -> Void) -> some View {
        Button(language.text("admin.complaints.delete"), systemImage: "minus.circle", role: .destructive, action: action)
            .buttonStyle(.borderless)
    }
}
