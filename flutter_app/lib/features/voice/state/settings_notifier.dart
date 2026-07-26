import 'package:flutter_riverpod/flutter_riverpod.dart';

// ttsMuted + ttsSpeed live in the settings store (NOT the conversation store) — the
// conversation controller reads them synchronously when deciding the mic-unlock path
// and whether to auto-enqueue TTS.
class VoiceSettings {
  final bool ttsMuted;
  final double ttsSpeed; // cycles 1.0 -> 1.25 -> 1.5

  const VoiceSettings({this.ttsMuted = false, this.ttsSpeed = 1.0});

  VoiceSettings copyWith({bool? ttsMuted, double? ttsSpeed}) =>
      VoiceSettings(ttsMuted: ttsMuted ?? this.ttsMuted, ttsSpeed: ttsSpeed ?? this.ttsSpeed);
}

class SettingsNotifier extends Notifier<VoiceSettings> {
  @override
  VoiceSettings build() => const VoiceSettings();

  void toggleTtsMuted() => state = state.copyWith(ttsMuted: !state.ttsMuted);

  void cycleSpeed() {
    const presets = [1.0, 1.25, 1.5];
    final next = presets[(presets.indexOf(state.ttsSpeed) + 1) % presets.length];
    state = state.copyWith(ttsSpeed: next);
  }
}

final settingsProvider = NotifierProvider<SettingsNotifier, VoiceSettings>(SettingsNotifier.new);
