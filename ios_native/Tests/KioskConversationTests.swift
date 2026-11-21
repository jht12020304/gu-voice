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
    nonisolated let closeCode: URLSessionWebSocketTask.CloseCode = .invalid
    init(frames: [String]) { self.frames = frames }

    func receive() throws -> URLSessionWebSocketTask.Message {
        guard !frames.isEmpty else { throw URLError(.networkConnectionLost) }
        return .string(frames.removeFirst())
    }

    func send(_ message: URLSessionWebSocketTask.Message) {}
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
