import AVFoundation
import XCTest
@testable import GUVoice

final class KioskAudioTests: XCTestCase {
    func testSpeechRequiresSustainedOnsetAndTwoSecondsOfSilence() throws {
        let frame = [Int16](repeating: 4000, count: 160)
        let silence = [Int16](repeating: 0, count: 160)
        var vad = KioskSpeechSegment()
        for _ in 0..<80 { XCTAssertNil(vad.append(silence)) }
        for _ in 0..<8 { XCTAssertNil(vad.append(frame)) }
        XCTAssertFalse(vad.isSpeaking)
        XCTAssertNil(vad.append(frame))
        XCTAssertTrue(vad.isSpeaking)
        for _ in 0..<199 { XCTAssertNil(vad.append(silence)) }
        let wav = try XCTUnwrap(vad.append(silence))
        XCTAssertFalse(vad.isSpeaking)
        XCTAssertEqual(String(decoding: wav[0..<4], as: UTF8.self), "RIFF")
        XCTAssertEqual(String(decoding: wav[8..<16], as: UTF8.self), "WAVEfmt ")
        XCTAssertEqual(Array(wav[22..<28]), [1, 0, 0x80, 0x3e, 0, 0]) // 16kHz mono
        XCTAssertEqual(wav.count, 44 + (6400 + 32_000) * 2)
        XCTAssertEqual(wav[44], 0)
        XCTAssertEqual(Array(wav[(44 + (6400 - 9 * 160) * 2)..<(46 + (6400 - 9 * 160) * 2)]), [0xa0, 0x0f])
        XCTAssertNil(vad.finish())
    }

    func testDoneSpeakingFlushesExactlyOnceAndNextRecordingHasNoPreviousPCM() throws {
        var vad = KioskSpeechSegment()
        XCTAssertNil(vad.append(Array(repeating: 4000, count: 1600)))
        let first = try XCTUnwrap(vad.finish())
        XCTAssertEqual(first.count, 44 + 3200)
        XCTAssertNil(vad.finish())
        XCTAssertNil(vad.append(Array(repeating: -5000, count: 1600)))
        let next = try XCTUnwrap(vad.finish())
        XCTAssertEqual(Array(next.dropFirst(44).prefix(2)), [0x78, 0xec])
        XCTAssertEqual(next.count, first.count)
    }

    func testNoiseUnderThresholdAndBriefTransientNeverStartAnUtterance() {
        var vad = KioskSpeechSegment()
        for _ in 0..<10 {
            XCTAssertNil(vad.append(Array(repeating: 1100, count: 8000)))
            XCTAssertNil(vad.append(Array(repeating: 5000, count: 400)))
            XCTAssertFalse(vad.isSpeaking)
        }
        XCTAssertNil(vad.finish())
    }

    @MainActor
    func testInvalidPlaybackReleasesTurnAndDisposedAudioDropsPatientCallbacks() {
        let audio = KioskAudio()
        var completions = 0
        audio.enqueue("invalid base64!", speed: 1)
        audio.afterPlayback { completions += 1 }
        XCTAssertEqual(completions, 1)
        audio.onUtterance = { _ in XCTFail("Disposed audio must not emit audio") }
        audio.close()
        audio.close()
        XCTAssertNil(audio.onUtterance)
        XCTAssertFalse(audio.isSpeaking)
        XCTAssertEqual(audio.waveform, [])
    }

    @MainActor
    func testNewDeviceRecoversMissingMicAndOnlyCurrentEngineCanReplaceItsTap() async throws {
        var inputs: [TestInput] = []
        var attempts = 0
        let audio = KioskAudio(requestPermission: { true }, inputFactory: { frame in
            attempts += 1
            guard attempts > 1 else { throw KioskMicUnavailable.noInputDevice }
            let input = TestInput(frame)
            inputs.append(input)
            return input
        })
        defer { audio.close() }
        audio.setListening(true)
        await audio.openMic()
        XCTAssertEqual(audio.unavailable, .noInputDevice)

        postRouteChange()
        await settle()
        let silent = try XCTUnwrap(inputs.last)
        XCTAssertTrue(silent.running)
        for _ in 0..<60 where audio.unavailable == nil {
            try await Task.sleep(for: .milliseconds(50))
        }
        XCTAssertTrue(silent.detached, "A route that stops delivering frames must become unavailable")
        XCTAssertEqual(audio.unavailable, .noInputDevice)
        postRouteChange()
        await settle()
        let first = try XCTUnwrap(inputs.last)
        XCTAssertTrue(first.running)
        XCTAssertNil(audio.unavailable)

        NotificationCenter.default.post(name: .AVAudioEngineConfigurationChange, object: first)
        await settle()
        let replacement = try XCTUnwrap(inputs.last)
        XCTAssertFalse(first === replacement)
        XCTAssertTrue(replacement.running)
        XCTAssertTrue(first.detached)
        NotificationCenter.default.post(name: .AVAudioEngineConfigurationChange, object: first)
        first.speak()
        await settle()
        XCTAssertFalse(audio.isSpeaking, "Late frames from a detached tap belong to the old route")
        XCTAssertTrue(inputs.last === replacement)
        replacement.speak()
        await settle()
        XCTAssertTrue(audio.isSpeaking)
    }

