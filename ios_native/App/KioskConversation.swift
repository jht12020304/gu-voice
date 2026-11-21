import Foundation
import Observation

protocol KioskSocket: AnyObject, Sendable {
    func receive() async throws -> URLSessionWebSocketTask.Message
    func send(_ message: URLSessionWebSocketTask.Message) async throws
    func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?)
    var closeCode: URLSessionWebSocketTask.CloseCode { get }
}

extension URLSessionWebSocketTask: KioskSocket {}

struct KioskSnapshot: Decodable, Sendable {
    let status: String
    let conversations: [ConversationTurn]
}

protocol KioskConversationSource: Sendable {
    func kioskSnapshot(for id: UUID, language: AppLanguage) async throws -> KioskSnapshot
    func kioskResume(for id: UUID, language: AppLanguage) async throws -> String?
    func kioskSocket(for id: UUID, resume: String?) async throws -> any KioskSocket
}

extension APIClient: KioskConversationSource {
    func kioskSnapshot(for id: UUID, language: AppLanguage) async throws -> KioskSnapshot {
        try await get("sessions/\(id.uuidString.lowercased())", language: language)
    }

    func kioskResume(for id: UUID, language: AppLanguage) async throws -> String? {
        struct Resume: Decodable { let checksum: String? }
        let data = try await request("sessions/\(id.uuidString.lowercased())/reconnect", language: language, method: "POST")
        return try JSONDecoder().decode(Resume.self, from: data).checksum
    }
}

@Observable @MainActor
final class KioskConversation {
    struct Message: Identifiable {
        let id: String
        let role: String
        var text: String
        var audio: [String] = []
        var ttsFailed = false
    }

    struct Flag: Identifiable {
        let id: String
        let severity: String
        let title: String
        let notice: String?
        var acknowledged = false
    }

    enum Connection: Equatable { case connecting, ready, reconnecting, interrupted, ended }
    private(set) var connection = Connection.connecting
    private(set) var messages: [Message] = []
    private(set) var flags: [Flag] = []
    private(set) var terminal: String?
    private(set) var paused = false
    private(set) var responding = false
    private(set) var waiting = false
    private(set) var ending = false
    private(set) var critical = false
    private(set) var noSpeech = false
    private(set) var error: String?
    private(set) var focus = ""
    private(set) var missingHPI: [String] = []
    private(set) var degraded = false
    let audio = KioskAudio()

    private let id: UUID
    private let source: any KioskConversationSource
    private let language: AppLanguage
    private var socket: (any KioskSocket)?
    private var outgoing: AsyncStream<String>.Continuation?
    private var endWatch: Task<Void, Never>?
    private var disposed = false
    private var playing = false
    private var playbackGeneration = 0
    private var ttsMuted = false
    private var speed = 1.0

    init(id: UUID, source: any KioskConversationSource, language: AppLanguage) {
        self.id = id
        self.source = source
        self.language = language
    }

    var canInput: Bool { connection == .ready && !critical && !ending }
    var allowsListening: Bool {
        canInput && !disposed && !paused && !waiting && !playing && (!responding || ttsMuted)
    }

    func configureVoice(muted: Bool, speed: Double) {
        self.speed = speed
        if muted != ttsMuted {
            ttsMuted = muted
            if muted { stopPlayback() }
            updateMic()
        }
    }

    func openMic() async {
        guard !disposed else { return }
        audio.onUtterance = { [weak self] data in self?.sendAudio(data) }
        await audio.openMic()
        guard !disposed else { return }
        updateMic()
    }

    // Each pass reconciles the visible transcript and terminal status before admitting input.
    func run(retryDelay: Duration = .seconds(1)) async {
        connection = .connecting
        var retries = 0
        while !disposed && !Task.isCancelled && terminal == nil {
            do {
                let snapshot = try await reload()
                guard !disposed, terminal == nil else { return }
                let resume = retries > 0 || snapshot.status == "in_progress"
                    ? try await source.kioskResume(for: id, language: language) : nil
                try Task.checkCancellation()
                guard !disposed else { return }
                let next = try await source.kioskSocket(for: id, resume: resume)
                guard !disposed, !Task.isCancelled else {
                    next.cancel(with: .goingAway, reason: nil)
                    return
                }
                socket = next
                try await channel(next)
            } catch {
                guard !disposed, !Task.isCancelled, terminal == nil, connection != .interrupted else { return }
                let code = socket?.closeCode.rawValue
                connection = .reconnecting
                resetConnection()
                if code == 4009 {
                    // Another worker may have ended this session between REST and the handshake.
                    _ = try? await reload()
                    guard !disposed, !Task.isCancelled, terminal == nil else { return }
                }
                if error as? APIError == .signedOut || [4003, 4004, 4009].contains(code ?? 0) || retries >= 3 {
                    connection = .interrupted
                    self.error = language.text("conversation.error.sessionInterrupted")
                    return
                }
                retries += 1
                do { try await Task.sleep(for: retryDelay * (1 << (retries - 1))) }
                catch { return }
            }
        }
    }

