// =============================================================================
// 對話氣泡元件 — Intercom 暖色調 + 清晰說話者區分
// 病患: 藍色 (右側) / AI 助手: 暖橙 (左側) / 系統: 中性灰 (置中)
// =============================================================================

import { relativeTime } from '../../utils/date';

interface ChatBubbleProps {
  message: {
    id: string;
    content: string;
    sender: 'patient' | 'assistant' | 'system';
    timestamp: string;
    isStreaming?: boolean;
    sttConfidence?: number;
  };
  showTimestamp?: boolean;
}

export default function ChatBubble({ message, showTimestamp = true }: ChatBubbleProps) {
  const { content, sender, timestamp, isStreaming, sttConfidence } = message;

  // 系統訊息：置中，中性色
  if (sender === 'system') {
    return (
      <div className="my-3 flex justify-center">
        <div className="chat-bubble-system">
          {content}
        </div>
      </div>
    );
  }

  const isPatient = sender === 'patient';

  return (
    <div className={`my-3 flex ${isPatient ? 'justify-end' : 'justify-start'}`}>
      {/* AI 頭像 */}
      {!isPatient && (
        <div className="mr-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-chat-ai-bg">
          <span className="text-small font-semibold text-chat-ai">AI</span>
        </div>
      )}

      <div className={`max-w-[75%] ${isPatient ? 'items-end' : 'items-start'} flex flex-col`}>
        {/* 角色標籤 */}
        <span className={`mb-1 px-1 text-tiny ${
          isPatient ? 'text-ink-muted text-right self-end' : 'text-chat-ai'
        }`}>
          {isPatient ? '病患' : 'AI 助手'}
        </span>

        {/* 氣泡 */}
        <div className={isPatient ? 'chat-bubble-patient' : 'chat-bubble-ai'}>
          <p className="whitespace-pre-wrap text-body leading-relaxed">
            {content}
            {isStreaming && (
              <span className="ml-1 inline-block h-4 w-0.5 animate-pulse bg-current opacity-70 align-text-bottom" />
            )}
          </p>
        </div>

        {/* 底部資訊 */}
        <div className="mt-1 flex items-center gap-2 px-1">
          {showTimestamp && (
            <span className="text-tiny text-ink-muted">
              {relativeTime(timestamp)}
            </span>
          )}
          {isPatient && sttConfidence !== undefined && (
            <span className="text-tiny text-ink-placeholder font-tnum">
              STT {(sttConfidence * 100).toFixed(0)}%
            </span>
          )}
        </div>
      </div>

      {/* 病患頭像 */}
      {isPatient && (
        <div className="ml-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-100">
          <span className="text-small font-semibold text-primary-700">P</span>
        </div>
      )}
    </div>
  );
}
