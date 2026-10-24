// =============================================================================
// 場次狀態 → i18n 標籤（單一來源；StatusBadge 與各列表頁共用）
// =============================================================================

import type { TFunction } from 'i18next';

const STATUS_KEYS: Record<string, string> = {
  waiting: 'status.waiting',
  in_progress: 'status.in_progress',
  completed: 'status.completed',
  aborted_red_flag: 'status.aborted_red_flag',
  cancelled: 'status.cancelled',
};

/** 任一 namespace 的 `t` 皆可；未知／缺省狀態回 `common:status.unknown`。 */
export function sessionStatusLabel(status: string | undefined, t: TFunction): string {
  return t(STATUS_KEYS[status ?? ''] ?? 'status.unknown', { ns: 'common' });
}
