import 'package:audio_session/audio_session.dart';

// (e) Configure the OS audio session so mic capture and TTS playback coexist without
// acoustic echo: playAndRecord + voiceChat mode delegates echo cancellation to the OS
// (iOS AVAudioSession voiceChat / Android AEC), replacing the browser's echoCancellation.
Future<void> configureVoiceAudioSession() async {
  final session = await AudioSession.instance;
  await session.configure(const AudioSessionConfiguration(
    avAudioSessionCategory: AVAudioSessionCategory.playAndRecord,
    avAudioSessionCategoryOptions: AVAudioSessionCategoryOptions.defaultToSpeaker,
    avAudioSessionMode: AVAudioSessionMode.voiceChat,
    androidAudioAttributes: AndroidAudioAttributes(
      contentType: AndroidAudioContentType.speech,
      usage: AndroidAudioUsage.voiceCommunication,
    ),
    androidAudioFocusGainType: AndroidAudioFocusGainType.gain,
  ));
  await session.setActive(true);
}