    private func reload() async throws -> KioskSnapshot {
        let snapshot = try await source.kioskSnapshot(for: id, language: language)
        try Task.checkCancellation()
        guard !disposed else { throw CancellationError() }
        if !setTerminal(snapshot.status) {
            messages = snapshot.conversations.sorted { $0.sequence < $1.sequence }.map {
                Message(id: $0.id.uuidString, role: $0.role, text: $0.content)
            }
        }
        return snapshot
    }

    private func channel(_ channel: any KioskSocket) async throws {
        let (stream, continuation) = AsyncStream<String>.makeStream()
        outgoing = continuation
        let writer = Task {
            do {
                for await frame in stream {
                    try Task.checkCancellation()
                    try await channel.send(.string(frame))
                }
            } catch { channel.cancel(with: .goingAway, reason: nil) }
        }
        // Use WebSocket control frames for keepalive. Application pings count as patient activity.
        let monitor = Task {
            try await Task.sleep(for: .seconds(15))
            if connection != .ready { channel.cancel(with: .goingAway, reason: nil); return }
            while !Task.isCancelled {
                if let urlSocket = channel as? URLSessionWebSocketTask {
                    let deadline = Task {
                        try await Task.sleep(for: .seconds(12))
                        channel.cancel(with: .goingAway, reason: nil)
                    }
                    urlSocket.sendPing { error in
                        deadline.cancel()
                        if error != nil { channel.cancel(with: .goingAway, reason: nil) }
                    }
                }
                try await Task.sleep(for: .seconds(30))
            }
        }
        defer {
            continuation.finish()
            writer.cancel()
            monitor.cancel()
        }
        try await withTaskCancellationHandler {
            while !disposed, terminal == nil {
                let raw = try await channel.receive()
                try Task.checkCancellation()
                guard !disposed else { return }
                let data: Data
                switch raw {
                case let .data(bytes): data = bytes
                case let .string(text): data = Data(text.utf8)
                @unknown default: continue
                }
                guard let envelope = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let type = envelope["type"] as? String else { throw APIError.invalidResponse }
                if type == "resume_failed" {
                    _ = try await reload()
                } else {
                    receive(type, payload: envelope["payload"] as? [String: Any] ?? [:])
                }
            }
        } onCancel: {
            channel.cancel(with: .goingAway, reason: nil)
        }
    }

