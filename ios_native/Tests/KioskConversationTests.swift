import XCTest
@testable import GUVoice

@MainActor
final class KioskConversationTests: XCTestCase {
    func testDisconnectResumesSameSessionAndReconcilesPersistedTranscriptBeforeCriticalStop() async {
        let stored = ConversationTurn(id: UUID(), sequence: 1, role: "patient", content: "persisted patient turn", confidence: nil)
        let first = ConversationScript(frames: [
            #"{"type":"connection_ack"}"#,
            #"{"type":"ai_response_start","payload":{"messageId":"partial"}}"#,
            #"{"type":"ai_response_chunk","payload":{"messageId":"partial","text":"unfinished reply"}}"#
        ])
        let resumed = ConversationScript(frames: [
            #"{"type":"connection_ack"}"#,
            #"{"type":"resume_failed","payload":{"code":"events.session.resume_failed"}}"#,
            #"{"type":"red_flag_alert","payload":{"alertId":"f","severity":"critical","title":"flag","patientNotice":"tell on-site staff"}}"#,
            #"{"type":"session_status","payload":{"status":"aborted_red_flag","code":"events.session.aborted_red_flag"}}"#
        ])
        let endpoint = ConversationEndpoint(sockets: [first, resumed], snapshots: [
            .init(status: "waiting", conversations: []),
            .init(status: "in_progress", conversations: []),
            .init(status: "in_progress", conversations: [stored])
        ])
        let id = UUID()
        let model = KioskConversation(id: id, source: endpoint, language: .english)
        await model.run(retryDelay: .zero)
        XCTAssertEqual(model.terminal, "aborted_red_flag")
        XCTAssertEqual(model.connection, .ended)
        XCTAssertEqual(model.messages.map(\.text), ["persisted patient turn"])
        XCTAssertEqual(model.flags.first?.notice, "tell on-site staff")
        XCTAssertFalse(model.canInput)
        let opens = await endpoint.opens
        XCTAssertEqual(opens.map(\.id), [id, id])
        XCTAssertEqual(opens.map(\.checksum), [nil, "history-checksum"])
    }

    func testFourAcknowledgedConnectionsMayEachReconnect() async {
        let ack = #"{"type":"connection_ack"}"#
        let done = #"{"type":"session_status","payload":{"status":"completed"}}"#
        let sockets = (0..<4).map { _ in ConversationScript(frames: [ack]) } + [.init(frames: [ack, done])]
        let endpoint = ConversationEndpoint(sockets: sockets, snapshots: .init(repeating: .init(status: "in_progress", conversations: []), count: 5))
        let model = KioskConversation(id: UUID(), source: endpoint, language: .english)
        await model.run(retryDelay: .zero)
        let opens = await endpoint.opens
        XCTAssertEqual(opens.count, 5)
        XCTAssertEqual(model.terminal, "completed")
    }

    func testEndAfterSpeechQueuesFinalAudioBeforeControlAndPollsQuietlyThroughSlowReply() async {
        let socket = ConversationScript(frames: [
            #"{"type":"connection_ack"}"#, "@client",
            #"{"type":"session_status","payload":{"status":"completed"}}"#
        ])
        let active = KioskSnapshot(status: "in_progress", conversations: [])
        let endpoint = ConversationEndpoint(sockets: [socket], snapshots: .init(repeating: active, count: 10))
        let mic = KioskAudio(requestPermission: { true }, inputFactory: { SpeakingInput(deliver: $0) })
        let model = KioskConversation(id: UUID(), source: endpoint, language: .english, audio: mic, endCheckInterval: .milliseconds(5))
        await socket.whenClientActs {
            await model.openMic()
            await self.eventually { mic.isSpeaking }
            model.end()
            model.receive("ai_response_start", payload: ["messageId": "last"])
            model.receive("ai_response_chunk", payload: ["messageId": "last", "text": "reply", "audioB64": "AAAA"])
            XCTAssertEqual(model.messages.last?.audio.count, 0)
            await self.eventually { model.canLeaveWithoutConfirmation }
            XCTAssertTrue(model.ending)
            XCTAssertFalse(model.allowsListening)
            XCTAssertNil(model.terminal)
            XCTAssertNil(model.error)
            model.receive("ai_response_end", payload: ["messageId": "last"])
            await self.eventually { await socket.sent.count >= 2 }
        }
        await model.run(retryDelay: .zero)
        let sent = await socket.sent
        let frames = sent.compactMap { try? JSONSerialization.jsonObject(with: Data($0.utf8)) as? [String: Any] }
        XCTAssertEqual(frames.compactMap { $0["type"] as? String }, ["audio_chunk", "control"])
        let payload = frames.first?["payload"] as? [String: Any]
        XCTAssertEqual(payload?["isFinal"] as? Bool, true)
        let wav = (payload?["audioData"] as? String).flatMap { Data(base64Encoded: $0) }
        XCTAssertEqual(wav?.prefix(4), Data("RIFF".utf8))
        XCTAssertEqual(wav?.count, 44 + 1600 * 2)
        XCTAssertEqual((frames.last?["payload"] as? [String: String])?["action"], "end_session")
        XCTAssertEqual(model.terminal, "completed")
    }

