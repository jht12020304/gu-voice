// =============================================================================
// 告警列表項目 — 左側色帶 + Sentry 監控風格
// =============================================================================

import { useTranslation } from 'react-i18next';
import SeverityBadge from '../medical/SeverityBadge';
import { relativeTime } from '../../utils/date';
import type { AlertSeverity } from '../../types/enums';

interface AlertItemProps {
  id: string;
  title: string;
  description?: string;
  severity: string;
  patientName?: string;
  chiefComplaint?: string;
  sessionStatus?: string;
  triggerReason?: string;
  suggestedActionCount?: number;
  createdAt: string;
  isAcknowledged: boolean;
  onAcknowledge?: () => void;
  onViewDetail?: () => void;
  onClick?: () => void;
}

const severityBorderClass: Record<string, string> = {
  critical: 'alert-card-critical',
  high: 'alert-card-high',
  medium: 'alert-card-medium',
};

export default function AlertItem({
  title,
  description,
  severity,
  patientName,
  chiefComplaint,
  sessionStatus,
  triggerReason,
  suggestedActionCount,
  createdAt,
  isAcknowledged,
  onAcknowledge,
  onViewDetail,
  onClick,
}: AlertItemProps) {
  const { t } = useTranslation('dashboard');
  return (
    <div
      className={`alert-card ${severityBorderClass[severity] || ''} ${
        !isAcknowledged ? 'border-l-0' : 'border-l'
      } ${
        onClick ? 'cursor-pointer' : ''
      }`}
      onClick={onClick}
    >
      <div className="flex items-start gap-4">
        <div className="shrink-0 pt-0.5">
          <svg
            className={`h-5 w-5 ${
              severity === 'critical'
                ? 'text-alert-critical'
                : severity === 'high'
                  ? 'text-alert-high-text'
                  : 'text-alert-medium-text'
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-body font-semibold text-ink-heading dark:text-white">{title}</p>
            <SeverityBadge severity={severity as AlertSeverity} size="sm" />
            <span
              className={`rounded-pill px-2.5 py-0.5 text-tiny font-semibold ${
                isAcknowledged
                  ? 'bg-green-50 text-green-700 ring-1 ring-green-200 dark:bg-green-950/30 dark:text-green-300 dark:ring-green-900'
                  : 'bg-surface-secondary text-ink-secondary ring-1 ring-edge dark:bg-dark-surface dark:text-dark-text-muted dark:ring-dark-border'
              }`}
            >
              {isAcknowledged ? t('alert.acknowledged') : t('alert.pending')}
            </span>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2 text-tiny text-ink-muted">
            {patientName ? (
              <span className="rounded-pill bg-surface-secondary px-2.5 py-1 text-small font-medium text-ink-secondary dark:bg-dark-surface dark:text-dark-text-muted">
                {patientName}
              </span>
            ) : null}
            {chiefComplaint ? (
              <span className="rounded-pill bg-white px-2.5 py-1 text-small text-ink-secondary ring-1 ring-edge dark:bg-dark-card dark:text-dark-text-muted dark:ring-dark-border">
                {t('alert.chiefComplaintLabel', { value: chiefComplaint })}
              </span>
            ) : null}
            {sessionStatus ? (
              <span className="text-small text-ink-muted">
                {t('alert.sessionStatusLabel', { value: sessionStatus })}
              </span>
            ) : null}
          </div>

          {description && (
            <p className="mt-3 text-small leading-6 text-ink-secondary line-clamp-3 dark:text-white/75">
              {description}
            </p>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-3 text-tiny text-ink-muted">
            {triggerReason ? (
              <span className="rounded-pill bg-surface-secondary px-2.5 py-1 text-small text-ink-muted dark:bg-dark-surface dark:text-dark-text-muted">
                {t('alert.triggerLabel', { value: triggerReason })}
              </span>
            ) : null}
            {suggestedActionCount ? (
              <span className="text-small text-ink-muted">
                {t('alert.suggestedActions', { count: suggestedActionCount })}
              </span>
            ) : null}
            <span>{relativeTime(createdAt)}</span>
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="text-right">
            <p className="text-small font-medium text-ink-heading dark:text-white">{new Date(createdAt).toLocaleDateString('zh-TW')}</p>
            <p className="mt-1 text-tiny text-ink-muted">
              {new Date(createdAt).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}
            </p>
          </div>

          <div className="flex flex-wrap justify-end gap-2">
            {onViewDetail ? (
              <button
                className="btn-secondary px-3 py-1.5 text-tiny"
                onClick={(e) => {
                  e.stopPropagation();
                  onViewDetail();
                }}
              >
                {t('alert.viewDetail')}
              </button>
            ) : null}

            {!isAcknowledged && onAcknowledge ? (
              <button
                className="btn-danger shrink-0 px-3 py-1.5 text-tiny"
                onClick={(e) => {
                  e.stopPropagation();
                  onAcknowledge();
                }}
              >
                {t('alert.acknowledge')}
              </button>
            ) : (
              <span className="shrink-0 rounded-pill bg-green-50 px-3 py-1.5 text-tiny font-semibold text-green-700 dark:bg-green-950/30 dark:text-green-300">
                {t('alert.acknowledgedBadge')}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
