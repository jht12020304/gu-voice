// =============================================================================
// 無限捲動 — sentinel 進入視窗且仍有下一頁時呼叫 onMore
// hasMore / isLoading / onMore 走 ref 讀最新值：observer 只在 sentinel 變動時建立一次，
// 不隨每次 loading 翻轉重建。
// =============================================================================

import { useEffect, useRef, type RefObject } from 'react';

interface UseInfiniteScrollOptions {
  hasMore: boolean;
  isLoading: boolean;
  onMore: () => void;
}

export function useInfiniteScroll(
  sentinelRef: RefObject<HTMLElement>,
  options: UseInfiniteScrollOptions,
): void {
  const latest = useRef(options);
  latest.current = options;

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const { hasMore, isLoading, onMore } = latest.current;
        if (entries[0].isIntersecting && hasMore && !isLoading) {
          onMore();
        }
      },
      { threshold: 0.1 },
    );

    if (sentinelRef.current) observer.observe(sentinelRef.current);

    return () => observer.disconnect();
  }, [sentinelRef]);
}
