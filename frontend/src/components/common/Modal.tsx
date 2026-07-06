// =============================================================================
// 通用 Modal 對話框
// =============================================================================

import { useEffect, useId, useRef, type ReactNode } from 'react';
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
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  // ESC 鍵關閉
  useEffect(() => {
    if (!visible || !closable) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [visible, closable, onClose]);

  // a11y：開啟時記住原焦點 → 初始 focus 進 dialog → focus trap（Tab 循環）→ 關閉還原焦點。
  // 參考 LanguageSwitcher 的 role="dialog"/aria-modal 做法，並補上完整 focus trap。
  useEffect(() => {
    if (!visible) return;
    previouslyFocusedRef.current = (document.activeElement as HTMLElement | null) ?? null;
    const node = dialogRef.current;
    const getFocusable = () =>
      node
        ? Array.from(
            node.querySelectorAll<HTMLElement>(
              'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
            ),
          ).filter((el) => el.offsetParent !== null || el === document.activeElement)
        : [];

    // 初始 focus：優先第一個可聚焦元素，否則 focus dialog 容器本身
    const initial = getFocusable()[0] ?? node;
    initial?.focus();

    const handleTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || !node) return;
      const items = getFocusable();
      if (items.length === 0) {
        e.preventDefault();
        node.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement as HTMLElement | null;
      // 焦點若跑到 dialog 之外（或落在容器本身）也拉回範圍內
      if (node.contains(active) === false) {
        e.preventDefault();
        first.focus();
        return;
      }
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleTab);
    return () => {
      document.removeEventListener('keydown', handleTab);
      previouslyFocusedRef.current?.focus?.();
    };
  }, [visible]);

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
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        tabIndex={-1}
        className={`relative z-10 w-full ${sizeClasses[size]} mx-4 rounded-xl bg-white shadow-2xl outline-none dark:bg-dark-card`}
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
          <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-6 py-4 dark:border-dark-border">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
