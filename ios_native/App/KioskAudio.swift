import AVFoundation
import Observation

enum KioskMicUnavailable: Error {
    case noInputDevice, permissionDenied, failed
}

// VAD measures samples after resampling. Device frame sizes and callback latency can vary.
struct KioskSpeechSegment {
    static let sampleRate = 16_000
    private var preRoll: [Int16] = []
    private var samples: [Int16] = []
    private(set) var speakingSamples = 0
    private var aboveThreshold = 0
    private var trailingSilence = 0

    var isSpeaking: Bool { !samples.isEmpty }

    mutating func append(_ frame: [Int16]) -> Data? {
        guard !frame.isEmpty else { return nil }
        let power = frame.reduce(0.0) { sum, sample in
            let amplitude = Double(sample) / 32768
            return sum + amplitude * amplitude
        }
        let voiced = power > Double(frame.count) * 0.035 * 0.035
        if !isSpeaking {
            preRoll.append(contentsOf: frame)
            if preRoll.count > 6400 { preRoll.removeFirst(preRoll.count - 6400) }
            aboveThreshold = voiced ? aboveThreshold + frame.count : 0
            guard aboveThreshold >= 1440 else { return nil } // 90 ms speech, including onset
            samples = preRoll
            preRoll.removeAll()
        } else {
            samples.append(contentsOf: frame)
        }
        speakingSamples += frame.count
        trailingSilence = voiced ? 0 : trailingSilence + frame.count
        return trailingSilence >= 2 * Self.sampleRate || speakingSamples >= 60 * Self.sampleRate ? finish() : nil
    }

    mutating func finish() -> Data? {
        defer { self = Self() }
        guard !samples.isEmpty else { return nil }
        var wav = Data("RIFF".utf8)
        func write<T: FixedWidthInteger>(_ value: T) {
            withUnsafeBytes(of: value.littleEndian) { wav.append(contentsOf: $0) }
        }
        let bytes = UInt32(samples.count * 2)
        write(36 + bytes)
        wav.append(contentsOf: "WAVEfmt ".utf8)
        write(UInt32(16))
        write(UInt16(1))
        write(UInt16(1))
        write(UInt32(Self.sampleRate))
        write(UInt32(Self.sampleRate * 2))
        write(UInt16(2))
        write(UInt16(16))
        wav.append(contentsOf: "data".utf8)
        write(bytes)
        samples.withUnsafeBytes { wav.append(contentsOf: $0) } // PCM16LE on iOS
        return wav
    }
}

@MainActor @Observable
final class KioskAudio: NSObject, AVAudioPlayerDelegate {
    private(set) var unavailable: KioskMicUnavailable?
    private(set) var isSpeaking = false
    private(set) var elapsedSeconds = 0
    private(set) var waveform: [Double] = []

    var onUtterance: ((Data) -> Void)?
    private let session = AVAudioSession.sharedInstance()
    private var engine: AVAudioEngine?
    private var requestedListening = false
    private var closed = false
    private var opening = false
    private var sessionActive = false
    private var listenFrom: UInt64?
    private var lastFrame: UInt64?
    private var inputWatch: Task<Void, Never>?
    @ObservationIgnored private var segment = KioskSpeechSegment()
    private var lastWaveform: UInt64 = 0

    private var player: AVAudioPlayer?
    private var sentences: [(data: Data, speed: Double)] = []
    private var playbackTails: [() -> Void] = []
    private var playbackTimeout: Task<Void, Never>?

