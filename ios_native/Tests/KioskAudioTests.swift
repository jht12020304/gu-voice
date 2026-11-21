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
}
