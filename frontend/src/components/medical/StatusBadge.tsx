// =============================================================================
// 場次狀態徽章 — 設計融合: Sentry uppercase 標籤 + Stripe pill 圓角
// =============================================================================

import { useTranslation } from 'react-i18next';

import type { SessionStatus } from '../../types/enums';

interface StatusBadgeProps {
  status: SessionStatus;
  size?: 'sm' | 'md';
  showDot?: boolean;
}

const statusConfig: Record<string, {
  labelKey: string;
  classes: string;
  dotColor: string;
}> = {
  waiting: {
    labelKey: 'status.waiting',
    classes: 'bg-status-waiting-bg text-status-waiting border-status-waiting-border',
    dotColor: 'bg-status-waiting',
  },
  in_progress: {
    labelKey: 'status.in_progress',
    classes: 'bg-status-in-progress-bg text-status-in-progress border-status-in-progress-border',
    dotColor: 'bg-status-in-progress',
  },
  completed: {
    labelKey: 'status.completed',
    classes: 'bg-status-completed-bg text-status-completed border-status-completed-border',
    dotColor: 'bg-status-completed',
  },
  aborted_red_flag: {
    labelKey: 'status.aborted_red_flag',
    classes: 'bg-status-red-flag-bg text-status-red-flag border-status-red-flag-border',
    dotColor: 'bg-status-red-flag',
  },
  cancelled: {
    labelKey: 'status.cancelled',
    classes: 'bg-status-cancelled-bg text-status-cancelled border-status-cancelled-border',
    dotColor: 'bg-status-cancelled',
  },
};

export default function StatusBadge({ status, size = 'md', showDot = true }: StatusBadgeProps) {
  const { t } = useTranslation('common');
  const config = statusConfig[status] || statusConfig.waiting;
  const sizeClasses = size === 'sm'
    ? 'px-2 py-0.5 text-tiny'
    : 'px-2.5 py-0.5 text-tiny';
  const dotSize = size === 'sm' ? 'h-1.5 w-1.5' : 'h-2 w-2';

  return (
    <span
      className={`badge border ${config.classes} ${sizeClasses}`}
    >
      {showDot && (
        <span className={`${dotSize} rounded-full ${config.dotColor} shrink-0`} />
      )}
      {t(config.labelKey)}
    </span>
  );
}
