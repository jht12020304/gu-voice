// =============================================================================
// 無限捲動 — sentinel 進入視窗且仍有下一頁時呼叫 onMore
// =============================================================================

import { useEffect, type RefObject } from 'react';

interface UseInfiniteScrollOptions {
  hasMore: boolean;
  isLoading: boolean;
  /** 需為穩定參照（store action 或 useCallback），否則每次 render 都會重建 observer。 */
  onMore: () => void;
}

export function useInfiniteScroll(
  sentinelRef: RefObject<HTMLElement>,
  { hasMore, isLoading, onMore }: UseInfiniteScrollOptions,
): void {
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !isLoading) {
          onMore();
        }
      },
      { threshold: 0.1 },
    );

    if (sentinelRef.current) observer.observe(sentinelRef.current);

    return () => observer.disconnect();
  }, [sentinelRef, hasMore, isLoading, onMore]);
}