    func receive(_ type: String, payload p: [String: Any]) {
        guard !disposed, terminal == nil else { return }
        let messageID = p["messageId"] as? String
        switch type {
        case "connection_ack":
            if let session = p["sessionId"] as? String, UUID(uuidString: session) != id {
                socket?.cancel(with: .policyViolation, reason: nil)
                return
            }
            connection = .ready
            error = nil
            if paused { control("pause_recording") }
            if critical { watchForTerminal() }
        case "ai_response_start":
            waiting = false
            responding = true
            noSpeech = false
            stopPlayback()
            messages.append(Message(id: messageID ?? UUID().uuidString, role: "assistant", text: ""))
        case "ai_response_chunk":
            guard let index = messages.lastIndex(where: { $0.id == messageID }) else { return }
            messages[index].text += p["text"] as? String ?? ""
            if p["ttsFailed"] as? Bool == true { messages[index].ttsFailed = true }
            if let chunk = p["audioB64"] as? String, !chunk.isEmpty {
                messages[index].audio.append(chunk)
                if !ttsMuted && !critical {
                    playing = true
                    updateMic()
                    audio.enqueue(chunk, speed: speed)
                }
            }
        case "ai_response_end":
            if let index = messages.lastIndex(where: { $0.id == messageID }),
               let full = p["fullText"] as? String, !full.isEmpty { messages[index].text = full }
            responding = false
            waitForPlayback()
        case "stt_final":
            let text = (p["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            noSpeech = text.isEmpty && !paused
            waiting = !text.isEmpty
            if !text.isEmpty { messages.append(Message(id: messageID ?? UUID().uuidString, role: "patient", text: text)) }
        case "red_flag_alert":
            let flag = Flag(id: p["alertId"] as? String ?? UUID().uuidString,
                            severity: p["severity"] as? String ?? "medium",
                            title: p["title"] as? String ?? "", notice: p["patientNotice"] as? String)
            flags.removeAll { $0.id == flag.id }
            flags.append(flag)
            sortFlags()
            if flag.severity == "critical" {
                critical = true
                stopPlayback()
                watchForTerminal()
            }
        case "supervisor_guidance":
            degraded = false
            focus = (p["nextFocus"] ?? p["next_focus"]) as? String ?? ""
            missingHPI = (p["missingHpi"] ?? p["missing_hpi"]) as? [String] ?? []
        case "supervisor_degraded":
            degraded = true
        case "session_status":
            if let status = p["status"] as? String {
                if status == "failed" {
                    connection = .interrupted
                    error = language.text("conversation.error.sessionInterrupted")
                    resetConnection()
                } else { _ = setTerminal(status) }
            }
        case "error":
            responding = false
            waiting = false
            endWatch?.cancel()
            ending = false
            error = p["code"].flatMap { $0 as? String }.map {
                language.text("ws.\($0)", args: (p["params"] as? [String: Any] ?? [:]).mapValues { String(describing: $0) })
            } ?? language.text("conversation.error.aiUnavailable")
            stopPlayback()
            if critical { watchForTerminal() }
        default: break
        }
        updateMic()
    }

    private func rank(_ severity: String) -> Int {
        switch severity { case "critical": 3; case "high": 2; default: 1 }
    }

    @discardableResult
    private func setTerminal(_ status: String) -> Bool {
        guard ["completed", "aborted_red_flag", "cancelled"].contains(status) else { return false }
        terminal = status
        connection = .ended
        resetConnection()
        audio.close()
        return true
    }

    func clearSpeechHint() { noSpeech = false }

    func acknowledge(_ id: String) {
        if let index = flags.firstIndex(where: { $0.id == id }) {
            flags[index].acknowledged = true
            sortFlags()
        }
    }

    private func sortFlags() {
        flags.sort { lhs, rhs in
            if lhs.acknowledged != rhs.acknowledged { return !lhs.acknowledged }
            return rank(lhs.severity) > rank(rhs.severity)
        }
    }

    private func emit(_ type: String, _ payload: [String: Any]) {
        guard let outgoing, connection == .ready else { return }
        let frame: [String: Any] = ["type": type, "id": UUID().uuidString,
                                    "timestamp": Date().ISO8601Format(), "payload": payload]
        if let data = try? JSONSerialization.data(withJSONObject: frame) {
            outgoing.yield(String(decoding: data, as: UTF8.self))
        }
    }

    private func control(_ action: String) { emit("control", ["action": action]) }

    func sendText(_ input: String) -> Bool {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.count <= 2000 else { return false }
        guard canInput else { error = language.text("conversation.input.sendOffline"); return false }
        error = nil
        noSpeech = false
        waiting = true
        messages.append(Message(id: UUID().uuidString, role: "patient", text: text))
        emit("text_message", ["text": text])
        updateMic()
        return true
    }

    private func sendAudio(_ data: Data) {
        guard canInput, !data.isEmpty else { return }
        noSpeech = false
        waiting = true
        // Connection metadata advertises a 32 KiB chunk size; the backend joins before STT.
        let stride = 24 * 1024
        var index = 0
        for start in Swift.stride(from: 0, to: data.count, by: stride) {
            let end = min(start + stride, data.count)
            let payload: [String: Any] = ["audioData": data[start..<end].base64EncodedString(),
                                          "chunkIndex": index, "isFinal": end == data.count]
            emit("audio_chunk", payload)
            index += 1
        }
        updateMic()
    }

    func togglePause() {
        guard canInput else { return }
        if !paused { audio.finishUtterance() }
        paused.toggle()
        updateMic()
        control(paused ? "pause_recording" : "resume_recording")
    }

    func replay(_ message: Message) {
        guard canInput, !message.audio.isEmpty else { return }
        stopPlayback()
        playing = true
        updateMic()
        for chunk in message.audio { audio.enqueue(chunk, speed: speed) }
        waitForPlayback()
    }

    private func waitForPlayback() {
        let generation = playbackGeneration
        audio.afterPlayback { [weak self] in
            guard let self, generation == playbackGeneration, !disposed else { return }
            playing = false
            updateMic()
        }
    }

    private func stopPlayback() {
        playbackGeneration += 1
        playing = false
        audio.stopPlayback()
    }

    private func updateMic() {
        audio.setListening(allowsListening)
    }

    func end() {
        guard canInput else { error = language.text("conversation.error.endSessionOffline"); return }
        audio.finishUtterance()
        ending = true
        updateMic()
        control("end_session")
        watchForTerminal()
    }

    private func watchForTerminal() {
        endWatch?.cancel()
        endWatch = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(12)) } catch { return }
            guard let self, !disposed, terminal == nil else { return }
            let latest = try? await source.kioskSnapshot(for: id, language: language)
            guard !Task.isCancelled, !disposed, terminal == nil else { return }
            if let status = latest?.status, setTerminal(status) { return }
            if critical {
                // A critical alert forbids another patient turn, even if the terminal ACK was lost.
                socket?.cancel(with: .goingAway, reason: nil)
            } else {
                ending = false
                error = language.text("conversation.error.endSessionTimeout")
                updateMic()
            }
        }
    }

    private func resetConnection() {
        outgoing?.finish()
        outgoing = nil
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        endWatch?.cancel()
        ending = false
        responding = false
        waiting = false
        stopPlayback()
        updateMic()
    }

    func close() {
        disposed = true
        connection = .ended
        resetConnection()
        audio.close()
        messages.removeAll()
        flags.removeAll()
        focus = ""
        missingHPI.removeAll()
        paused = false
        critical = false
        degraded = false
        noSpeech = false
        error = nil
        terminal = nil
    }
}
