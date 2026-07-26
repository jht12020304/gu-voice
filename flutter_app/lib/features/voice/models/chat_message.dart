// ChatMessage from conversationStore.ts. ttsAudioChunks caches per-message base64 MP3
// so replay works even while TTS is muted.
class ChatMessage {
  final String id;
  final String sessionId;
  final String sender; // 'patient' | 'assistant' | 'system'
  final String content;
  final String timestamp;
  final double? sttConfidence;
  final bool isStreaming;
  final bool hasTtsFailure;
  final List<String> ttsAudioChunks;

  ChatMessage({
    required this.id,
    required this.sessionId,
    required this.sender,
    required this.content,
    required this.timestamp,
    this.sttConfidence,
    this.isStreaming = false,
    this.hasTtsFailure = false,
    List<String>? ttsAudioChunks,
  }) : ttsAudioChunks = ttsAudioChunks ?? [];

  ChatMessage copyWith({String? content, bool? isStreaming, bool? hasTtsFailure}) => ChatMessage(
        id: id,
        sessionId: sessionId,
        sender: sender,
        content: content ?? this.content,
        timestamp: timestamp,
        sttConfidence: sttConfidence,
        isStreaming: isStreaming ?? this.isStreaming,
        hasTtsFailure: hasTtsFailure ?? this.hasTtsFailure,
        ttsAudioChunks: ttsAudioChunks,
      );
}

class RedFlagEvent {
  final String id;
  final String title;
  final String? description;
  final String severity; // 'critical' | 'high' | 'medium'
  final List<String> suggestedActions;
  bool isAcknowledged;

  RedFlagEvent({
    required this.id,
    required this.title,
    this.description,
    required this.severity,
    List<String>? suggestedActions,
    this.isAcknowledged = false,
  }) : suggestedActions = suggestedActions ?? [];
}
