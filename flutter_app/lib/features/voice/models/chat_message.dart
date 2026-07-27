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

/// 病患端紅旗事件。
///
/// ⚠️ 刻意**不含** `description` / `suggestedActions`：那兩個欄位是 LLM 自由生成
/// 的醫師向臨床內容（實測 description 含鑑別診斷與「建議立即急診評估」、
/// suggestedActions 含「立即安排急診評估」），對已坐在候診區的病患既看不懂又
/// 造成恐慌，且違反院內 kiosk 的措辭鐵律。後端自 2026-07-27 起在
/// `conversation_handler._persist_and_emit_alert` 就**根本不送**給病患端；
/// 醫師端（dashboard 廣播）與 DB 仍保留完整內容。
///
/// 型別層不留這兩個欄位＝結構性防線：store 裡沒有值，日後有人在 widget 裡想印
/// 也印不出東西。與 React 的 conversationStore/ConversationPage 行為一致。
class RedFlagEvent {
  final String id;
  final String title;
  final String severity; // 'critical' | 'high' | 'medium'

  /// 後端依「這則紅旗有沒有真的建立醫師通知」二選一的在地化病患指引
  /// （ws.red_flag_patient_notice_notified / _flagged）。
  /// 前端不得自行拼裝這句話——有沒有通知到醫師只有後端知道，前端自己講就會對
  /// 病患說謊。舊後端不送此欄，缺席時 UI 退回保守版的本地 fallback。
  final String? patientNotice;

  bool isAcknowledged;

  RedFlagEvent({
    required this.id,
    required this.title,
    required this.severity,
    this.patientNotice,
    this.isAcknowledged = false,
  });
}
