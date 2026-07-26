import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:just_audio/just_audio.dart';
import 'package:gu_voice/features/voice/services/tts_playback_controller.dart';

// 不變式 #5（stopActiveTTS 中斷播放必須補呼釋放）的回歸測試。
//
// 這裡測的是「誰有權釋放 chain」而不是「有沒有出聲」：一旦被中斷的 step 沒有釋放、
// 或釋放權跑到別的 step 手上，appendTail 的 VAD 解鎖就會在錯的時機（或永遠不）觸發，
// 症狀是麥克風永久卡住。fake player 刻意不會自己完成播放，所以每條測試裡
// chain 前進的唯一途徑就是被測的那條路徑。
void main() {
  // 任意合法 base64；fake player 不解碼，只有 _playStep 的 base64Decode 會碰到。
  const b64 = 'AQIDBA==';

  TtsPlaybackController controllerWith(_FakePlayer player) =>
      TtsPlaybackController(speed: () => 1.0, player: player);

  group('epoch 世代取消', () {
    test('clearQueue 之後，先前 enqueue 的 step 不得播放', () async {
      final player = _FakePlayer();
      final tts = controllerWith(player);

      tts.enqueue(b64); // epoch 0 的句子，還沒輪到它跑
      tts.clearQueue(); // 靜音/barge-in 在它起跑前落地

      await _pump();

      expect(player.sourceCount, 0, reason: '舊世代的句子連載入都不該發生');
      expect(player.playCount, 0);
    });

    test('barge-in：排在後面的句子在 chain 解開後仍不得播放', () async {
      final player = _FakePlayer();
      final tts = controllerWith(player);

      tts.enqueue(b64); // A：開始播放
      await _pump();
      expect(player.playCount, 1);

      tts.enqueue(b64); // B：排在 A 後面
      // 完整重現 _bargeIn()：stopActive() 不 await，緊接著同步 clearQueue()。
      unawaited(tts.stopActive());
      tts.clearQueue();

      await _pump();

      expect(player.playCount, 1,
          reason: 'stopActive 釋放 A 後 chain 會前進到 B，但 B 屬於已取消的世代');
    });
  });

  test('stopActive 必須讓 chain 前進（不變式 #5：中斷的 step 一定要釋放）', () async {
    final player = _FakePlayer();
    final tts = controllerWith(player);
    var released = false;

    tts.enqueue(b64);
    tts.appendTail(tts.epoch, () => released = true);
    await _pump();

    expect(player.playCount, 1);
    expect(player.speeds, [1.0], reason: '播放前套用當下語速（clamp 後）');
    expect(released, isFalse, reason: 'tail 必須等句子播完，不能搶跑');

    // fake 永遠不會自己送出 completed，所以唯一能解開 chain 的就是 stopActive。
    await tts.stopActive();
    await _pump();

    expect(player.stopCount, 1);
    expect(released, isTrue,
        reason: '被中斷的 step 洩漏了 completer → chain 永遠停在原地 → tail 裡的 '
            'VAD 解鎖不會執行 → 麥克風永久卡死');
  });

  test('epoch 已被 bump 的 stale tail 不得觸發 onRelease', () async {
    final player = _FakePlayer();
    final tts = controllerWith(player);
    var staleReleased = false;

    final captured = tts.epoch;
    tts.enqueue(b64);
    tts.appendTail(captured, () => staleReleased = true);
    await _pump();

    tts.clearQueue(); // 新的擁有者接手，舊 tail 就此作廢
    await tts.stopActive(); // 解開 chain，讓那個作廢的 tail 真的跑到
    await _pump();

    expect(staleReleased, isFalse,
        reason: 'stale tail 打穿新擁有者的鎖 → 在新一輪 AI 說話期間解開 VAD');

    // 同時證明機制本身沒壞死：換成當前 epoch 的 tail 照樣會釋放。
    var freshReleased = false;
    tts.appendTail(tts.epoch, () => freshReleased = true);
    await _pump();
    expect(freshReleased, isTrue);
  });

  test('G4：stopActive 完成的是它中斷的那個 step，不是中途接手的新 step', () async {
    final player = _FakePlayer();
    final tts = controllerWith(player);
    var released = false;

    tts.enqueue(b64); // A
    tts.enqueue(b64); // B
    tts.appendTail(tts.epoch, () => released = true);
    await _pump();
    expect(player.playCount, 1, reason: 'A 播放中、B 排隊中');

    // 製造 race：player 在 stopActive 停在 `await stop()` 期間回報 A 已 completed，
    // chain 因此前進，B 在那個空檔成為 _activeStep。
    player.onStop = () async {
      player.emitCompleted();
      await _pump();
    };

    await tts.stopActive();
    await _pump();

    expect(player.playCount, 2, reason: 'B 確實在 await 期間接手了');
    expect(released, isFalse,
        reason: 'stopActive 誤把新 step（B）complete 掉 → B 的 tail 在 B 還在播的時候'
            '就解開 VAD，而且 A 的 completer 一併洩漏');

    // B 仍然是真正的擁有者：只有它自己播完才會放行 tail。
    player.emitCompleted();
    await _pump();
    expect(released, isTrue);
  });
}

// 讓已排定的 microtask/event-loop 工作跑完。每一次 Duration.zero delay 會把當下所有
// pending microtask 抽乾，5 輪對「A 完成 → sub.cancel → chain 前進 → B 起跑」綽綽有餘。
Future<void> _pump([int turns = 5]) async {
  for (var i = 0; i < turns; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

class _FakePlayer implements TtsAudioPlayer {
  // broadcast：每個 _playStep 都會開一條新的 listen，播完就 cancel。
  final _states = StreamController<PlayerState>.broadcast();

  int sourceCount = 0;
  int playCount = 0;
  int stopCount = 0;
  final List<double> speeds = [];

  // 給測試插隊用：在 stop() 的 future 解決「之前」執行，用來重現 G4 的空檔。
  Future<void> Function()? onStop;

  void emitCompleted() =>
      _states.add(PlayerState(false, ProcessingState.completed));

  @override
  Stream<PlayerState> get playerStateStream => _states.stream;

  @override
  Future<void> setAudioSource(AudioSource source) async {
    sourceCount++;
  }

  @override
  Future<void> setSpeed(double speed) async {
    speeds.add(speed);
  }

  @override
  Future<void> play() async {
    playCount++;
  }

  @override
  Future<void> stop() async {
    stopCount++;
    await onStop?.call();
  }

  @override
  Future<void> dispose() async {
    await _states.close();
  }
}
