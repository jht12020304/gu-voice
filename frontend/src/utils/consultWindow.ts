// 問診起訖（epoch ms）＋時長（秒）。場次欄位優先；production 有不少已完成場次沒有
// startedAt／durationSeconds，缺值時用逐字稿第一句／最後一句的 createdAt 補。（同 Flutter consultWindow）
export function consultWindow(
  session: { startedAt?: string; completedAt?: string; durationSeconds?: number } | null | undefined,
  turnTimes: Array<string | undefined | null>,
): { start?: number; end?: number; seconds?: number } {
  const ms = (iso?: string | null) => (iso ? Date.parse(iso) : NaN);
  const times = turnTimes.map(ms).filter((n) => !Number.isNaN(n)).sort((a, b) => a - b);
  const s = ms(session?.startedAt);
  const e = ms(session?.completedAt);
  const start = Number.isNaN(s) ? times[0] : s;
  const end = Number.isNaN(e) ? times[times.length - 1] : e;
  const d = session?.durationSeconds;
  const seconds =
    d != null && d >= 0 ? d : start != null && end != null && end >= start ? Math.round((end - start) / 1000) : undefined;
  return { start, end, seconds };
}
