// =============================================================================
// 病患排隊卡片
// =============================================================================

import StatusBadge from '../medical/StatusBadge';
import { formatWaitingTime } from '../../utils/format';
import type { SessionStatus } from '../../types/enums';

interface QueueCardProps {
  patientName: string;
  chiefComplaint: string;
  status: string;
  waitingSeconds: number;
  hasRedFlag?: boolean;
  onClick?: () => void;
}

export default function QueueCard({
  patientName,
  chiefComplaint,
  status,
  waitingSeconds,
  hasRedFlag = false,
  onClick,
}: QueueCardProps) {
  const isUrgent = hasRedFlag && waitingSeconds > 1800;

  return (
    <div
      className={`flex items-center gap-4 rounded-card border bg-white p-4 transition-all duration-200 dark:bg-dark-card ${
        hasRedFlag
          ? 'border-l-4 border-l-alert-critical border-t-edge border-r-edge border-b-edge dark:border-t-dark-border dark:border-r-dark-border dark:border-b-dark-border'
          : 'border-edge dark:border-dark-border'
      } ${onClick ? 'cursor-pointer hover:bg-surface-tertiary hover:-translate-y-px hover:shadow-card-hover dark:hover:bg-dark-hover' : ''} ${
        isUrgent ? 'animate-pulse-alert' : ''
      }`}
      onClick={onClick}
    >
      {/* 頭像 */}
      <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full text-caption font-semibold ${
        hasRedFlag
          ? 'bg-alert-critical-bg text-alert-critical dark:bg-red-950 dark:text-red-300'
          : 'bg-primary-50 text-primary-700 dark:bg-primary-950 dark:text-primary-300'
      }`}>
        {patientName.charAt(0)}
      </div>

      {/* 資訊 */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-body font-medium text-ink-heading dark:text-white">{patientName}</p>
          {hasRedFlag && (
            <span className="badge badge-red-flag text-tiny px-1.5 py-0.5">
              紅旗
            </span>
          )}
        </div>
        <p className="mt-0.5 truncate text-small text-ink-muted">{chiefComplaint}</p>
      </div>

      {/* 狀態 + 等候時間 */}
      <div className="flex flex-shrink-0 flex-col items-end gap-1">
        <StatusBadge status={status as SessionStatus} size="sm" />
        <span className="text-tiny text-ink-muted font-tnum">{formatWaitingTime(waitingSeconds)}</span>
      </div>
    </div>
  );
}
