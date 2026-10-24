// =============================================================================
// 日期工具函式
// =============================================================================

import i18n from '../i18n';

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

// -----------------------------------------------------------------------------
// 本地日／月工具（CLAUDE.md：依日期分組／篩選一律用**裝置本地日**分桶，不拿後端 UTC 切日）
// -----------------------------------------------------------------------------

const pad2 = (n: number) => `${n}`.padStart(2, '0');

/** 本地日 key `YYYY-MM-DD`；無效日期回 `'unknown'`。 */
export function localDayKey(iso: string | Date): string {
  const d = iso instanceof Date ? iso : new Date(iso);
  if (Number.isNaN(d.getTime())) return 'unknown';
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/** 日分組標題（年月日＋星期）；locale 省略時跟隨目前 i18n 語系。 */
export function dayLabel(iso: string | Date, locale?: string): string {
  const d = iso instanceof Date ? iso : new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return new Intl.DateTimeFormat(locale || i18n.resolvedLanguage || i18n.language || 'zh-TW', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  }).format(d);
}

/** 本地月 key `YYYY-MM`。 */
export function monthKey(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

/** `YYYY-MM` → 本地月首 00:00:00.000 與月末 23:59:59.999（Date；`.toISOString()` 後自帶時區位移）。 */
export function localMonthRange(yyyyMm: string): { start: Date; end: Date } {
  const [y, m] = yyyyMm.split('-').map(Number);
  return { start: new Date(y, m - 1, 1, 0, 0, 0, 0), end: new Date(y, m, 0, 23, 59, 59, 999) };
}

/** `YYYY-MM-DD` → 本地日界（裸日期字串會被後端 `datetime.fromisoformat` 當成 UTC）。 */
export function localDayBounds(yyyyMmDd: string): { start: Date; end: Date } {
  const [y, m, d] = yyyyMmDd.split('-').map(Number);
  return { start: new Date(y, m - 1, d, 0, 0, 0, 0), end: new Date(y, m - 1, d, 23, 59, 59, 999) };
}

/** `YYYY-MM` → `yyyy/MM/dd - yyyy/MM/dd` 資料區間標籤。 */
export function monthRangeLabel(yyyyMm: string): string {
  const { start, end } = localMonthRange(yyyyMm);
  const ymd = (d: Date) => `${d.getFullYear()}/${pad2(d.getMonth() + 1)}/${pad2(d.getDate())}`;
  return `${ymd(start)} - ${ymd(end)}`;
}

/** 加減月份；日號超出目標月時夾到月末（1/31 + 1 → 2/28）。 */
export function addMonths(d: Date, n: number): Date {
  const r = new Date(d.getTime());
  r.setDate(1);
  r.setMonth(r.getMonth() + n);
  r.setDate(Math.min(d.getDate(), new Date(r.getFullYear(), r.getMonth() + 1, 0).getDate()));
  return r;
}
