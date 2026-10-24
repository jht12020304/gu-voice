// =============================================================================
// 點擊元素外部時呼叫 callback（下拉選單收合用）
// =============================================================================

import { useEffect, type RefObject } from 'react';

export function useClickOutside(ref: RefObject<HTMLElement>, onOutside: () => void): void {
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onOutside();
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [ref, onOutside]);
}
