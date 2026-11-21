import Charts
import SwiftUI

struct ResearchScreen: View {
    let account: Account
    let language: AppLanguage

    @State private var result: Load<ResearchData> = .loading
    @State private var export: ResearchExport?
    @State private var exportFailed = false

    var body: some View {
        List {
            switch result {
            case .loading, .signedOut:
                ProgressView(language.text("research.page.loading"))
            case .failed:
                Text(language.text("research.page.error"))
                Button(language.text("common.retry")) { Task { await load() } }
            case let .loaded(data):
                figures(data)
            }
        }
        .navigationTitle(language.text("research.page.title"))
        .task(id: language) {
            while !Task.isCancelled {
                await load()
                do { try await Task.sleep(for: .seconds(30)) } catch { return }
            }
        }
        .refreshable { await load() }
        .sheet(item: $export) { file in
            ActivitySheet(items: [file.image])
        }
        .alert(language.text("research.page.exportFailed"), isPresented: $exportFailed) {
            Button(language.text("session.doctor.detail.confirm")) {}
        }
    }

    @ViewBuilder private func figures(_ data: ResearchData) -> some View {
        Section(language.text("research.page.title")) {
            metrics(data.cohort, [("total_sessions", "kpi.sessions"), ("completion", "kpi.completionRate")])
            metrics(data.demographics, [("total_patients", "kpi.patients")])
            metrics(data.safety, [("alert_session", "kpi.redFlagRate")])
        }
        figure("demographics.title", subtitle: "demographics.subtitle") {
            metrics(data.demographics, [("age_years", "demographics.age")])
            chart(distribution(data.demographics, "age_band_distribution"), label: "demographics.ageBands")
            chart(distribution(data.demographics, "gender_distribution", prefix: "common.gender."), label: "demographics.gender")
            chart(distribution(data.demographics, "chief_complaint_distribution"), label: "demographics.caseMix")
        }
        figure("cohort.title", subtitle: "cohort.subtitle") {
            let trend = data.cohort["weekly_trend"]?.objects ?? []
            Chart(Array(trend.enumerated()), id: \.offset) { _, row in
                if let week = row["week_start"]?.string {
                    ForEach([("sessions", "cohort.seriesSessions"), ("completed", "cohort.seriesCompleted")], id: \.0) { key, title in
                        if let count = row[key]?.number {
                            LineMark(x: .value(language.text("research.cohort.title"), week),
                                     y: .value(language.text("research.kpi.sessions"), count))
                                .foregroundStyle(by: .value(language.text("research.kpi.sessions"), language.text("research.\(title)")))
                        }
                    }
                }
            }
            .chartXAxis(.hidden)
            .frame(height: 170)
        }
        figure("efficiency.title", subtitle: "efficiency.subtitle") {
            metrics(data.efficiency, [("duration_seconds", "efficiency.duration"), ("patient_turns", "efficiency.turns"),
                                      ("patient_turn_chars", "efficiency.chars")])
            chart(histogram(data.efficiency, "duration_histogram"), label: "efficiency.duration")
            chart(histogram(data.efficiency, "turns_histogram"), label: "efficiency.turns")
        }
        figure("hpi.title", subtitle: "hpi.subtitle") {
            let rates = (data.history["hpi_field_fill_rates"]?.objects ?? []).compactMap { row -> Point? in
                guard let field = row["field"]?.string, let rate = row["rate"]?.number else { return nil }
                return Point(label: language.text("research.hpi.fields.\(field)"), value: rate)
            }
            metrics(data.history, [("mean_hpi_completeness", "kpi.hpiCompleteness")])
            chart(rates, label: "hpi.title", percentage: true)
        }
        figure("safety.title", subtitle: "safety.subtitle") {
            metrics(data.safety, [("alert_session", "safety.alertRate"), ("acknowledged", "safety.ackRate"),
                                  ("time_to_first_alert_seconds", "safety.timeToFirstAlert"), ("ack_latency_seconds", "safety.ackLatency")])
            chart(distribution(data.safety, "severity_distribution", prefix: "research.safety.severity."), label: "safety.severityTitle")
        }
        figure("safety.urgencyTitle", subtitle: "safety.urgencySubtitle") {
            chart(distribution(data.safety, "urgency_distribution", prefix: "research.safety.urgency."), label: "safety.urgencyTitle")
            chart(distribution(data.safety, "layer_distribution", prefix: "research.safety.layer."), label: "safety.layerTitle")
        }
        figure("stt.title", subtitle: "stt.subtitle") {
            metrics(data.stt, [("turns_with_confidence", "stt.turns"), ("confidence_summary", "stt.medianConfidence"),
                               ("low_confidence", "stt.lowConfidence"), ("voice_turn_share", "stt.voiceShare")])
            chart(histogram(data.stt, "histogram"), label: "stt.medianConfidence")
        }
        figure("documentation.title", subtitle: "documentation.subtitle") {
            metrics(data.documentation, [("ai_confidence_summary", "documentation.aiConfidence"),
                                         ("icd10_verified", "documentation.icdVerified"),
                                         ("physician_agreement", "documentation.agreement")])
            chart(distribution(data.documentation, "review_outcomes", prefix: "research.documentation.outcomes."),
                  label: "documentation.outcomesTitle")
        }
        figure("forest.title", subtitle: "forest.subtitle") {
            forest(data)
        }
        Section(language.text("research.table.title")) {
            ForEach(Array(data.byLanguage.enumerated()), id: \.offset) { _, row in
                if let tag = row["language"]?.string {
                    DisclosureGroup(language.text("common.language.names.\(tag)")) {
                        metrics(row, [("sessions", "table.sessions"), ("completed", "table.completed"),
                                      ("median_duration_seconds", "table.medianDuration"), ("mean_patient_turns", "table.meanTurns"),
                                      ("mean_stt_confidence", "table.medianConfidence"), ("red_flag_rate", "table.redFlagRate")])
                    }
                }
            }
        }
        Section(language.text("research.methods.title")) {
            ForEach(["subtitle", "decideAi", "amie", "triage", "pdqi", "stats", "disclaimer"], id: \.self) { key in
                Text(language.text("research.methods.\(key)"))
            }
        }
    }

