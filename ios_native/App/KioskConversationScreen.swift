import SwiftUI

struct KioskConversationScreen: View {
    let account: Account
    let sessionID: UUID
    let language: AppLanguage
    let onTerminal: (String) -> Void
    let onLeave: () -> Void

    var body: some View {
        ConversationContent(account: account, sessionID: sessionID, language: language,
                            onTerminal: onTerminal, onLeave: onLeave)
            .id(sessionID)
    }
}

private struct ConversationContent: View {
    let account: Account
    let language: AppLanguage
    let onTerminal: (String) -> Void
    let onLeave: () -> Void
    @State private var model: KioskConversation
    @State private var draft = ""
    @State private var confirmEnd = false
    @State private var retry = 0
    @AppStorage("kioskTtsMuted") private var muted = false
    @AppStorage("kioskTtsSpeed") private var speed = 1.0

    init(account: Account, sessionID: UUID, language: AppLanguage,
         onTerminal: @escaping (String) -> Void, onLeave: @escaping () -> Void) {
        self.account = account
        self.language = language
        self.onTerminal = onTerminal
        self.onLeave = onLeave
        _model = State(initialValue: KioskConversation(id: sessionID, source: account.api, language: language))
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    connectionNotice.id("connection-notice")
                    guidance.id("consultation-guidance")
                    ForEach(model.messages) { message in bubble(message) }
                }
                .frame(maxWidth: 760, alignment: .leading)
                .padding()
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: model.flags.count) { old, new in
                if new > old { proxy.scrollTo("consultation-guidance", anchor: .top) }
            }
            .onChange(of: model.connection) { _, connection in
                if connection == .interrupted || connection == .reconnecting { proxy.scrollTo("connection-notice", anchor: .top) }
            }
            .onChange(of: model.error) { _, error in
                if error != nil { proxy.scrollTo("connection-notice", anchor: .top) }
            }
            .onChange(of: model.messages.last?.id) { _, id in
                if let id { proxy.scrollTo(id, anchor: .bottom) }
            }
        }
        .safeAreaInset(edge: .bottom) { controls }
        .navigationTitle(language.text("conversation.title"))
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden()
        .interactiveDismissDisabled()
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(language.text(model.ending ? "conversation.endSessionPending" : "conversation.endSession")) {
                    confirmEnd = true
                }
                .accessibilityIdentifier("kiosk-end")
                .disabled(model.ending || model.critical || model.connection == .interrupted)
            }
        }
        .alert(language.text("conversation.endSession"), isPresented: $confirmEnd) {
            Button(language.text("common.language.switchModal.cancel"), role: .cancel) {}
            Button(language.text("conversation.endSession"), role: .destructive) { model.end() }
                .accessibilityIdentifier("kiosk-end-confirm")
        }
        .task {
            model.configureVoice(muted: muted, speed: speed)
            await model.openMic()
        }
        .task(id: model.noSpeech) {
            guard model.noSpeech else { return }
            do { try await Task.sleep(for: .seconds(4)); model.clearSpeechHint() } catch {}
        }
        .task(id: retry) {
            await model.run()
            if !Task.isCancelled { await account.noticeAuthorizationLoss(language) }
        }
        .onChange(of: muted) { _, value in model.configureVoice(muted: value, speed: speed) }
        .onChange(of: speed) { _, value in model.configureVoice(muted: muted, speed: value) }
        .onChange(of: model.terminal) { _, status in if let status { onTerminal(status) } }
        .onDisappear { model.close() }
    }

    @ViewBuilder private var guidance: some View {
        ForEach(model.flags.prefix(3)) { flag in
            VStack(alignment: .leading, spacing: 6) {
                Label(flag.title.isEmpty ? language.text("conversation.redFlag.generic") : flag.title,
                      systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red).font(.headline)
                Text(flag.notice.flatMap { $0.isEmpty ? nil : $0 } ?? language.text("conversation.redFlag.patientNotice"))
                if flag.acknowledged {
                    Image(systemName: "checkmark.circle").accessibilityLabel(language.text("common.acknowledge"))
                } else {
                    Button(language.text("dashboard.alert.acknowledge")) { model.acknowledge(flag.id) }
                }
            }
        }
        if model.flags.count > 3 {
            Text(language.text("conversation.redFlag.more", args: ["count": String(model.flags.count - 3)]))
        }
        if model.degraded { Text(language.text("conversation.supervisor.degraded")) }
        if !model.focus.isEmpty {
            Text("\(language.text("conversation.supervisor.hintLabel"))  \(model.focus)")
        }
        if !model.missingHPI.isEmpty {
            Text(language.text("conversation.supervisor.missingLabel") + " " +
                 model.missingHPI.map { language.text("conversation.supervisor.hpi.\($0)") }.joined(separator: " · "))
        }
    }

    private func bubble(_ message: KioskConversation.Message) -> some View {
        let patient = message.role == "patient"
        return VStack(alignment: patient ? .trailing : .leading, spacing: 5) {
            Text(language.text("common.roles.\(message.role)"))
                .font(.caption).foregroundStyle(.secondary)
            Text(message.text.isEmpty && message.role == "assistant" ? "…" : message.text)
            if message.ttsFailed { Text(language.text("conversation.tts.failed")).font(.caption) }
            if !message.audio.isEmpty {
                Button { model.replay(message) } label: {
                    Label(language.text("conversation.tts.replayAria"), systemImage: "speaker.wave.2")
                }
                .disabled(!model.canInput)
            }
        }
        .padding(12)
        .background(patient ? Color.accentColor.opacity(0.12) : Color.secondary.opacity(0.09),
                    in: RoundedRectangle(cornerRadius: 14))
        .frame(maxWidth: .infinity, alignment: patient ? .trailing : .leading)
        .id(message.id)
    }

    @ViewBuilder private var connectionNotice: some View {
        if model.connection == .connecting {
            ProgressView(language.text("conversation.loading"))
        } else if model.connection == .reconnecting {
            ProgressView(language.text("conversation.connection.reconnecting"))
        } else if model.connection == .interrupted {
            HStack {
                Button(language.text("conversation.connection.retry")) { retry += 1 }
                Button(language.text("session.complete.actionHome"), action: onLeave)
            }
            .buttonStyle(.bordered)
        }
        if let problem = model.error {
            Label(problem, systemImage: "exclamationmark.circle").foregroundStyle(.red)
        }
        if let reason = model.audio.unavailable {
            let key = reason == .permissionDenied ? "conversation.error.micPermission" : "conversation.error.micNotFound"
            Label(language.text(key), systemImage: "mic.slash")
                .font(.callout).foregroundStyle(.secondary)
        }
    }

    private var status: String {
        if model.noSpeech && !model.audio.isSpeaking { return language.text("conversation.status.noSpeechDetected") }
        if model.audio.unavailable != nil { return language.text("conversation.input.textPlaceholder") }
        if model.paused { return language.text("conversation.voiceControl.pausedBanner") }
        if model.responding { return language.text("conversation.status.speaking") }
        if model.waiting { return language.text("conversation.status.transcribing") }
        if model.audio.isSpeaking {
            return language.text("conversation.status.listening", args: ["duration": "\(model.audio.elapsedSeconds)"])
        }
        return language.text("conversation.status.idle")
    }

    private var controls: some View {
        VStack(spacing: 8) {
            if model.canInput {
                if model.audio.isSpeaking {
                    HStack(alignment: .center, spacing: 2) {
                        ForEach(Array(model.audio.waveform.enumerated()), id: \.offset) { _, sample in
                            Capsule().fill(.tint).frame(width: 3, height: max(3, min(28, 28 * sample)))
                        }
                    }.frame(height: 28).accessibilityHidden(true)
                }
                Text(status).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
            HStack {
                TextField(language.text("conversation.input.textPlaceholder"), text: $draft, axis: .vertical)
                    .textFieldStyle(.roundedBorder).lineLimit(1...3)
                    .accessibilityIdentifier("kiosk-message")
                    .onChange(of: draft) { _, value in if value.count > 2000 { draft = String(value.prefix(2000)) } }
                Button {
                    if model.sendText(draft) { draft = "" }
                } label: {
                    Label(language.text("conversation.input.send"), systemImage: "arrow.up.circle.fill")
                        .labelStyle(.iconOnly).font(.title2)
                }
                .frame(minWidth: 44, minHeight: 44)
                .accessibilityIdentifier("kiosk-send")
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !model.canInput || model.waiting || model.responding)
            }
            HStack(spacing: 20) {
                Button(action: model.togglePause) {
                    Label(language.text(model.paused ? "conversation.voiceControl.resume" : "conversation.voiceControl.pause"),
                          systemImage: model.paused ? "mic" : "mic.slash")
                }
                .disabled(!model.canInput || model.audio.unavailable != nil)
                Button { muted.toggle() } label: {
                    Label(language.text(muted ? "conversation.tts.unmuteLabel" : "conversation.tts.muteLabel"),
                          systemImage: muted ? "speaker.slash" : "speaker.wave.2")
                }
                Button { speed = speed == 1 ? 1.25 : speed == 1.25 ? 1.5 : 1 } label: {
                    Text("\(speed.formatted())×")
                }
                .accessibilityLabel(language.text("conversation.tts.speedLabel", args: ["rate": speed.formatted()]))
                Button(action: model.audio.finishUtterance) {
                    Label(language.text("conversation.voiceControl.finishSpeaking"), systemImage: "checkmark.circle")
                }
                .disabled(!model.canInput || !model.audio.isSpeaking)
            }
            .labelStyle(.iconOnly).buttonStyle(.bordered).controlSize(.large)
        }
        .frame(maxWidth: 760)
        .padding(.horizontal)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity)
        .background(.bar)
    }
}