    func openMic() async {
        guard !closed, !opening, engine == nil else { return }
        opening = true
        defer { opening = false }
        let allowed = await AVAudioApplication.requestRecordPermission()
        guard !closed, !Task.isCancelled else { return }
        guard allowed else { unavailable = .permissionDenied; return }
        do {
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker])
            try session.setActive(true)
            sessionActive = true
            let engine = AVAudioEngine()
            let input = engine.inputNode
            // On a mic-less simulator route/permission can look valid while this format is 0 Hz / 0 ch.
            let hardware = input.inputFormat(forBus: 0)
            let format = input.outputFormat(forBus: 0)
            guard Self.usable(hardware), Self.usable(format) else { throw KioskMicUnavailable.noInputDevice }
            guard let mono = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: false),
                  let converter = AVAudioConverter(from: format, to: mono) else { throw KioskMicUnavailable.failed }
            input.installTap(onBus: 0, bufferSize: 1024, format: format, block: Self.tap(converter) { [weak self] frame, time in
                Task { @MainActor in self?.receive(frame, at: time) }
            })
            self.engine = engine
            unavailable = nil
            updateCapture()
        } catch {
            unavailable = (error as? KioskMicUnavailable) ?? .failed
        }
    }

    private static func usable(_ format: AVAudioFormat) -> Bool {
        format.sampleRate > 0 && format.channelCount > 0
    }

    // AVAudioEngine invokes this block on its audio thread. Only owned PCM samples cross to the UI.
    private nonisolated static func tap(
        _ converter: AVAudioConverter, deliver: @escaping @Sendable ([Int16], UInt64) -> Void
    ) -> AVAudioNodeTapBlock {
        { buffer, when in
            let rate = converter.outputFormat.sampleRate / buffer.format.sampleRate
            let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * rate)) + 32
            guard let output = AVAudioPCMBuffer(pcmFormat: converter.outputFormat, frameCapacity: capacity) else { return }
            var supplied = false
            var error: NSError?
            let result = converter.convert(to: output, error: &error) { _, status in
                if supplied { status.pointee = .noDataNow; return nil }
                supplied = true
                status.pointee = .haveData
                return buffer
            }
            guard result != .error, output.frameLength > 0, let pointer = output.int16ChannelData?[0] else { return }
            deliver(Array(UnsafeBufferPointer(start: pointer, count: Int(output.frameLength))), when.hostTime)
        }
    }

    func setListening(_ enabled: Bool) {
        requestedListening = enabled
        updateCapture()
    }

    private func updateCapture() {
        guard let engine else { return }
        guard !closed, requestedListening, player == nil, sentences.isEmpty else {
            if listenFrom != nil { engine.pause() }
            resetCapture()
            return
        }
        guard listenFrom == nil else { return }
        do {
            listenFrom = mach_absolute_time()
            try engine.start()
            inputWatch = Task { [weak self] in
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .seconds(2)) } catch { return }
                    guard let self, let last = self.lastFrame ?? self.listenFrom else { return }
                    if AVAudioTime.seconds(forHostTime: mach_absolute_time() - last) >= 2 {
                        self.detachInput()
                        self.unavailable = .noInputDevice
                        return
                    }
                }
            }
        } catch {
            detachInput()
            unavailable = .failed
        }
    }

    private func receive(_ frame: [Int16], at time: UInt64) {
        guard let listenFrom, time >= listenFrom else { return }
        lastFrame = mach_absolute_time()
        if let wav = segment.append(frame) {
            publish(wav)
            return
        }
        isSpeaking = segment.isSpeaking
        elapsedSeconds = segment.speakingSamples / KioskSpeechSegment.sampleRate
        if time > lastWaveform, AVAudioTime.seconds(forHostTime: time - lastWaveform) >= 0.05 {
            lastWaveform = time
            let count = max(1, (frame.count + 31) / 32)
            waveform = stride(from: 0, to: frame.count, by: count).map { start in
                let peak = frame[start..<min(start + count, frame.count)].map { abs(Int($0)) }.max() ?? 0
                return Double(peak) / 32768
            }
        }
    }

    func finishUtterance() {
        if let wav = segment.finish() { publish(wav) }
    }

    private func publish(_ wav: Data) {
        setListening(false)
        onUtterance?(wav)
    }

    private func resetCapture() {
        listenFrom = nil
        lastFrame = nil
        inputWatch?.cancel()
        inputWatch = nil
        segment = KioskSpeechSegment()
        isSpeaking = false
        elapsedSeconds = 0
        waveform = []
    }

    private func detachInput() {
        engine?.stop()
        engine?.inputNode.removeTap(onBus: 0)
        engine = nil
        resetCapture()
    }

    func enqueue(_ base64: String, speed: Double) {
        guard !closed, let data = Data(base64Encoded: base64), !data.isEmpty else { return }
        sentences.append((data, speed))
        updateCapture()
        advancePlayback()
    }

    func afterPlayback(_ onEnded: @escaping () -> Void) {
        if player == nil && sentences.isEmpty { onEnded() } else { playbackTails.append(onEnded) }
    }

    func stopPlayback() {
        playbackTimeout?.cancel()
        playbackTimeout = nil
        player?.stop()
        player = nil
        sentences.removeAll()
        releasePlayback()
    }

    private func advancePlayback() {
        guard player == nil else { return }
        while !sentences.isEmpty {
            let (data, speed) = sentences.removeFirst()
            do {
                if !sessionActive {
                    try session.setCategory(.playback, mode: .spokenAudio)
                    try session.setActive(true)
                    sessionActive = true
                }
                let next = try AVAudioPlayer(data: data)
                next.enableRate = true
                next.rate = Float(min(1.5, max(0.5, speed)))
                next.delegate = self
                guard next.play() else { continue }
                player = next
                // An interrupted AVAudioPlayer may never send audioPlayerDidFinishPlaying.
                let deadline = next.duration / Double(next.rate) + 2
                let id = ObjectIdentifier(next)
                playbackTimeout = Task { [weak self] in
                    do { try await Task.sleep(for: .seconds(deadline)) } catch { return }
                    self?.finishedPlayer(id)
                }
                return
            } catch { continue } // Transcript remains available when an audio chunk cannot play.
        }
        releasePlayback()
    }

    private func releasePlayback() {
        let tails = playbackTails
        playbackTails.removeAll()
        tails.forEach { $0() }
        updateCapture()
    }

    private func finishedPlayer(_ id: ObjectIdentifier) {
        guard let player, ObjectIdentifier(player) == id else { return }
        playbackTimeout?.cancel()
        playbackTimeout = nil
        player.stop()
        self.player = nil
        advancePlayback()
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        let id = ObjectIdentifier(player)
        Task { @MainActor in self.finishedPlayer(id) }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        let id = ObjectIdentifier(player)
        Task { @MainActor in self.finishedPlayer(id) }
    }

    func close() {
        guard !closed else { return }
        closed = true
        onUtterance = nil
        detachInput()
        stopPlayback()
        if sessionActive { try? session.setActive(false, options: [.notifyOthersOnDeactivation]) }
        sessionActive = false
    }
}
