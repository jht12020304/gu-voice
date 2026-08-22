// Byte-for-byte port of the VAD auto-resume decision matrix + supervisor-guidance
// normalizer from frontend/src/stores/conversationStore.ts. These are the medical-safety
// kernel: every mute has an owner that unmutes it, manual pause beats every auto-resume,
// and only 'user_resume' clears a manual pause. Pure functions — fully unit-tested.

enum VadResumeTrigger {
  emptyStt, // empty stt_final (Whisper heard nothing)
  aiStartTtsMuted, // AI turn starts while TTS muted (no feedback risk, open mic now)
  aiTtsDone, // voice-mode AI turn finished playing (queue tail)
  replayEnd, // replay of an old message's TTS ended or was aborted
  wsError, // backend error event (rate limit / audio format / STT fail)
  reconnected, // WS reconnected after a drop
  ttsMuteToggle, // user switched to TTS-muted (stop+flush then resume mic)
  userResume, // user tapped "resume recording"
}

class VadResumeContext {
  final bool userPaused;
  final bool aiTurnLocked; // pendingAiUnmuteRef || pendingReplayUnmuteRef
  final bool wsDown;

  const VadResumeContext({
    required this.userPaused,
    required this.aiTurnLocked,
    required this.wsDown,
  });
}

bool shouldUnmuteVAD(VadResumeTrigger trigger, VadResumeContext ctx) {
  // reconnected: the only unlocker of a disconnect-mute; blocked only by manual pause.
  if (trigger == VadResumeTrigger.reconnected) return !ctx.userPaused;
  // user_resume: must not break the AI-speaking hard-lock (feedback invariant); when
  // down, defer to reconnected.
  if (trigger == VadResumeTrigger.userResume) return !ctx.aiTurnLocked && !ctx.wsDown;
  // replay_end: third-party unlock path — yield to a still-running real AI turn, and
  // respect manual pause + disconnect.
  if (trigger == VadResumeTrigger.replayEnd) {
    return !ctx.userPaused && !ctx.aiTurnLocked && !ctx.wsDown;
  }
  // all other auto-resume paths: manual pause wins; when down, defer to reconnected.
  return !ctx.userPaused && !ctx.wsDown;
}

class SupervisorGuidance {
  final String nextFocus;
  final List<String> missingHpi;
  final num hpiCompletionPercentage;
  final bool fallback;

  const SupervisorGuidance({
    required this.nextFocus,
    required this.missingHpi,
    required this.hpiCompletionPercentage,
    required this.fallback,
  });
}

// 2026-08-23 資料鏈路稽核：後端 `_emit_supervisor_guidance` 的 WS payload 是
// **camelCase**（conversation_handler.py `nextFocus/missingHpi/hpiCompletionPercentage`），
// 而 WS 不經過 dio 的 snake→camel 轉換層。舊版只讀 snake_case ＝ 指導橫幅在
// Flutter 上**從未亮過**（#27 類缺陷：兩端手抄清單漂移）。雙形容忍：camel 為主
// （後端現況）、snake 為備（防後端未來改口）。
SupervisorGuidance? normalizeSupervisorGuidance(Map? payload) {
  if (payload == null) return null;
  final missing = payload['missingHpi'] ?? payload['missing_hpi'];
  final pct = payload['hpiCompletionPercentage'] ?? payload['hpi_completion_percentage'];
  return SupervisorGuidance(
    nextFocus: (payload['nextFocus'] ?? payload['next_focus']) as String? ?? '',
    missingHpi: missing is List ? missing.cast<String>() : const [],
    hpiCompletionPercentage: pct is num ? pct : 0,
    fallback: (payload['fallback'] as bool?) ?? false,
  );
}
