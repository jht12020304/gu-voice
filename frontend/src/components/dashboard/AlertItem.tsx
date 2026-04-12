// =============================================================================
// 告警列表項目 — 左側色帶 + Sentry 監控風格
// =============================================================================

import SeverityBadge from '../medical/SeverityBadge';
import { relativeTime } from '../../utils/date';
import type { AlertSeverity } from '../../types/enums';

interface AlertItemProps {
  id: string;
  title: string;
  description?: string;
  severity: string;
  patientName?: string;
  createdAt: string;
  isAcknowledged: boolean;
  onAcknowledge?: () => void;
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
  createdAt,
  isAcknowledged,
  onAcknowledge,
  onClick,
}: AlertItemProps) {
  return (
    <div
      className={`alert-card ${severityBorderClass[severity] || ''} ${
        !isAcknowledged ? 'border-l-0' : 'border-l'
      } ${severity === 'critical' && !isAcknowledged ? 'animate-pulse-alert' : ''} ${
        onClick ? 'cursor-pointer' : ''
      }`}
      onClick={onClick}
    >
      <div className="flex items-start gap-3">
        {/* 告警圖示 */}
        <div className="shrink-0 pt-0.5">
          <svg
            className={`h-5 w-5 ${
              !isAcknowledged ? 'text-alert-critical' : 'text-ink-muted'
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

        {/* 內容 */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-body font-medium text-ink-heading">{title}</p>
            <SeverityBadge severity={severity as AlertSeverity} size="sm" />
          </div>
          {description && (
            <p className="mt-1 text-small text-ink-secondary line-clamp-2">{description}</p>
          )}
          <div className="mt-1.5 flex items-center gap-2 text-tiny text-ink-muted">
            {patientName && (
              <>
                <span className="font-medium text-ink-secondary">{patientName}</span>
                <span>·</span>
              </>
            )}
            <span>{relativeTime(createdAt)}</span>
          </div>
        </div>

        {/* 確認按鈕 */}
        {!isAcknowledged && onAcknowledge && (
          <button
            className="btn-danger shrink-0 text-tiny px-3 py-1.5"
            onClick={(e) => {
              e.stopPropagation();
              onAcknowledge();
            }}
          >
            確認處理
          </button>
        )}

        {isAcknowledged && (
          <span className="shrink-0 text-tiny text-alert-success font-medium">
            ✓ 已確認
          </span>
        )}
      </div>
    </div>
  );
}