    @MainActor
    func testInterruptionFlushesCapturedSpeechAndRespectsPauseAfterRecovery() async throws {
        var inputs: [TestInput] = []
        let audio = KioskAudio(requestPermission: { true }, inputFactory: {
            let input = TestInput($0)
            inputs.append(input)
            return input
        })
        defer { audio.close() }
        var utterances = 0
        audio.onUtterance = { _ in utterances += 1 }
        audio.setListening(true)
        await audio.openMic()
        let first = try XCTUnwrap(inputs.first)
        first.speak()
        await settle()
        postInterruption(.began)
        await settle()
        XCTAssertEqual(utterances, 1)
        XCTAssertTrue(first.detached)
        XCTAssertFalse(audio.isSpeaking)
        audio.setListening(false)
        postRouteChange()
        await settle()
        XCTAssertEqual(inputs.count, 1, "A new device cannot override the interruption")
        postInterruption(.ended)
        await settle()
        let replacement = try XCTUnwrap(inputs.last)
        XCTAssertFalse(first === replacement)
        XCTAssertFalse(replacement.running, "Interruption recovery cannot undo manual pause")
        audio.setListening(true)
        XCTAssertTrue(replacement.running)
    }

    @MainActor
    func testTTSKeepsNewRouteMutedAndCloseSuppressesQueuedPlaybackAndDeviceCallbacks() async throws {
        var inputs: [TestInput] = []
        let audio = KioskAudio(requestPermission: { true }, inputFactory: {
            let input = TestInput($0)
            inputs.append(input)
            return input
        })
        defer { audio.close() }
        audio.setListening(true)
        await audio.openMic()
        var voice = KioskSpeechSegment()
        for _ in 0..<20 { _ = voice.append(Array(repeating: 2000, count: 1600)) }
        let wav = try XCTUnwrap(voice.finish())
        audio.enqueue(wav.base64EncodedString(), speed: 1)
        var completions = 0
        audio.afterPlayback { completions += 1 }
        postRouteChange()
        await settle()
        XCTAssertEqual(completions, 0)
        XCTAssertFalse(try XCTUnwrap(inputs.last).running)
        postInterruption(.began)
        await settle()
        XCTAssertEqual(completions, 1, "Stopping playback must release its owner")
        postInterruption(.ended)
        await settle()
        XCTAssertTrue(try XCTUnwrap(inputs.last).running)
        audio.enqueue(wav.base64EncodedString(), speed: 1)
        audio.afterPlayback { XCTFail("A playback tail crossed session disposal") }
        audio.close()
        let countAtClose = inputs.count
        postRouteChange()
        postInterruption(.ended)
        await settle()
        XCTAssertEqual(inputs.count, countAtClose)
        XCTAssertTrue(try XCTUnwrap(inputs.last).detached)
    }

    private func postRouteChange() {
        NotificationCenter.default.post(name: AVAudioSession.routeChangeNotification, object: AVAudioSession.sharedInstance(),
                                        userInfo: [AVAudioSessionRouteChangeReasonKey: AVAudioSession.RouteChangeReason.newDeviceAvailable.rawValue])
    }

    private func postInterruption(_ kind: AVAudioSession.InterruptionType) {
        NotificationCenter.default.post(name: AVAudioSession.interruptionNotification, object: AVAudioSession.sharedInstance(),
                                        userInfo: [AVAudioSessionInterruptionTypeKey: kind.rawValue])
    }

    @MainActor private func settle() async {
        // The observers deliberately leave AVAudioEngine's notification queue before rebuilding it.
        await withCheckedContinuation { continuation in
            DispatchQueue.main.async { continuation.resume() }
        }
    }
}

private final class TestInput: NSObject, KioskMicInput {
    let deliver: KioskAudio.DeliverFrame
    var running = false
    var detached = false
    init(_ deliver: @escaping KioskAudio.DeliverFrame) { self.deliver = deliver }
    func start() throws { running = true }
    func pause() { running = false }
    func detach() { running = false; detached = true }
    func speak() { deliver(Array(repeating: 4000, count: 1600), mach_absolute_time()) }
}
