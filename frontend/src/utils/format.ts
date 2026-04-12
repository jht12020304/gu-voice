// =============================================================================
// 格式化工具函式
// =============================================================================

/**
 * 格式化日期
 * @param dateStr ISO 日期字串
 * @param options 顯示格式
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
    return new Date(dateStr).toLocaleString('zh-TW', options);
  } catch {
    return dateStr;
  }
}

/**
 * 格式化持續時間（秒 -> MM:SS 或 HH:MM:SS）
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
 * 格式化等候時間
 * 例如 120 秒 -> "2 分鐘"
 */
export function formatWaitingTime(seconds: number): string {
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分鐘`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m > 0 ? `${h} 小時 ${m} 分鐘` : `${h} 小時`;
}

/**
 * 格式化數字（加千分位逗號）
 */
export function formatNumber(num: number): string {
  return num.toLocaleString('zh-TW');
}
