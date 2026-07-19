// =============================================================================
// 期刊級圖表原語（純 inline SVG，無外部依賴）
//
// 設計依據：
//   - 連續資料用箱形圖顯示分佈，不用長條圖遮蔽（Weissgerber 2015,
//     PLOS Biology「Beyond Bar and Line Graphs」；Nature/eLife 已要求）
//   - 比例一律附 Wilson 95% CI 誤差線與分子/分母（SAMPL 指引）
//   - 子群比較用森林圖 + 參考線（Lancet/JAMA 慣例）
//   - 每個 Figure 可下載向量 SVG 供投稿
//
// 顏色沿用 dataviz 已驗證 token（validate_palette PASS，明暗雙面）：
//   主色 #2563eb、次色 #16a34a、status 危急/高/中、格線走 currentColor 淡化。
// 文字一律 ink token（避免 categorical 色當文字）。
// =============================================================================

import { useCallback, useRef } from 'react';
import type { NumericSummary, Proportion } from '../../../types/api';

const INK = { blue: '#2563eb', green: '#16a34a' };

// ── Figure 容器：panel 編號 + caption + n= + 下載 SVG ──────

export function FigureCard({
  figureLabel,
  title,
  caption,
  footnote,
  downloadName,
  children,
}: {
  figureLabel: string;
  title: string;
  caption?: string;
  footnote?: string;
  downloadName: string;
  children: React.ReactNode;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);

  const downloadSvg = useCallback(() => {
    const svg = bodyRef.current?.querySelector('svg');
    if (!svg) return;
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    // 內嵌白底，讓投稿圖在任何背景下都可讀
    const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    bg.setAttribute('width', '100%');
    bg.setAttribute('height', '100%');
    bg.setAttribute('fill', '#ffffff');
    clone.insertBefore(bg, clone.firstChild);
    const blob = new Blob([new XMLSerializer().serializeToString(clone)], {
      type: 'image/svg+xml;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${downloadName}.svg`;
    a.click();
    URL.revokeObjectURL(url);
  }, [downloadName]);

  return (
    <figure className="card m-0">
      <figcaption className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-tiny font-bold uppercase tracking-wide text-primary-600">
              {figureLabel}
            </span>
            <h2 className="text-h3 text-ink-heading dark:text-white">{title}</h2>
          </div>
          {caption ? <p className="mt-1 text-small text-ink-muted">{caption}</p> : null}
        </div>
        <button
          type="button"
          onClick={downloadSvg}
          className="shrink-0 rounded-card border border-edge px-2.5 py-1.5 text-tiny font-medium text-ink-secondary transition hover:bg-surface-hover dark:border-dark-border dark:hover:bg-dark-hover"
          title="Download vector SVG"
        >
          ↓ SVG
        </button>
      </figcaption>
      <div ref={bodyRef}>{children}</div>
      {footnote ? <p className="mt-3 text-tiny text-ink-muted">{footnote}</p> : null}
    </figure>
  );
}

// ── 水平箱形圖組（多列共用同一 x 軸；median/IQR box + whisker + 離群 + n）──
// 每列一個連續變數的分佈。scale 由呼叫端統一或各列自訂。

export type BoxRow = {
  key: string;
  label: string;
  summary: NumericSummary;
  unit?: string;
  /** 轉換顯示值（如秒→分）；不影響統計，只影響刻度標籤與資料值縮放 */
  transform?: (v: number) => number;
};

export function BoxPlotRow({
  summary,
  min,
  max,
  transform = (v) => v,
  formatTick,
  unit,
}: {
  summary: NumericSummary;
  min: number;
  max: number;
  transform?: (v: number) => number;
  formatTick: (v: number) => string;
  unit?: string;
}) {
  const W = 520;
  const H = 46;
  const PAD = { l: 6, r: 46 };
  const span = max - min || 1;
  const x = (raw: number | null) =>
    raw === null ? PAD.l : PAD.l + ((transform(raw) - min) / span) * (W - PAD.l - PAD.r);
  const cy = 20;
  const s = summary;
  if (s.n === 0) {
    return <p className="py-2 text-tiny text-ink-muted">n = 0</p>;
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="box plot">
      {/* whisker line */}
      <line x1={x(s.whiskerLow)} x2={x(s.whiskerHigh)} y1={cy} y2={cy} stroke="currentColor" className="text-ink-muted" strokeWidth="1.5" />
      {/* whisker caps */}
      <line x1={x(s.whiskerLow)} x2={x(s.whiskerLow)} y1={cy - 6} y2={cy + 6} stroke="currentColor" className="text-ink-muted" strokeWidth="1.5" />
      <line x1={x(s.whiskerHigh)} x2={x(s.whiskerHigh)} y1={cy - 6} y2={cy + 6} stroke="currentColor" className="text-ink-muted" strokeWidth="1.5" />
      {/* IQR box */}
      <rect
        x={x(s.p25)}
        y={cy - 11}
        width={Math.max(x(s.p75) - x(s.p25), 1)}
        height={22}
        rx={2}
        fill={INK.blue}
        fillOpacity={0.14}
        stroke={INK.blue}
        strokeWidth="1.5"
      />
      {/* median */}
      <line x1={x(s.median)} x2={x(s.median)} y1={cy - 11} y2={cy + 11} stroke={INK.blue} strokeWidth="2.5" />
      {/* outliers */}
      {s.outliers.map((o, i) => (
        <circle key={i} cx={x(o)} cy={cy} r={2.6} fill="none" stroke="currentColor" className="text-ink-muted" strokeWidth="1" />
      ))}
      {/* median value label at right */}
      <text x={W - PAD.r + 6} y={cy + 4} className="fill-ink-heading text-[11px] font-semibold" style={{ fontVariantNumeric: 'tabular-nums' }}>
        {formatTick(transform(s.median ?? 0))}{unit ? ` ${unit}` : ''}
      </text>
    </svg>
  );
}

export function BoxPlotGroup({ rows, formatTick }: { rows: BoxRow[]; formatTick: (v: number) => string }) {
  return (
    <div className="grid gap-4">
      {rows.map((r) => {
        const t = r.transform ?? ((v: number) => v);
        const lo = r.summary.n ? t(r.summary.min ?? 0) : 0;
        const hi = r.summary.n ? t(r.summary.max ?? 1) : 1;
        const pad = (hi - lo) * 0.05 || 1;
        return (
          <div key={r.key} className="grid grid-cols-[130px_1fr] items-center gap-3">
            <div className="text-small text-ink-body dark:text-dark-text-muted">
              {r.label}
              <span className="ml-1 text-tiny text-ink-muted">n={r.summary.n}</span>
            </div>
            <div className="text-ink-muted">
              <BoxPlotRow
                summary={r.summary}
                min={lo - pad}
                max={hi + pad}
                transform={r.transform}
                formatTick={formatTick}
                unit={r.unit}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── 比例條 + 95% CI 誤差線（分子/分母標在右）──────────────

export function ProportionRow({
  label,
  prop,
  color = INK.blue,
}: {
  label: string;
  prop: Proportion;
  color?: string;
}) {
  const W = 520;
  const H = 34;
  const PAD = { l: 6, r: 96 };
  const barW = W - PAD.l - PAD.r;
  const x = (v: number) => PAD.l + v * barW;
  const v = prop.value;
  const cy = 17;
  return (
    <div className="grid grid-cols-[130px_1fr] items-center gap-3">
      <span className="truncate text-small text-ink-body dark:text-dark-text-muted">{label}</span>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="proportion with 95% CI">
        {/* track */}
        <rect x={PAD.l} y={cy - 7} width={barW} height={14} rx={4} className="fill-surface-tertiary dark:fill-dark-surface" />
        {v !== null ? (
          <>
            <rect x={PAD.l} y={cy - 7} width={Math.max(x(v) - PAD.l, 1)} height={14} rx={4} fill={color} />
            {/* 95% CI whisker */}
            {prop.ciLow !== null && prop.ciHigh !== null ? (
              <>
                <line x1={x(prop.ciLow)} x2={x(prop.ciHigh)} y1={cy} y2={cy} stroke="currentColor" className="text-ink-heading dark:text-white" strokeWidth="1.5" />
                <line x1={x(prop.ciLow)} x2={x(prop.ciLow)} y1={cy - 5} y2={cy + 5} stroke="currentColor" className="text-ink-heading dark:text-white" strokeWidth="1.5" />
                <line x1={x(prop.ciHigh)} x2={x(prop.ciHigh)} y1={cy - 5} y2={cy + 5} stroke="currentColor" className="text-ink-heading dark:text-white" strokeWidth="1.5" />
              </>
            ) : null}
            <text x={W - PAD.r + 8} y={cy + 4} className="fill-ink-heading text-[11px] font-semibold" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {(v * 100).toFixed(1)}%
            </text>
          </>
        ) : (
          <text x={W - PAD.r + 8} y={cy + 4} className="fill-ink-muted text-[11px]">—</text>
        )}
      </svg>
    </div>
  );
}

// ── 森林圖：子群比例 + 95% CI，含整體參考線 ───────────────

export function ForestPlot({
  rows,
  overall,
  overallLabel,
  xLabel,
}: {
  rows: { label: string; prop: Proportion }[];
  overall: number | null;
  overallLabel: string;
  xLabel: string;
}) {
  const W = 640;
  const rowH = 34;
  const headH = 8;
  const footH = 34;
  const H = headH + rows.length * rowH + footH;
  const PAD = { l: 150, r: 60 };
  const plotW = W - PAD.l - PAD.r;
  // x 軸固定 0~1（比例）
  const x = (v: number) => PAD.l + v * plotW;
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="forest plot">
      {/* 整體參考線 */}
      {overall !== null ? (
        <line x1={x(overall)} x2={x(overall)} y1={headH} y2={headH + rows.length * rowH} stroke={INK.blue} strokeWidth="1" strokeDasharray="4 3" />
      ) : null}
      {/* grid ticks */}
      {ticks.map((tk) => (
        <g key={tk}>
          <line x1={x(tk)} x2={x(tk)} y1={headH} y2={headH + rows.length * rowH} className="stroke-edge dark:stroke-dark-border" strokeWidth="1" />
          <text x={x(tk)} y={H - footH + 20} textAnchor="middle" className="fill-ink-muted text-[10px]" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {Math.round(tk * 100)}%
          </text>
        </g>
      ))}
      {/* rows */}
      {rows.map((r, i) => {
        const cy = headH + i * rowH + rowH / 2;
        const p = r.prop;
        const hasCI = p.value !== null && p.ciLow !== null && p.ciHigh !== null;
        // 點大小反映樣本量（森林圖慣例：n 越大點越大）
        const size = 3 + Math.min(6, Math.sqrt(p.denominator));
        return (
          <g key={r.label}>
            <text x={8} y={cy + 4} className="fill-ink-body dark:fill-dark-text-muted text-[12px] font-medium">
              {r.label}
            </text>
            {hasCI ? (
              <>
                <line x1={x(p.ciLow as number)} x2={x(p.ciHigh as number)} y1={cy} y2={cy} stroke="currentColor" className="text-ink-heading dark:text-white" strokeWidth="1.5" />
                <line x1={x(p.ciLow as number)} x2={x(p.ciLow as number)} y1={cy - 5} y2={cy + 5} stroke="currentColor" className="text-ink-heading dark:text-white" strokeWidth="1.5" />
                <line x1={x(p.ciHigh as number)} x2={x(p.ciHigh as number)} y1={cy - 5} y2={cy + 5} stroke="currentColor" className="text-ink-heading dark:text-white" strokeWidth="1.5" />
                <rect x={x(p.value as number) - size / 2} y={cy - size / 2} width={size} height={size} fill={INK.blue} className="stroke-white dark:stroke-dark-card" strokeWidth="1" />
                <text x={W - PAD.r + 6} y={cy + 4} className="fill-ink-heading text-[11px]" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {`${((p.value as number) * 100).toFixed(0)}% (${p.numerator}/${p.denominator})`}
                </text>
              </>
            ) : (
              <text x={x(0.5)} y={cy + 4} textAnchor="middle" className="fill-ink-muted text-[11px]">
                n/a
              </text>
            )}
          </g>
        );
      })}
      {/* x label + overall legend */}
      <text x={PAD.l + plotW / 2} y={H - 4} textAnchor="middle" className="fill-ink-secondary text-[11px]">
        {xLabel}
        {overall !== null ? `\u3000- - - ${overallLabel} ${(overall * 100).toFixed(1)}%` : ''}
      </text>
    </svg>
  );
}

// ── 直方圖（單一分佈；資料端 4px 圓角、柱間 gap）─────────────

export function HistogramChart({
  buckets,
  bucketLabel,
  countLabel,
}: {
  buckets: { start: number; end: number; count: number }[];
  bucketLabel: (b: { start: number; end: number }) => string;
  countLabel: string;
}) {
  const max = Math.max(...buckets.map((b) => b.count), 1);
  const W = 560;
  const H = 170;
  const PAD = { l: 4, r: 4, t: 16, b: 22 };
  const bw = (W - PAD.l - PAD.r) / buckets.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="histogram">
      {buckets.map((b, i) => {
        const h = b.count > 0 ? Math.max((b.count / max) * (H - PAD.t - PAD.b), 3) : 0;
        const bx = PAD.l + i * bw;
        return (
          <g key={i}>
            {b.count > 0 ? (
              <text x={bx + bw / 2} y={H - PAD.b - h - 4} textAnchor="middle" className="fill-ink-muted text-[10px]" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {b.count}
              </text>
            ) : null}
            <rect x={bx + 1} y={H - PAD.b - h} width={bw - 2} height={h} rx={3} fill={INK.blue} />
          </g>
        );
      })}
      <text x={PAD.l} y={H - 6} className="fill-ink-muted text-[10px]">{buckets.length ? bucketLabel(buckets[0]) : ''}</text>
      <text x={W - PAD.r} y={H - 6} textAnchor="end" className="fill-ink-muted text-[10px]">{buckets.length ? bucketLabel(buckets[buckets.length - 1]) : ''}</text>
      <text x={W / 2} y={H - 6} textAnchor="middle" className="fill-ink-secondary text-[10px]">{countLabel}</text>
    </svg>
  );
}

// ── 部分-整體堆疊條（2px surface gap + legend + 計數）───────

export function StackedShareBar({
  buckets,
  labels,
  colors,
}: {
  buckets: { key: string; count: number }[];
  labels: Record<string, string>;
  colors: Record<string, string>;
}) {
  const total = buckets.reduce((s, b) => s + b.count, 0);
  return (
    <div>
      <div className="flex h-6 w-full gap-[2px] overflow-hidden rounded-[4px]">
        {total > 0 ? (
          buckets
            .filter((b) => b.count > 0)
            .map((b) => (
              <div key={b.key} style={{ width: `${(b.count / total) * 100}%`, backgroundColor: colors[b.key] ?? '#64748b' }} />
            ))
        ) : (
          <div className="w-full bg-surface-tertiary dark:bg-dark-surface" />
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
        {buckets.map((b) => (
          <span key={b.key} className="flex items-center gap-1.5 text-tiny text-ink-secondary">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colors[b.key] ?? '#64748b' }} />
            {labels[b.key] ?? b.key}
            <span className="font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>{b.count}</span>
            <span className="text-ink-muted" style={{ fontVariantNumeric: 'tabular-nums' }}>
              ({total > 0 ? `${Math.round((b.count / total) * 100)}%` : '—'})
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ── 週趨勢折線（2 系列 + legend + 8px 端點/2px surface ring）──

export function WeeklyTrendChart({
  items,
  labels,
}: {
  items: { weekStart: string; sessions: number; completed: number; redFlagSessions: number }[];
  labels: { sessions: string; completed: string };
}) {
  const W = 640;
  const H = 200;
  const PAD = { l: 30, r: 12, t: 12, b: 26 };
  const max = Math.max(...items.map((i) => i.sessions), 1);
  const x = (i: number) => PAD.l + (items.length <= 1 ? 0 : (i / (items.length - 1)) * (W - PAD.l - PAD.r));
  const y = (v: number) => H - PAD.b - (v / max) * (H - PAD.t - PAD.b);
  const path = (get: (it: (typeof items)[number]) => number) =>
    items.map((it, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(get(it)).toFixed(1)}`).join(' ');
  const gridVals = [0, Math.ceil(max / 2), max];
  return (
    <div>
      <div className="mb-2 flex items-center gap-4 text-tiny text-ink-secondary">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: INK.blue }} />{labels.sessions}</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: INK.green }} />{labels.completed}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="weekly trend">
        {gridVals.map((g) => (
          <g key={g}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(g)} y2={y(g)} className="stroke-edge dark:stroke-dark-border" strokeWidth="1" />
            <text x={PAD.l - 6} y={y(g) + 3} textAnchor="end" className="fill-ink-muted text-[10px]" style={{ fontVariantNumeric: 'tabular-nums' }}>{g}</text>
          </g>
        ))}
        <path d={path((it) => it.sessions)} fill="none" stroke={INK.blue} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <path d={path((it) => it.completed)} fill="none" stroke={INK.green} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {items.map((it, i) => (
          <g key={it.weekStart}>
            <circle cx={x(i)} cy={y(it.sessions)} r="4" fill={INK.blue} className="stroke-white dark:stroke-dark-card" strokeWidth="2" />
            <circle cx={x(i)} cy={y(it.completed)} r="4" fill={INK.green} className="stroke-white dark:stroke-dark-card" strokeWidth="2" />
            <text x={x(i)} y={H - 8} textAnchor="middle" className="fill-ink-muted text-[10px]" style={{ fontVariantNumeric: 'tabular-nums' }}>{it.weekStart.slice(5)}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}
