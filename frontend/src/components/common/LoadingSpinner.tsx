// =============================================================================
// 載入動畫元件
// =============================================================================

import { useTranslation } from 'react-i18next';

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  message?: string;
  fullPage?: boolean;
}

const sizeClasses = {
  sm: 'h-4 w-4 border-2',
  md: 'h-8 w-8 border-4',
  lg: 'h-12 w-12 border-4',
};

export default function LoadingSpinner({ size = 'md', message, fullPage = false }: LoadingSpinnerProps) {
  const { t } = useTranslation('common');
  // a11y：role="status" + aria-live 讓螢幕閱讀器播報載入中；無自訂訊息時用既有 common:loading 當 aria-label
  const spinner = (
    <div
      className="flex flex-col items-center gap-3"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={message ? undefined : t('loading')}
    >
      <div
        className={`animate-spin rounded-full border-blue-500 border-t-transparent ${sizeClasses[size]}`}
        aria-hidden="true"
      />
      {message && <p className="text-sm text-gray-500 dark:text-white/50">{message}</p>}
    </div>
  );

  if (fullPage) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center">
        {spinner}
      </div>
    );
  }

  return spinner;
}
