// 檢查急迫度的標籤配色（SOAP 計畫區與快速開單共用）
export const URGENCY_CLASS: Record<string, string> = {
  er_now: 'bg-red-50 text-red-600 ring-1 ring-red-500/15 dark:bg-red-500/10 dark:text-red-400 dark:ring-red-400/20',
  '24h': 'bg-orange-50 text-orange-600 ring-1 ring-orange-500/15 dark:bg-orange-500/10 dark:text-orange-400 dark:ring-orange-400/20',
  this_week: 'bg-amber-50 text-amber-700 ring-1 ring-amber-500/15 dark:bg-amber-500/10 dark:text-amber-400 dark:ring-amber-400/20',
  routine: 'bg-surface-tertiary text-ink-muted ring-1 ring-edge dark:bg-dark-border dark:text-white/50 dark:ring-dark-border',
};
