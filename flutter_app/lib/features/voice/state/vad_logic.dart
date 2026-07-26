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

// payload is the backend snake_case supervisor_guidance WS event.
SupervisorGuidance? normalizeSupervisorGuidance(Map? payload) {
  if (payload == null) return null;
  final missing = payload['missing_hpi'];
  final pct = payload['hpi_completion_percentage'];
  return SupervisorGuidance(
    nextFocus: (payload['next_focus'] as String?) ?? '',
    missingHpi: missing is List ? missing.cast<String>() : const [],
    hpiCompletionPercentage: pct is num ? pct : 0,
    fallback: (payload['fallback'] as bool?) ?? false,
  );
}
