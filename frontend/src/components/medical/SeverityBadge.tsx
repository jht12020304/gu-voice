// =============================================================================
// 告警嚴重度徽章 — Sentry uppercase + Intercom 告警色板
// 同時使用顏色+圖標+文字，確保色盲友善
// =============================================================================

import type { AlertSeverity } from '../../types/enums';

interface SeverityBadgeProps {
  severity: AlertSeverity;
  size?: 'sm' | 'md';
  showIcon?: boolean;
}

const severityConfig: Record<string, {
  label: string;
  classes: string;
  icon: string;
}> = {
  critical: {
    label: '危急',
    classes: 'bg-alert-critical-bg text-alert-critical-text border-alert-critical-border',
    icon: '⚠',
  },
  high: {
    label: '高度',
    classes: 'bg-alert-high-bg text-alert-high-text border-alert-high-border',
    icon: '▲',
  },
  medium: {
    label: '中度',
    classes: 'bg-alert-medium-bg text-alert-medium-text border-alert-medium-border',
    icon: '●',
  },
};

export default function SeverityBadge({
  severity,
  size = 'md',
  showIcon = true,
}: SeverityBadgeProps) {
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
      {config.label}
    </span>
  );
}
