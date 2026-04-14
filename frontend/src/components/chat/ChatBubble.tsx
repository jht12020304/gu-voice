// =============================================================================
// 對話氣泡元件 — Intercom 暖色調 + 清晰說話者區分
// 病患: 藍色 (右側) / AI 助手: 暖橙 (左側) / 系統: 中性灰 (置中)
// =============================================================================

import { useTranslation } from 'react-i18next';
import { relativeTime } from '../../utils/date';

interface ChatBubbleProps {
  message: {
    id: string;
    content: string;
    sender: 'patient' | 'assistant' | 'system';
    timestamp: string;
    isStreaming?: boolean;
    sttConfidence?: number;
    /** Fix 16：該則訊息至少有一句 TTS 失敗 */
    hasTtsFailure?: boolean;
    /** Fix 18：是否已快取可重播的 TTS 音訊 */
    canReplay?: boolean;
  };
  showTimestamp?: boolean;
  /** Fix 18：使用者點擊 AI 氣泡觸發重播 */
  onReplay?: (messageId: string) => void;
}

export default function ChatBubble({ message, showTimestamp = true, onReplay }: ChatBubbleProps) {
  const { t } = useTranslation(['conversation', 'common']);
  const { content, sender, timestamp, isStreaming, sttConfidence, hasTtsFailure, canReplay } = message;

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
  const isAssistant = sender === 'assistant';
  const replayable = isAssistant && !!canReplay && !!onReplay;

  const handleBubbleClick = () => {
    if (replayable) {
      onReplay!(message.id);
    }
  };

  return (
    <div className={`my-3 flex ${isPatient ? 'justify-end' : 'justify-start'}`}>
      {/* AI 頭像 */}
      {!isPatient && (
        <div className="mr-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-chat-ai-bg dark:bg-orange-950">
          <span className="text-small font-semibold text-chat-ai dark:text-orange-300">AI</span>
        </div>
      )}

      <div className={`max-w-[75%] ${isPatient ? 'items-end' : 'items-start'} flex flex-col`}>
        {/* 角色標籤 */}
        <span className={`mb-1 px-1 text-tiny ${
          isPatient
            ? 'text-ink-secondary dark:text-slate-300 text-right self-end'
            : 'text-chat-ai dark:text-orange-300'
        }`}>
          {isPatient ? t('common:roles.patient') : t('common:roles.assistant')}
        </span>

        {/* 氣泡 */}
        <div
          className={`relative ${isPatient ? 'chat-bubble-patient' : 'chat-bubble-ai'} ${
            replayable ? 'cursor-pointer hover:brightness-95 transition-[filter]' : ''
          }`}
          onClick={handleBubbleClick}
          role={replayable ? 'button' : undefined}
          tabIndex={replayable ? 0 : undefined}
          onKeyDown={(e) => {
            if (replayable && (e.key === 'Enter' || e.key === ' ')) {
              e.preventDefault();
              onReplay!(message.id);
            }
          }}
          aria-label={replayable ? t('conversation:tts.replayAria') : undefined}
          title={replayable ? t('conversation:tts.replayTitle') : undefined}
        >
          <p className="whitespace-pre-wrap text-body leading-relaxed">
            {content}
            {isStreaming && (
              <span className="ml-1 inline-block h-4 w-0.5 animate-pulse bg-current opacity-70 align-text-bottom" />
            )}
          </p>

          {/* Fix 18：重播圖示（右下角，僅 AI 訊息且有快取時顯示） */}
          {replayable && (
            <span
              className="absolute bottom-1 right-1 inline-flex items-center justify-center rounded-full bg-white/60 dark:bg-black/30 px-1 py-0.5 text-tiny text-chat-ai dark:text-orange-300"
              aria-hidden="true"
            >
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.536 8.464a5 5 0 010 7.072M12 6v12l-4-4H5a1 1 0 01-1-1v-2a1 1 0 011-1h3l4-4z" />
              </svg>
            </span>
          )}
        </div>

        {/* Fix 16：TTS 合成失敗的輕量內嵌提示 */}
        {hasTtsFailure && (
          <span
            className="mt-1 inline-flex items-center gap-1 px-1 text-tiny text-ink-secondary dark:text-slate-400"
            aria-label={t('conversation:tts.failed')}
          >
            <span aria-hidden="true">🔇</span>
            {t('conversation:tts.failed')}
          </span>
        )}

        {/* 底部資訊 */}
        <div className="mt-1 flex items-center gap-2 px-1">
          {showTimestamp && (
            <span className="text-tiny text-ink-secondary dark:text-slate-400">
              {relativeTime(timestamp)}
            </span>
          )}
          {isPatient && sttConfidence !== undefined && (
            <span className="text-tiny text-ink-placeholder dark:text-slate-500 font-tnum">
              STT {(sttConfidence * 100).toFixed(0)}%
            </span>
          )}
        </div>
      </div>

      {/* 病患頭像 */}
      {isPatient && (
        <div className="ml-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-100 dark:bg-primary-900">
          <span className="text-small font-semibold text-primary-700 dark:text-primary-200">P</span>
        </div>
      )}
    </div>
  );
}
