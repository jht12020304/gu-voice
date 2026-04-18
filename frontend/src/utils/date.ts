// =============================================================================
// 日期工具函式
// =============================================================================

import i18n from '../i18n';

/**
 * 安全解析 ISO 日期字串
 */
export function parseISO(dateStr: string): Date {
  return new Date(dateStr);
}

/**
 * 判斷日期是否為今天
 */
export function isToday(dateStr: string): boolean {
  const date = new Date(dateStr);
  const today = new Date();
  return (
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate()
  );
}

/**
 * 判斷日期是否在本週
 */
export function isThisWeek(dateStr: string): boolean {
  const date = new Date(dateStr);
  const now = new Date();
  const startOfWeek = new Date(now);
  startOfWeek.setDate(now.getDate() - now.getDay());
  startOfWeek.setHours(0, 0, 0, 0);
  const endOfWeek = new Date(startOfWeek);
  endOfWeek.setDate(startOfWeek.getDate() + 7);
  return date >= startOfWeek && date < endOfWeek;
}

/**
 * 相對時間（例如 "3 分鐘前"、"昨天"）
 *
 * i18n-aware：使用 Intl.RelativeTimeFormat 依當前 i18n 語系輸出原生字串，
 * 支援 zh-TW / en-US / ja-JP / ko-KR / vi-VN。numeric: 'auto' 會讓
 * Intl 自動把 "1 day ago" 轉為對應語系的「昨天 / yesterday / 昨日 / 어제 / hôm qua」。
 * 「剛剛 / just now」< 60 秒 不在 Intl 覆蓋範圍，改走 i18n 翻譯 key common:time.justNow。
 */
export function relativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  const lng = i18n.resolvedLanguage || i18n.language || 'zh-TW';

  if (diffSeconds < 60) {
    // i18n.t 在 i18next 尚未初始化時會回傳 key 本身；保留 fallback 避免 UI 露出原始 key
    const justNow = i18n.t('time.justNow', { ns: 'common', defaultValue: 'Just now' });
    return typeof justNow === 'string' ? justNow : 'Just now';
  }

  const rtf = new Intl.RelativeTimeFormat(lng, { numeric: 'auto' });

  if (diffMinutes < 60) return rtf.format(-diffMinutes, 'minute');
  if (diffHours < 24) return rtf.format(-diffHours, 'hour');
  if (diffDays < 7) return rtf.format(-diffDays, 'day');
  if (diffDays < 30) return rtf.format(-Math.floor(diffDays / 7), 'week');
  if (diffDays < 365) return rtf.format(-Math.floor(diffDays / 30), 'month');
  return rtf.format(-Math.floor(diffDays / 365), 'year');
}

/**
 * 格式化為日期部分 YYYY-MM-DD
 */
export function toDateString(dateStr: string): string {
  const d = new Date(dateStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * 格式化為時間部分 HH:MM
 */
export function toTimeString(dateStr: string): string {
  const d = new Date(dateStr);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
