// =============================================================================
// 統計數據卡片 — Stripe 藍調陰影 + tnum 數字排版
// =============================================================================

interface StatCardProps {
  title: string;
  value: number | string;
  icon: React.ReactNode;
  color?: 'blue' | 'green' | 'red' | 'orange';
  trend?: { value: number; label: string };
  onClick?: () => void;
  loading?: boolean;
}

const colorClasses = {
  blue: {
    icon: 'bg-primary-50 text-primary-600 dark:bg-primary-950 dark:text-primary-300',
    trend: 'text-primary-600',
  },
  green: {
    icon: 'bg-alert-success-bg text-alert-success dark:bg-green-950 dark:text-green-300',
    trend: 'text-alert-success',
  },
  red: {
    icon: 'bg-alert-critical-bg text-alert-critical dark:bg-red-950 dark:text-red-300',
    trend: 'text-alert-critical',
  },
  orange: {
    icon: 'bg-alert-high-bg text-alert-high dark:bg-orange-950 dark:text-orange-300',
    trend: 'text-alert-high',
  },
};

export default function StatCard({
  title,
  value,
  icon,
  color = 'blue',
  trend,
  onClick,
  loading = false,
}: StatCardProps) {
  const colors = colorClasses[color];

  return (
    <div
      className={`card ${
        onClick ? 'card-interactive' : ''
      }`}
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <p className="text-caption text-ink-secondary">{title}</p>
          {loading ? (
            <div className="mt-2 h-8 w-20 skeleton" />
          ) : (
            <p className="text-h1 font-bold text-ink-heading dark:text-white font-tnum">{value}</p>
          )}
          {trend && !loading && (
            <p className={`text-tiny font-medium ${colors.trend}`}>
              <span className="inline-flex items-center gap-0.5">
                {trend.value > 0 ? '↑' : trend.value < 0 ? '↓' : '→'}{' '}
                {Math.abs(trend.value)}% {trend.label}
              </span>
            </p>
          )}
        </div>
        <div className={`rounded-card p-2.5 ${colors.icon}`}>
          {icon}
        </div>
      </div>
    </div>
  );
}
