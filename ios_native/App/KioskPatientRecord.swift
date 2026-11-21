import SwiftUI

struct KioskReportExcerpt: Decodable, Sendable {
    struct Texts: Decodable, Equatable, Sendable {
        let language: String?
        let summary: String?
        let education: [String]

        enum CodingKeys: String, CodingKey {
            case language, summary, patientEducation, patient_education
        }

        init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            language = try? values.decode(String.self, forKey: .language)
            summary = Self.clean(try? values.decode(String.self, forKey: .summary))
            let key: CodingKeys = values.contains(.patient_education) ? .patient_education : .patientEducation
            if let item = Self.clean(try? values.decode(String.self, forKey: key)) {
                education = [item]
            } else if let items = try? values.decode([ClinicalValue].self, forKey: key) {
                education = items.compactMap {
                    guard case let .text(value) = $0 else { return nil }
                    return Self.clean(value)
                }
            } else {
                education = []
            }
        }

        fileprivate static func clean(_ raw: String?) -> String? {
            guard let value = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty else { return nil }
            return value
        }
    }

    enum PatientText: Equatable {
        case content(String?, [String])
        case notice
    }

    let status: Report.Status
    let review: Report.Review
    private let summary: String?
    private let education: [String]
    private let localized: Texts?

    enum CodingKeys: String, CodingKey {
        case status, summary, plan
        case review = "review_status"
        case localized = "patient_facing_localized"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        status = try values.decodeIfPresent(Report.Status.self, forKey: .status) ?? .generating
        review = try values.decodeIfPresent(Report.Review.self, forKey: .review) ?? .pending
        summary = Texts.clean(try? values.decode(String.self, forKey: .summary))
        education = (try? values.decode(Texts.self, forKey: .plan))?.education ?? []
        localized = try? values.decode(Texts.self, forKey: .localized)
    }

    static func patientText(_ report: Self?, sessionLanguage: String?) -> PatientText {
        func code(_ language: String) -> String? {
            Locale(identifier: language).language.languageCode?.identifier
        }
        guard let sessionCode = sessionLanguage.flatMap(code),
              AppLanguage.allCases.contains(where: { code($0.rawValue) == sessionCode }) else { return .notice }
        if let localized = report?.localized, let language = localized.language, code(language) == sessionCode,
           localized.summary != nil || !localized.education.isEmpty {
            return .content(localized.summary, localized.education)
        }
        return sessionCode == "zh" ? .content(report?.summary, report?.education ?? []) : .notice
    }
}

struct KioskPatientRecord: View {
    let id: UUID
    let account: Account
    let language: AppLanguage
    let onHome: () -> Void
    let onHistory: () -> Void

    @State private var session: ClinicalSession?
    @State private var report: KioskReportExcerpt?
    @State private var fetching = true

    private func t(_ key: String) -> String { language.text(key) }

    private var patientText: KioskReportExcerpt.PatientText {
        KioskReportExcerpt.patientText(report, sessionLanguage: session?.language)
    }

