// =============================================================================
// 格式化工具函式（i18n aware）
// -----------------------------------------------------------------------------
// 這些函式被 hook 外部（utility 層）呼叫，不能依賴 React context。
// 改為透過 i18next singleton 讀取 `resolvedLanguage`（或 `language`）動態餵給
// `Intl.DateTimeFormat` / `Intl.RelativeTimeFormat` / `Intl.NumberFormat`，
// 讓顯示跟隨當前介面語言切換。
//
// 註：signature 維持不變（不新增 lang 參數），呼叫端無須改動。
// =============================================================================

import i18n from '../i18n';

/**
 * 取得目前 i18n locale（BCP-47）。
 * `resolvedLanguage` 會回傳實際生效的 locale（fallback 後），沒有時退回 `language`，
 * 最後退回 `zh-TW` 以保留舊行為。
 */
function currentLocale(): string {
  return i18n.resolvedLanguage || i18n.language || 'zh-TW';
}

/**
 * 格式化日期時間（依目前 i18n locale）
 * @param dateStr ISO 日期字串
 * @param options `Intl.DateTimeFormat` 選項，預設 yyyy/MM/dd HH:mm 等效
 */
export function formatDate(
  dateStr: string | undefined | null,
  options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  },
): string {
  if (!dateStr) return '-';
  try {
    const date = new Date(dateStr);
    if (Number.isNaN(date.getTime())) return dateStr;
    return new Intl.DateTimeFormat(currentLocale(), options).format(date);
  } catch {
    return dateStr;
  }
}

/**
 * 格式化持續時間（秒 -> MM:SS 或 HH:MM:SS）
 * 時間碼為冒號分隔的位元組，與語言無關，故維持現狀。
 */
export function formatDuration(seconds: number | undefined | null): string {
  if (!seconds || seconds <= 0) return '00:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);

  if (h > 0) {
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s
      .toString()
      .padStart(2, '0')}`;
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

/**
 * 格式化病歷號碼
 * 例如 "MRN001234" -> "MRN-001234"
 */
export function formatMRN(mrn: string | undefined | null): string {
  if (!mrn) return '-';
  // 若已有分隔符直接返回
  if (mrn.includes('-')) return mrn;
  // 嘗試在字母與數字之間插入分隔符
  return mrn.replace(/([A-Za-z]+)(\d+)/, '$1-$2');
}

/**
 * 截斷文字
 */
export function truncateText(text: string, maxLength: number, suffix = '...'): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength - suffix.length) + suffix;
}

/**
 * 格式化等候時間（依目前 i18n locale）
 * 依序嘗試 `秒 / 分鐘 / 小時` 三級單位，套用 `Intl.NumberFormat` 的 `unit` 樣式，
 * 讓 zh-TW 顯示「2 分鐘」、en-US 顯示「2 min」等 locale 慣用寫法。
 *
 * 備註：`Intl.NumberFormat` 的 unit 只接受少量已登記單位；`second / minute / hour`
 * 為合法值。
 */
export function formatWaitingTime(seconds: number): string {
  const locale = currentLocale();
  if (seconds < 60) {
    return new Intl.NumberFormat(locale, {
      style: 'unit',
      unit: 'second',
      unitDisplay: 'short',
    }).format(seconds);
  }
  if (seconds < 3600) {
    return new Intl.NumberFormat(locale, {
      style: 'unit',
      unit: 'minute',
      unitDisplay: 'short',
    }).format(Math.floor(seconds / 60));
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const hourPart = new Intl.NumberFormat(locale, {
    style: 'unit',
    unit: 'hour',
    unitDisplay: 'short',
  }).format(h);
  if (m === 0) return hourPart;
  const minutePart = new Intl.NumberFormat(locale, {
    style: 'unit',
    unit: 'minute',
    unitDisplay: 'short',
  }).format(m);
  return `${hourPart} ${minutePart}`;
}

/**
 * 格式化數字（依目前 i18n locale 套用千分位）
 */
export function formatNumber(num: number): string {
  return new Intl.NumberFormat(currentLocale()).format(num);
}

/**
 * 相對時間（例如「3 分鐘前」「3 minutes ago」）。
 *
 * 依目前 i18n locale 使用 `Intl.RelativeTimeFormat`。輸入為 ISO 字串或 `Date`。
 * 未來時間會回正值（例如 "in 2 hours"），過去時間為負值。
 */
export function formatRelative(input: string | Date | undefined | null): string {
  if (!input) return '-';
  try {
    const date = input instanceof Date ? input : new Date(input);
    if (Number.isNaN(date.getTime())) return typeof input === 'string' ? input : '-';
    const locale = currentLocale();
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    const diffSeconds = Math.round((date.getTime() - Date.now()) / 1000);
    const abs = Math.abs(diffSeconds);

    if (abs < 60) return rtf.format(diffSeconds, 'second');
    const diffMinutes = Math.round(diffSeconds / 60);
    if (Math.abs(diffMinutes) < 60) return rtf.format(diffMinutes, 'minute');
    const diffHours = Math.round(diffSeconds / 3600);
    if (Math.abs(diffHours) < 24) return rtf.format(diffHours, 'hour');
    const diffDays = Math.round(diffSeconds / 86_400);
    if (Math.abs(diffDays) < 7) return rtf.format(diffDays, 'day');
    const diffWeeks = Math.round(diffDays / 7);
    if (Math.abs(diffWeeks) < 5) return rtf.format(diffWeeks, 'week');
    const diffMonths = Math.round(diffDays / 30);
    if (Math.abs(diffMonths) < 12) return rtf.format(diffMonths, 'month');
    const diffYears = Math.round(diffDays / 365);
    return rtf.format(diffYears, 'year');
  } catch {
    return typeof input === 'string' ? input : '-';
  }
}
