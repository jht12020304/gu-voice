// =============================================================================
// 對話逐字稿面板 — 問診對話完整呈現
// 設計參考：Stripe (60%) + Intercom (25%) + Sentry (15%) 設計系統融合
// =============================================================================

import { useState } from 'react';
import type { Conversation } from '../../types';

interface TranscriptPanelProps {
  conversations: Conversation[];
  isLoading?: boolean;
}

const roleConfig: Record<string, { label: string; color: string; bg: string; align: 'left' | 'right' | 'center' }> = {
  patient:   { label: '病患', color: 'text-primary-700 dark:text-primary-300', bg: 'bg-primary-50 border-primary-100 dark:bg-primary-950/40 dark:border-primary-800', align: 'right' },
  assistant: { label: 'AI 助手', color: 'text-amber-700 dark:text-amber-300', bg: 'bg-amber-50/60 border-amber-100 dark:bg-amber-950/30 dark:border-amber-800', align: 'left' },
  system:    { label: '系統', color: 'text-ink-muted', bg: 'bg-surface-tertiary border-edge dark:bg-dark-border/50 dark:border-dark-border', align: 'center' },
};

function formatTime(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    return d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
}

export default function TranscriptPanel({ conversations, isLoading }: TranscriptPanelProps) {
  const [expanded, setExpanded] = useState(false);

  if (isLoading) {
    return (
      <div className="card p-0 overflow-hidden">
        <div className="px-5 py-4 flex items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-tertiary dark:bg-dark-border">
            <svg className="h-4 w-4 text-ink-muted animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </span>
          <span className="text-body text-ink-muted">載入對話記錄...</span>
        </div>
      </div>
    );
  }

  if (!conversations || conversations.length === 0) return null;

  const sorted = [...conversations].sort((a, b) => a.sequenceNumber - b.sequenceNumber);
  const preview = sorted.slice(0, 4);
  const hasMore = sorted.length > 4;

  return (
    <div className="card p-0 overflow-hidden">
      {/* Header */}
      <button
        className="flex w-full items-center justify-between px-5 py-4 hover:bg-surface-secondary/50 transition-colors dark:hover:bg-dark-surface/50"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-tertiary text-ink-muted dark:bg-dark-border">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
          </span>
          <div className="text-left">
            <h3 className="text-h3 font-semibold text-ink-heading dark:text-white">
              問診對話逐字稿
            </h3>
            <p className="text-tiny text-ink-muted">{sorted.length} 則對話</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-pill bg-surface-tertiary px-2.5 py-0.5 text-tiny text-ink-muted dark:bg-dark-border">
            {sorted.filter(c => c.role === 'patient').length} 則病患 / {sorted.filter(c => c.role === 'assistant').length} 則 AI
          </span>
          <svg
            className={`h-5 w-5 text-ink-placeholder transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Preview (always visible when collapsed) */}
      {!expanded && (
        <div className="border-t border-edge px-5 py-4 dark:border-dark-border">
          <div className="space-y-3">
            {preview.map((msg) => (
              <MessageBubble key={msg.id} message={msg} compact />
            ))}
            {hasMore && (
              <button
                onClick={() => setExpanded(true)}
                className="text-small font-medium text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 transition-colors"
              >
                查看完整對話 ({sorted.length - 4} 則更多)...
              </button>
            )}
          </div>
        </div>
      )}

      {/* Full transcript */}
      {expanded && (
        <div className="border-t border-edge dark:border-dark-border">
          <div className="max-h-[600px] overflow-y-auto px-5 py-4">
            <div className="space-y-3">
              {sorted.map((msg) => (
                <MessageBubble key={msg.id} message={msg} />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── 訊息氣泡元件 ──

function MessageBubble({ message, compact = false }: { message: Conversation; compact?: boolean }) {
  const cfg = roleConfig[message.role] || roleConfig.system;

  if (message.role === 'system') {
    return (
      <div className="flex justify-center">
        <div className={`rounded-card border px-3 py-1.5 text-center text-small ${cfg.bg} ${cfg.color}`}>
          {message.contentText}
        </div>
      </div>
    );
  }

  const isPatient = message.role === 'patient';

  return (
    <div className={`flex gap-3 ${isPatient ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-tiny font-semibold ${
        isPatient
          ? 'bg-primary-100 text-primary-700 dark:bg-primary-900 dark:text-primary-300'
          : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
      }`}>
        {isPatient ? 'P' : 'AI'}
      </div>

      {/* Bubble */}
      <div className={`max-w-[75%] ${isPatient ? 'text-right' : ''}`}>
        <div className="flex items-center gap-2 mb-0.5">
          {!isPatient && <span className={`text-tiny font-medium ${cfg.color}`}>{cfg.label}</span>}
          <span className="text-tiny text-ink-placeholder font-data">{formatTime(message.createdAt)}</span>
          {isPatient && <span className={`text-tiny font-medium ${cfg.color}`}>{cfg.label}</span>}
        </div>
        <div className={`inline-block rounded-card border px-3 py-2 text-left ${cfg.bg}`}>
          <p className={`text-body text-ink-body dark:text-white/90 ${compact ? 'line-clamp-2' : ''}`}>
            {message.contentText}
          </p>
        </div>
        {message.sttConfidence !== undefined && message.sttConfidence < 0.8 && (
          <p className="mt-0.5 text-tiny text-ink-placeholder">
            STT 信心: {Math.round(message.sttConfidence * 100)}%
          </p>
        )}
      </div>
    </div>
  );
}
