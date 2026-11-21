// =============================================================================
// 通用 Modal 對話框
// =============================================================================

import { useId, useLayoutEffect, useRef, type ReactNode } from 'react';
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
  const titleId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  useLayoutEffect(() => {
    const node = dialogRef.current;
    if (!node || !visible) return;
    previouslyFocusedRef.current = document.activeElement as HTMLElement | null;
    node.showModal();
    return () => {
      if (node.open) node.close();
      previouslyFocusedRef.current?.focus();
      requestAnimationFrame(() => previouslyFocusedRef.current?.focus());
    };
  }, [visible]);

  if (!visible) return null;

  return (
    <dialog
        ref={dialogRef}
        aria-labelledby={title ? titleId : undefined}
        onCancel={(event) => {
          event.preventDefault();
          if (closable) {
            dialogRef.current?.close();
            onClose();
            window.setTimeout(() => previouslyFocusedRef.current?.focus(), 0);
          }
        }}
        className={`m-auto w-[calc(100%-2rem)] ${sizeClasses[size]} rounded-xl bg-white p-0 shadow-2xl outline-none backdrop:bg-black/50 dark:bg-dark-card`}
      >
        {/* 標題列 */}
        {(title || closable) && (
          <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4 dark:border-dark-border">
            {title && (
              <h2 id={titleId} className="text-lg font-semibold text-gray-900 dark:text-white">
                {title}
              </h2>
            )}
            {closable && (
              <button
                className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-primary-500 dark:text-white/40 dark:hover:bg-dark-hover dark:hover:text-white/80"
                onClick={() => {
                  dialogRef.current?.close();
                  onClose();
                  window.setTimeout(() => previouslyFocusedRef.current?.focus(), 0);
                }}
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
          <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-6 py-4 dark:border-dark-border">
            {footer}
          </div>
        )}
    </dialog>
  );
}