    func testFailedSendRecoversMissingIdenticalAnswerButNeverReplaysOrOverwritesNewDraft() async {
        await assertDeliveryRecovery(persisted: false, newDraft: "")
        await assertDeliveryRecovery(persisted: false, newDraft: "next answer in progress")
        await assertDeliveryRecovery(persisted: true, newDraft: "next answer in progress")
    }

    func testServerRejectsTextRestoresDraftAndKeepsLocalizedFailureWithoutBlockingRetry() async {
        let socket = ConversationScript(frames: [#"{"type":"connection_ack"}"#, "@client",
                                                 #"{"type":"session_status","payload":{"status":"completed"}}"#])
        let active = KioskSnapshot(status: "in_progress", conversations: [])
        let endpoint = ConversationEndpoint(sockets: [socket], snapshots: [active, active])
        let model = KioskConversation(id: UUID(), source: endpoint, language: .english)
        await socket.whenClientActs {
            XCTAssertTrue(model.sendText("my answer"))
            model.receive("error", payload: ["code": "errors.ws.rate_limit_exceeded", "params": ["retryAfter": 5]])
            await self.eventually { model.canSendText }
            XCTAssertEqual(model.draft, "my answer")
            XCTAssertTrue(model.messages.isEmpty)
            XCTAssertEqual(model.error, AppLanguage.english.text("ws.errors.ws.rate_limit_exceeded", args: ["retryAfter": "5"]))
        }
        await model.run(retryDelay: .zero)
    }

    private func assertDeliveryRecovery(persisted: Bool, newDraft: String) async {
        func answer(_ sequence: Int) -> ConversationTurn {
            ConversationTurn(id: UUID(), sequence: sequence, role: "patient", content: "no", confidence: nil)
        }
        let prior = answer(1)
        let first = ConversationScript(frames: [#"{"type":"connection_ack"}"#, "@client"], failWrites: true)
        let second = ConversationScript(frames: [
            #"{"type":"connection_ack"}"#, "@client",
            #"{"type":"session_status","payload":{"status":"completed"}}"#
        ])
        let endpoint = ConversationEndpoint(sockets: [first, second], snapshots: [
            .init(status: "in_progress", conversations: [prior]),
            .init(status: "in_progress", conversations: persisted ? [prior, answer(2)] : [prior])
        ])
        let model = KioskConversation(id: UUID(), source: endpoint, language: .english)
        await first.whenClientActs {
            model.draft = "no"
            XCTAssertTrue(model.sendText(model.draft))
            model.draft = newDraft
            await self.eventually { await first.sent.count == 1 }
        }
        await second.whenClientActs {
            XCTAssertEqual(model.draft, newDraft.isEmpty && !persisted ? "no" : newDraft)
            XCTAssertEqual(model.recoveredDrafts.map(\.text), !persisted && !newDraft.isEmpty ? ["no"] : [])
            XCTAssertEqual(model.messages.map(\.text), persisted ? ["no", "no"] : ["no"])
            if !persisted { XCTAssertEqual(model.error, AppLanguage.english.text("conversation.input.sendOffline")) }
            let retried = await second.sent
            XCTAssertTrue(retried.isEmpty)
        }
        await model.run(retryDelay: .zero)
        XCTAssertEqual(model.terminal, "completed")
        model.close()
        XCTAssertTrue(model.draft.isEmpty && model.recoveredDrafts.isEmpty)
    }

    private func eventually(_ condition: () async -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        let deadline = ContinuousClock.now.advanced(by: .seconds(2))
        while !(await condition()) {
            guard ContinuousClock.now < deadline else { return XCTFail("Timed out", file: file, line: line) }
            try? await Task.sleep(for: .milliseconds(1))
        }
    }

    func testMissedTerminalDuringDisconnectUsesRESTAndDoesNotStartAnotherSocket() async {
        let endpoint = ConversationEndpoint(sockets: [.init(frames: [#"{"type":"connection_ack"}"#])],
                                            snapshots: [.init(status: "waiting", conversations: []),
                                                        .init(status: "completed", conversations: [])])
        let model = KioskConversation(id: UUID(), source: endpoint, language: .english)
        await model.run(retryDelay: .zero)
        XCTAssertEqual(model.terminal, "completed")
        let opens = await endpoint.opens
        XCTAssertEqual(opens.count, 1)
    }

    func testCriticalCannotSendOrCompleteFromAlertAloneAndDisposeRejectsLateFrames() {
        let endpoint = ConversationEndpoint(sockets: [], snapshots: [])
        let patient = KioskConversation(id: UUID(), source: endpoint, language: .english)
        patient.receive("connection_ack", payload: [:])
        patient.receive("stt_final", payload: ["text": "first patient's history"])
        patient.togglePause()
        patient.receive("red_flag_alert", payload: ["alertId": "f", "severity": "critical"])
        XCTAssertFalse(patient.canInput)
        XCTAssertFalse(patient.sendText("late text"))
        patient.receive("session_status", payload: ["code": "events.session.ended_by_user"])
        XCTAssertNil(patient.terminal)
        patient.receive("session_status", payload: ["status": "aborted_red_flag"])
        patient.receive("session_status", payload: ["status": "completed"])
        XCTAssertEqual(patient.terminal, "aborted_red_flag")

        patient.close()
        patient.receive("stt_final", payload: ["text": "late first patient event"])
        XCTAssertTrue(patient.messages.isEmpty)
        XCTAssertTrue(patient.flags.isEmpty)
        XCTAssertFalse(patient.paused)
        let second = KioskConversation(id: UUID(), source: endpoint, language: .english)
        XCTAssertNil(second.terminal)
        XCTAssertTrue(second.messages.isEmpty)
        XCTAssertTrue(second.flags.isEmpty)
        XCTAssertFalse(second.paused)
        XCTAssertNil(second.error)
    }

    func testMicGateRequiresAnAvailableTurnAndNeverClearsPatientPause() {
        let endpoint = ConversationEndpoint(sockets: [], snapshots: [])
        let model = KioskConversation(id: UUID(), source: endpoint, language: .english)
        XCTAssertFalse(model.allowsListening)
        model.receive("connection_ack", payload: [:])
        XCTAssertTrue(model.allowsListening)
        model.receive("ai_response_start", payload: ["messageId": "greeting"])
        XCTAssertFalse(model.allowsListening)
        model.togglePause()
        model.configureVoice(muted: true, speed: 1)
        model.receive("ai_response_end", payload: ["messageId": "greeting"])
        model.receive("stt_final", payload: ["text": ""])
        XCTAssertFalse(model.allowsListening)
        model.togglePause()
        XCTAssertTrue(model.allowsListening)
        model.receive("red_flag_alert", payload: ["severity": "critical"])
        XCTAssertFalse(model.allowsListening)
        model.close()
        XCTAssertFalse(model.allowsListening)
    }

    func testExhaustedReconnectProvidesExitWithoutCompletingAndEndWaitsForStatus() async {
        let endpoint = ConversationEndpoint(sockets: [], snapshots: [])
        let model = KioskConversation(id: UUID(), source: endpoint, language: .english)
        model.receive("connection_ack", payload: [:])
        model.end()
        XCTAssertTrue(model.ending)
        XCTAssertNil(model.terminal)
        await model.run(retryDelay: .zero)
        XCTAssertEqual(model.connection, .interrupted)
        XCTAssertFalse(model.ending)
        XCTAssertNotNil(model.error)
        XCTAssertNil(model.terminal)
    }
}

private actor ConversationScript: KioskSocket {
    var frames: [String]
    var sent: [String] = []
    private let failWrites: Bool
    private var clientAction: (@MainActor @Sendable () async -> Void)?
    nonisolated let closeCode: URLSessionWebSocketTask.CloseCode = .invalid
    init(frames: [String], failWrites: Bool = false) {
        self.frames = frames
        self.failWrites = failWrites
    }

    func whenClientActs(_ action: @escaping @MainActor @Sendable () async -> Void) { clientAction = action }

    func receive() async throws -> URLSessionWebSocketTask.Message {
        if frames.first == "@client" {
            frames.removeFirst()
            await clientAction?()
            clientAction = nil
        }
        guard !frames.isEmpty else { throw URLError(.networkConnectionLost) }
        return .string(frames.removeFirst())
    }

    func send(_ message: URLSessionWebSocketTask.Message) throws {
        if case let .string(frame) = message { sent.append(frame) }
        if failWrites { throw URLError(.networkConnectionLost) }
    }
    nonisolated func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {}
}

private actor ConversationEndpoint: KioskConversationSource {
    var sockets: [ConversationScript]
    var snapshots: [KioskSnapshot]
    var opens: [(id: UUID, checksum: String?)] = []

    init(sockets: [ConversationScript], snapshots: [KioskSnapshot]) {
        self.sockets = sockets
        self.snapshots = snapshots
    }

    func kioskSnapshot(for id: UUID, language: AppLanguage) throws -> KioskSnapshot {
        guard !snapshots.isEmpty else { throw URLError(.notConnectedToInternet) }
        return snapshots.removeFirst()
    }

    func kioskResume(for id: UUID, language: AppLanguage) -> String? { "history-checksum" }

    func kioskSocket(for id: UUID, resume: String?) throws -> any KioskSocket {
        opens.append((id, resume))
        guard !sockets.isEmpty else { throw URLError(.notConnectedToInternet) }
        return sockets.removeFirst()
    }
}

private final class SpeakingInput: KioskMicInput {
    let deliver: KioskAudio.DeliverFrame
    init(deliver: @escaping KioskAudio.DeliverFrame) { self.deliver = deliver }
    func start() throws { deliver(Array(repeating: 4000, count: 1600), mach_absolute_time()) }
    func pause() {}
    func detach() {}
}