    private func figure<Content: View>(_ title: String, subtitle: String, @ViewBuilder content: () -> Content) -> some View {
        let caption = language.text("research.\(title)")
        let chartContent = VStack(alignment: .leading, spacing: 12, content: content)
        return Section(caption) {
            Text(language.text("research.\(subtitle)")).foregroundStyle(.secondary)
            chartContent
            Button(language.text("research.page.exportPng"), systemImage: "square.and.arrow.up") {
                let renderer = ImageRenderer(content: VStack(alignment: .leading, spacing: 12) {
                    Text(caption).font(.headline)
                    chartContent
                }
                .padding()
                .frame(width: 420)
                .foregroundStyle(.black)
                .background(.white)
                .environment(\.colorScheme, .light)
                .environment(\.locale, Locale(identifier: language.rawValue)))
                renderer.scale = 3
                if let image = renderer.uiImage { export = ResearchExport(image: image) }
                else { exportFailed = true }
            }
        }
    }

    @ViewBuilder private func metrics(_ values: [String: ClinicalValue], _ fields: [(String, String)]) -> some View {
        ForEach(fields, id: \.0) { key, title in
            let value = values[key]
            let label = language.text("research.\(title)")
            if let summary = value?.object {
                if let median = summary["median"]?.number {
                    LabeledContent(label, value: interval(value: median, low: summary["p25"]?.number, high: summary["p75"]?.number))
                } else if let proportion = summary["value"]?.number {
                    LabeledContent(label, value: proportional(proportion, summary: summary))
                } else {
                    LabeledContent(label, value: "—")
                }
            } else if let number = value?.number {
                LabeledContent(label, value: number.formatted(.number.precision(.fractionLength(0...2))))
            } else {
                LabeledContent(label, value: "—")
            }
        }
    }

    private func proportional(_ value: Double, summary: [String: ClinicalValue]) -> String {
        let format = FloatingPointFormatStyle<Double>.Percent().precision(.fractionLength(1))
        let percent = value.formatted(format)
        guard let numerator = summary["numerator"]?.number, let denominator = summary["denominator"]?.number,
              let low = summary["ci_low"]?.number, let high = summary["ci_high"]?.number else { return percent }
        return "\(percent) (\(Int(numerator))/\(Int(denominator)); \(low.formatted(format))–\(high.formatted(format)))"
    }

    private func interval(value: Double, low: Double?, high: Double?) -> String {
        let style = FloatingPointFormatStyle<Double>.number.precision(.fractionLength(0...2))
        guard let low, let high else { return value.formatted(style) }
        return "\(value.formatted(style)) (\(low.formatted(style))–\(high.formatted(style)))"
    }

