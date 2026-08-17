import AVFoundation
import Flutter

/// 回報「這台 iOS 機器上真的錄得到音嗎」。
///
/// 為什麼非得寫原生：宿主機沒有任何音訊輸入裝置時，iOS Simulator 對**每一個**
/// 便宜的訊號都回報一支幽靈麥克風。2026-08-17 在無麥克風的 Mac mini 上逐一實測
/// （iPhone 17 simulator、麥克風權限已授予）：
///
///   record.listInputDevices()          → 1 [MicrophoneBuiltIn]
///   AVAudioSession.availableInputs     → 1 [builtInMic]
///   AVAudioSession.currentRoute.inputs → 1 [builtInMic]
///   audio_session getDevices(inputs)   → 1 [builtInMic]
///   AVAudioSession.isInputAvailable    → true
///   AVAudioSession.inputNumberOfChannels → 1
///   AVAudioSession.sampleRate          → 48000
///   ── 以上全部說「有麥克風」，全部都是假的 ──
///   AVAudioEngine.inputNode.inputFormat(forBus: 0) → 0 Hz / 0 ch  ← 唯一的真話
///
/// 而 record 的 `RecorderStreamDelegate.start` 正是拿最後那個 format 去
/// `installTap(onBus:bufferSize:format:)`，`IsFormatSampleRateAndChannelCountValid`
/// 為 false 時 AVFoundation 直接拋 NSException → SIGABRT，Dart 的 try/catch 攔不到，
/// 整個 app 死掉（缺陷 A，重現 6/6）。所以這裡只讀那個 format——判準與原生的實際
/// 前置條件一字不差，而且刻意**不**混入上面那些會說謊的 session 屬性（它們在這台
/// 機器上是偽陽性，加進來只會多出偽陰性的機會）。
///
/// 只讀不改 audio session：呼叫端（`AudioStreamService.openMic`）保證此時 session
/// 已經是 playAndRecord 且啟用。不裝 tap、不 start，所以沒有錄音行為。
enum MicProbe {
  static let channelName = "gu_voice/mic_probe"

  static func register(with messenger: FlutterBinaryMessenger) {
    let channel = FlutterMethodChannel(name: channelName, binaryMessenger: messenger)
    channel.setMethodCallHandler { call, result in
      guard call.method == "hasUsableInput" else {
        result(FlutterMethodNotImplemented)
        return
      }
      result(hasUsableInput())
    }
  }

  private static func hasUsableInput() -> Bool {
    // ⚠️ engine 必須用 withExtendedLifetime 撐住：`AVAudioEngine().inputNode` 那種
    // 一行寫法會讓 engine 在取到 node 之後立刻被 ARC 釋放，而 node 對 engine 是
    // 非持有的反向參考，接著 `inputFormat(forBus:)` 就 EXC_BAD_ACCESS
    // （2026-08-17 實測，AVAudioIONodeImpl::AUI() 段錯誤——修復本身變成新的崩潰）。
    let engine = AVAudioEngine()
    return withExtendedLifetime(engine) { () -> Bool in
      let format = engine.inputNode.inputFormat(forBus: 0)
      return format.sampleRate > 0 && format.channelCount > 0
    }
  }
}
