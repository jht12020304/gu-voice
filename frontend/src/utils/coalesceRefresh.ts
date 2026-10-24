/** Collapse event bursts; an event during a request always gets one follow-up. */
export function coalesceRefresh(refresh: () => Promise<unknown>, delay = 100) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let running = false;
  let dirty = false;
  let disposed = false;
  const schedule = () => {
    if (disposed) return;
    dirty = true;
    if (running || timer) return;
    timer = setTimeout(async () => {
      timer = undefined;
      dirty = false;
      running = true;
      try { await refresh(); }
      finally {
        running = false;
        if (dirty) schedule();
      }
    }, delay);
  };
  return {
    schedule,
    dispose: () => { disposed = true; clearTimeout(timer); },
  };
}
