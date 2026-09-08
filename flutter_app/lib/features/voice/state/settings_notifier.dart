import 'package:flutter/material.dart' show ThemeMode;
import 'package:flutter_riverpod/flutter_riverpod.dart';

// ttsMuted + ttsSpeed live in the settings store (NOT the conversation store) — the
// conversation controller reads them synchronously when deciding the mic-unlock path
// and whether to auto-enqueue TTS.
class VoiceSettings {
  final bool ttsMuted;
  final double ttsSpeed; // cycles 1.0 -> 1.25 -> 1.5
  // Doctor-facing preferences (the doctor settings page). In-memory only, like the React
  // version — persisting them needs a real preferences endpoint.
  final ThemeMode themeMode;
  final bool soundAlerts;
  final double textScale;

  const VoiceSettings({
    this.ttsMuted = false,
    this.ttsSpeed = 1.0,
    this.themeMode = ThemeMode.system,
    this.soundAlerts = true,
    this.textScale = 1.0,
  });

  VoiceSettings copyWith({
    bool? ttsMuted,
    double? ttsSpeed,
    ThemeMode? themeMode,
    bool? soundAlerts,
    double? textScale,
  }) => VoiceSettings(
    ttsMuted: ttsMuted ?? this.ttsMuted,
    ttsSpeed: ttsSpeed ?? this.ttsSpeed,
    themeMode: themeMode ?? this.themeMode,
    soundAlerts: soundAlerts ?? this.soundAlerts,
    textScale: textScale ?? this.textScale,
  );
}

class SettingsNotifier extends Notifier<VoiceSettings> {
  @override
  VoiceSettings build() => const VoiceSettings();

  void toggleTtsMuted() => state = state.copyWith(ttsMuted: !state.ttsMuted);

  void setThemeMode(ThemeMode m) => state = state.copyWith(themeMode: m);

  void toggleSoundAlerts() =>
      state = state.copyWith(soundAlerts: !state.soundAlerts);

  void setTextScale(double scale) =>
      state = state.copyWith(textScale: scale.clamp(1.0, 1.4));

  void cycleSpeed() {
    const presets = [1.0, 1.25, 1.5];
    final next =
        presets[(presets.indexOf(state.ttsSpeed) + 1) % presets.length];
    state = state.copyWith(ttsSpeed: next);
  }
}

final settingsProvider = NotifierProvider<SettingsNotifier, VoiceSettings>(
  SettingsNotifier.new,
);
