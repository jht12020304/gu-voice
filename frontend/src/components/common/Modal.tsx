// =============================================================================
// 通用 Modal 對話框
// =============================================================================

import { useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

interface ModalProps {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg';
  closable?: boolean;
  footer?: ReactNode;
}

const sizeClasses = {
  sm: 'max-w-md',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
};

export default function Modal({
  visible,
  onClose,
  title,
  children,
  size = 'md',
  closable = true,
  footer,
}: ModalProps) {
  const { t } = useTranslation('common');
  // ESC 鍵關閉
  useEffect(() => {
    if (!visible || !closable) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [visible, closable, onClose]);

  // 防止背景捲動
  useEffect(() => {
    if (visible) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [visible]);

  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* 遮罩 */}
      <div
        className="absolute inset-0 bg-black/50 transition-opacity"
        onClick={closable ? onClose : undefined}
      />

      {/* Modal 內容 */}
      <div
        className={`relative z-10 w-full ${sizeClasses[size]} mx-4 rounded-xl bg-white shadow-2xl`}
      >
        {/* 標題列 */}
        {(title || closable) && (
          <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
            {title && <h2 className="text-lg font-semibold text-gray-900">{title}</h2>}
            {closable && (
              <button
                className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                onClick={onClose}
                aria-label={t('close')}
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
        )}

        {/* 內容 */}
        <div className="px-6 py-4">{children}</div>

        {/* 底部操作 */}
        {footer && (
          <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