    private func chart(_ values: [Point], label: String, percentage: Bool = false) -> some View {
        let title = language.text("research.\(label)")
        return VStack(alignment: .leading) {
            Text(title).font(.subheadline.bold())
            if values.isEmpty {
                Text(language.text("research.page.empty")).foregroundStyle(.secondary)
            } else {
                Chart(Array(values.enumerated()), id: \.offset) { _, item in
                    BarMark(x: .value(title, item.value), y: .value(title, item.label))
                        .annotation(position: .trailing) {
                            Text(item.value.formatted(percentage
                                ? .number.scale(100).precision(.fractionLength(0...1))
                                : .number.precision(.fractionLength(0...1))) + (percentage ? "%" : ""))
                                .font(.caption)
                        }
                }
                .chartXScale(domain: 0...max(percentage ? 1.2 : 1, (values.map(\.value).max() ?? 0) * 1.2))
                .frame(height: max(100, CGFloat(values.count) * 26))
            }
        }
    }

    private func forest(_ data: ResearchData) -> some View {
        let rows = data.byLanguage.compactMap { row -> ForestPoint? in
            guard let tag = row["language"]?.string, let rate = row["red_flag_rate"]?.object,
                  let value = rate["value"]?.number, let low = rate["ci_low"]?.number, let high = rate["ci_high"]?.number
            else { return nil }
            return ForestPoint(label: language.text("common.language.names.\(tag)"), value: value, low: low, high: high)
        }
        return Chart(rows, id: \.label) { row in
            RuleMark(xStart: .value("95% CI", row.low), xEnd: .value("95% CI", row.high),
                     y: .value(language.text("research.table.language"), row.label))
            PointMark(x: .value(language.text("research.forest.xLabel"), row.value),
                      y: .value(language.text("research.table.language"), row.label))
        }
        .chartXScale(domain: 0...1)
        .frame(height: max(125, CGFloat(rows.count) * 30))
    }

    private func distribution(_ values: [String: ClinicalValue], _ key: String, prefix: String = "") -> [Point] {
        (values[key]?.objects ?? []).compactMap { row in
            guard let raw = row["key"]?.string, let count = row["count"]?.number else { return nil }
            let translated = language.text(prefix + raw)
            return Point(label: translated == prefix + raw ? raw : translated, value: count)
        }
    }

    private func histogram(_ values: [String: ClinicalValue], _ key: String) -> [Point] {
        (values[key]?.objects ?? []).compactMap { row in
            guard let start = row["start"]?.number, let end = row["end"]?.number, let count = row["count"]?.number else { return nil }
            let style = FloatingPointFormatStyle<Double>.number.precision(.fractionLength(0...2))
            return Point(label: "\(start.formatted(style))–\(end.formatted(style))", value: count)
        }
    }

    private func load() async {
        guard account.currentUser?.isSystemAdmin == true else { return }
        let next: Load<ResearchData> = await Load.fetch {
            try await account.api.get("research/analytics", language: language)
        }
        guard !Task.isCancelled else { return }
        result = next
        if next.isSignedOut { await account.noticeAuthorizationLoss(language) }
    }

    private struct Point { let label: String; let value: Double }
    private struct ForestPoint { let label: String; let value: Double; let low: Double; let high: Double }
    private struct ResearchExport: Identifiable { let id = UUID(); let image: UIImage }
}

private struct ResearchData: Decodable, Sendable {
    let cohort: [String: ClinicalValue]
    let demographics: [String: ClinicalValue]
    let efficiency: [String: ClinicalValue]
    let history: [String: ClinicalValue]
    let safety: [String: ClinicalValue]
    let stt: [String: ClinicalValue]
    let documentation: [String: ClinicalValue]
    let byLanguage: [[String: ClinicalValue]]

    enum CodingKeys: String, CodingKey {
        case cohort, demographics, efficiency, safety, documentation
        case history = "history_taking", stt = "stt_quality", byLanguage = "by_language"
    }
}

private extension ClinicalValue {
    var object: [String: Self]? {
        if case let .object(value) = self { return value }
        return nil
    }

    var objects: [[String: Self]] {
        if case let .array(value) = self { return value.compactMap(\.object) }
        return []
    }

    var string: String? {
        if case let .text(value) = self { return value }
        return nil
    }

    var number: Double? {
        if case let .number(value) = self { return NSDecimalNumber(decimal: value).doubleValue }
        return nil
    }
}
