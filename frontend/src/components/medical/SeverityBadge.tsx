// =============================================================================
// 告警嚴重度徽章 — Sentry uppercase + Intercom 告警色板
// 同時使用顏色+圖標+文字，確保色盲友善
// =============================================================================

import { useTranslation } from 'react-i18next';

import type { AlertSeverity } from '../../types/enums';

interface SeverityBadgeProps {
  severity: AlertSeverity;
  size?: 'sm' | 'md';
  showIcon?: boolean;
}

const severityConfig: Record<string, {
  labelKey: string;
  classes: string;
  icon: string;
}> = {
  critical: {
    labelKey: 'severity.critical',
    classes: 'bg-alert-critical-bg text-alert-critical-text border-alert-critical-border',
    icon: '⚠',
  },
  high: {
    labelKey: 'severity.high',
    classes: 'bg-alert-high-bg text-alert-high-text border-alert-high-border',
    icon: '▲',
  },
  medium: {
    labelKey: 'severity.medium',
    classes: 'bg-alert-medium-bg text-alert-medium-text border-alert-medium-border',
    icon: '●',
  },
};

export default function SeverityBadge({
  severity,
  size = 'md',
  showIcon = true,
}: SeverityBadgeProps) {
  const { t } = useTranslation('common');
  const config = severityConfig[severity] || severityConfig.medium;
  const sizeClasses = size === 'sm'
    ? 'px-2 py-0.5 text-tiny'
    : 'px-2.5 py-0.5 text-tiny';

  return (
    <span
      className={`badge border ${config.classes} ${sizeClasses} ${
        severity === 'critical' ? 'pulse-critical' : ''
      }`}
    >
      {showIcon && <span className="shrink-0">{config.icon}</span>}
      {t(config.labelKey)}
    </span>
  );
}