    var body: some View {
        List {
            Label(t("session.complete.subtitle"), systemImage: "checkmark.circle")
            if let session {
                Section(t("session.complete.summaryTitle")) {
                    LabeledContent(t("session.complete.summaryChiefComplaint"), value: session.complaint ?? "—")
                    LabeledContent(t("session.complete.summaryStartedAt")) { Text(date(session.startedAt ?? session.createdAt)) }
                    LabeledContent(t("session.complete.summaryDuration"), value: duration(session, fallback: "session.complete.durationEmpty"))
                    if session.flagged {
                        Label(t("session.complete.redFlagTitle"), systemImage: "exclamationmark.triangle").foregroundStyle(.red)
                        if let reason = session.reason { Text(reason) }
                    }
                }
            }
            Section(t("session.complete.reportTitle")) {
                if let report, report.status == .generated {
                    switch patientText {
                    case .content(let summary, _): if let summary { Text(summary) }
                    case .notice: Text(t("session.patientFacing.notice"))
                    }
                    let key = switch report.review {
                    case .approved: "session.complete.reviewStatusApproved"
                    case .revisionNeeded: "session.complete.reviewStatusRevisionNeeded"
                    case .pending: "session.complete.reviewStatusPending"
                    }
                    Text(t(key)).font(.subheadline)
                } else if fetching {
                    ProgressView(t("session.complete.reportAnalyzing"))
                } else {
                    Text(t("session.complete.reportEmpty"))
                }
                if let session {
                    NavigationLink(t("session.patientDetail.title")) { detail(session) }
                }
            }
            Section(t("session.complete.nextStepsTitle")) {
                ForEach(["nextStep1", "nextStep2", "nextStep3"], id: \.self) { key in
                    Label(t("session.complete." + key), systemImage: "checkmark.circle")
                }
            }
            Button(t("session.complete.actionHome"), action: onHome)
            Button(t("session.complete.actionHistory"), action: onHistory)
        }
        .navigationTitle(t("session.complete.title"))
        .task(id: id) {
            fetching = true
            defer { if !Task.isCancelled { fetching = false } }
            let path = "sessions/\(id.uuidString.lowercased())"
            do {
                let value: ClinicalSession = try await account.api.get(path, language: language)
                guard !Task.isCancelled else { return }
                session = value
            } catch APIError.signedOut {
                await account.noticeAuthorizationLoss(language)
                return
            } catch { if Task.isCancelled { return } }

            for attempt in 1...12 {
                do {
                    let next: KioskReportExcerpt = try await account.api.get("\(path)/report", language: language)
                    guard !Task.isCancelled else { return }
                    report = next
                    if next.status != .generating { return }
                } catch APIError.signedOut {
                    await account.noticeAuthorizationLoss(language)
                    return
                } catch { if Task.isCancelled { return } }
                if attempt < 12 {
                    do { try await Task.sleep(for: .seconds(3)) } catch { return }
                }
            }
        }
    }

    private func detail(_ session: ClinicalSession) -> some View {
        List {
            Text(language.text("session.patientDetail.recordId", args: ["id": session.id.uuidString.lowercased()]))
                .font(.caption)
            Section {
                Text(t(sessionStatusKey(session.status))).font(.headline)
                Text(date(session.createdAt))
                Text(language.text("session.patientDetail.chiefComplaint", args: [
                    "value": session.complaint ?? t("session.patientDetail.chiefComplaintEmpty")
                ]))
            }
            let content = patientText
            Section(t("session.patientDetail.summaryHeading")) {
                switch content {
                case let .content(summary, _): Text(summary ?? t("session.patientDetail.summaryEmpty"))
                case .notice: Text(t("session.patientFacing.notice"))
                }
            }
            Section(t("session.patientDetail.adviceHeading")) {
                if case let .content(_, education) = content, !education.isEmpty {
                    ForEach(Array(education.enumerated()), id: \.offset) { _, text in Text(text) }
                } else {
                    Text(t("session.patientDetail.adviceEmpty"))
                }
            }
            Section {
                LabeledContent(t("session.patientDetail.doctorLabel"),
                               value: session.doctorID?.uuidString.lowercased() ?? t("session.patientDetail.doctorUnassigned"))
                LabeledContent(t("session.patientDetail.durationLabel"), value: duration(session, fallback: "session.patientDetail.durationEmpty"))
            }
        }
        .navigationTitle(t("session.patientDetail.title"))
    }

    private func date(_ value: Date) -> String {
        value.formatted(.dateTime.year().month().day().hour().minute().locale(Locale(identifier: language.rawValue)))
    }

    private func duration(_ session: ClinicalSession, fallback: String) -> String {
        guard let seconds = session.duration else { return t(fallback) }
        return language.text("session.complete.durationMinutes", args: ["minutes": String(Int((Double(seconds) / 60).rounded()))])
    }
}
