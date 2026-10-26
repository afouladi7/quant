import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

// Chart conventions (dataviz method): one y-axis per chart, 2px lines, hairline grid,
// legend for >= 2 series plus direct end labels, crosshair tooltip, text in text tokens.

export interface Series {
  key: string;
  label: string;
  slot: 1 | 2 | 3;
  points: { x: number; y: number | null }[];
}

function useWidth<T extends HTMLElement>(fallback = 600) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth || fallback);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || fallback));
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallback]);
  return [ref, w] as const;
}

function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

export function LineChart({
  title,
  series,
  yFormat = (v) => String(v),
  xLabel = "tick",
  height = 200,
  zeroLine = false,
  stepped = false,
}: {
  title: string;
  series: Series[];
  yFormat?: (v: number) => string;
  xLabel?: string;
  height?: number;
  zeroLine?: boolean;
  stepped?: boolean;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const titleId = useId();
  const pad = { l: 64, r: 64, t: 10, b: 26 };
  const all = series.flatMap((s) => s.points.filter((p) => p.y !== null)) as { x: number; y: number }[];
  const xs = all.map((p) => p.x);
  const ys = all.map((p) => p.y);
  if (zeroLine) ys.push(0);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y0 === y1) { const pad = Math.abs(y0) * 0.001 || 1; y0 -= pad; y1 += pad; }
  const yPad = (y1 - y0) * 0.08;
  y0 -= yPad; y1 += yPad;
  const iw = Math.max(10, width - pad.l - pad.r), ih = height - pad.t - pad.b;
  const sx = (x: number) => pad.l + (x1 === x0 ? iw / 2 : ((x - x0) / (x1 - x0)) * iw);
  const sy = (y: number) => pad.t + ih - ((y - y0) / (y1 - y0)) * ih;
  const yTicks = niceTicks(y0, y1);
  const xTicks = niceTicks(x0, x1, 5).filter((t) => Number.isInteger(t));
  const xsUnique = useMemo(() => Array.from(new Set(xs)).sort((a, b) => a - b), [xs.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!all.length) {
    return (
      <figure className="chart">
        <figcaption className="chart-title">{title}</figcaption>
        <p className="empty small">No data yet — start the simulation or run a step.</p>
      </figure>
    );
  }

  const path = (pts: { x: number; y: number | null }[]) => {
    let d = "";
    let prev: { x: number; y: number } | null = null;
    for (const p of pts) {
      if (p.y === null) { prev = null; continue; }
      if (!prev) d += `M${sx(p.x)},${sy(p.y)}`;
      else if (stepped) d += `H${sx(p.x)}V${sy(p.y)}`;
      else d += `L${sx(p.x)},${sy(p.y)}`;
      prev = p as { x: number; y: number };
    }
    return d;
  };

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = (e.target as SVGRectElement).getBoundingClientRect();
    const px = e.clientX - rect.left + pad.l;
    let best = xsUnique[0];
    for (const x of xsUnique) if (Math.abs(sx(x) - px) < Math.abs(sx(best) - px)) best = x;
    setHover(best);
  };

  const hoverRows = hover === null ? [] : series.map((s) => ({ s, p: s.points.find((p) => p.x === hover) }));

  return (
    <figure className="chart" ref={ref} aria-labelledby={titleId}>
      <figcaption id={titleId} className="chart-title">{title}</figcaption>
      {series.length > 1 && (
        <div className="legend" aria-hidden="true">
          {series.map((s) => (
            <span key={s.key}><i className={`key s${s.slot}`} />{s.label}</span>
          ))}
        </div>
      )}
      <svg width={width} height={height} role="img" aria-label={`${title}: line chart`}>
        {yTicks.map((t) => (
          <g key={t}>
            <line className="grid" x1={pad.l} x2={pad.l + iw} y1={sy(t)} y2={sy(t)} />
            <text className="axis" x={pad.l - 6} y={sy(t)} textAnchor="end" dominantBaseline="middle">{yFormat(t)}</text>
          </g>
        ))}
        {zeroLine && y0 < 0 && y1 > 0 && <line className="zero" x1={pad.l} x2={pad.l + iw} y1={sy(0)} y2={sy(0)} />}
        {xTicks.map((t) => (
          <text key={t} className="axis" x={sx(t)} y={height - 6} textAnchor="middle">{t}</text>
        ))}
        <text className="axis" x={pad.l + iw} y={height - 6} textAnchor="end" dy="0">{""}</text>
        {series.map((s) => (
          <path key={s.key} d={path(s.points)} className={`line s${s.slot}`} />
        ))}
        {series.map((s) => {
          const last = [...s.points].reverse().find((p) => p.y !== null);
          if (!last || last.y === null) return null;
          return (
            <g key={s.key}>
              <circle className={`dot s${s.slot}`} cx={sx(last.x)} cy={sy(last.y)} r={4} />
              {series.length <= 4 && (
                <text className="end-label" x={sx(last.x) + 8} y={sy(last.y)} dominantBaseline="middle">
                  {yFormat(last.y)}
                </text>
              )}
            </g>
          );
        })}
        {hover !== null && <line className="crosshair" x1={sx(hover)} x2={sx(hover)} y1={pad.t} y2={pad.t + ih} />}
        <rect
          x={pad.l} y={pad.t} width={iw} height={ih} fill="transparent"
          onMouseMove={onMove} onMouseLeave={() => setHover(null)}
        />
      </svg>
      {hover !== null && (
        <div className="tooltip" style={{ left: Math.min(sx(hover) + 12, width - 170) }} role="status">
          <div className="muted small">{xLabel} {hover}</div>
          {hoverRows.map(({ s, p }) => (
            <div key={s.key}><i className={`key s${s.slot}`} />{s.label}: <b>{p && p.y !== null ? yFormat(p.y) : "—"}</b></div>
          ))}
        </div>
      )}
    </figure>
  );
}

export interface DistRow {
  key: string;
  label: string;
  values: number[];
  median?: number | null;
  p25?: number | null;
  p75?: number | null;
  note?: ReactNode;
}

/** Strip + box plot rows on one shared x-axis (ms). Log scale when the range is wide. */
export function DistributionChart({ title, rows, unit = "ms" }: { title: string; rows: DistRow[]; unit?: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<{ row: string; v: number; x: number; y: number } | null>(null);
  const all = rows.flatMap((r) => r.values).filter((v) => v > 0);
  const [logMode, setLogMode] = useState<boolean | null>(null);
  if (!all.length) {
    return (
      <figure className="chart">
        <figcaption className="chart-title">{title}</figcaption>
        <p className="empty small">Run a benchmark to see measured latency distributions.</p>
      </figure>
    );
  }
  const lo = Math.min(...all), hi = Math.max(...all);
  const log = logMode ?? hi / lo > 30;
  const rowH = 44, pad = { l: 190, r: 24, t: 8, b: 30 };
  const iw = Math.max(10, width - pad.l - pad.r);
  const height = pad.t + rows.length * rowH + pad.b;
  const f = (v: number) => (log ? Math.log10(v) : v);
  const a = log ? f(lo) - 0.05 : 0, b = log ? f(hi) + 0.05 : hi * 1.05;
  const sx = (v: number) => pad.l + ((f(Math.max(v, lo)) - a) / (b - a)) * iw;
  const ticks = log
    ? Array.from({ length: Math.ceil(b) - Math.floor(a) + 1 }, (_, i) => 10 ** (Math.floor(a) + i)).filter((t) => f(t) >= a && f(t) <= b)
    : niceTicks(0, b, 5);
  return (
    <figure className="chart" ref={ref}>
      <figcaption className="chart-title">
        {title}
        <label className="small muted chart-toggle">
          <input type="checkbox" checked={log} onChange={(e) => setLogMode(e.target.checked)} /> log scale
        </label>
      </figcaption>
      <svg width={width} height={height} role="img" aria-label={`${title}: per-trial latency strip plot`}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="grid" x1={sx(t)} x2={sx(t)} y1={pad.t} y2={height - pad.b} />
            <text className="axis" x={sx(t)} y={height - 10} textAnchor="middle">{t < 1 ? t.toPrecision(1) : t.toLocaleString()} {unit}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const cy = pad.t + i * rowH + rowH / 2;
          return (
            <g key={r.key}>
              <text className="row-label" x={pad.l - 10} y={cy} textAnchor="end" dominantBaseline="middle">{r.label}</text>
              {r.p25 != null && r.p75 != null && (
                <rect className="box" x={sx(r.p25)} y={cy - 10} width={Math.max(2, sx(r.p75) - sx(r.p25))} height={20} rx={4} />
              )}
              {r.values.map((v, j) => {
                const jitter = (((j * 7919) % 17) / 17 - 0.5) * 18;
                return (
                  <circle
                    key={j} className="dot s1 small-dot" cx={sx(v)} cy={cy + jitter} r={3}
                    onMouseEnter={() => setHover({ row: r.label, v, x: sx(v), y: cy + jitter })}
                    onMouseLeave={() => setHover(null)}
                  />
                );
              })}
              {r.median != null && <line className="median" x1={sx(r.median)} x2={sx(r.median)} y1={cy - 14} y2={cy + 14} />}
            </g>
          );
        })}
      </svg>
      <p className="small muted">Each dot is one measured trial. Shaded box: middle 50% (p25–p75). Vertical bar: median.</p>
      {hover && (
        <div className="tooltip" style={{ left: Math.min(hover.x + 10, width - 180), top: hover.y + 20 }} role="status">
          {hover.row}: <b>{hover.v.toFixed(3)} {unit}</b>
        </div>
      )}
    </figure>
  );
}

/** Horizontal bars, e.g. order-book depth comparisons. */
export function BarList({ items, format = (v) => String(v) }: { items: { label: string; value: number; slot?: 1 | 2 | 3 }[]; format?: (v: number) => string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ul className="barlist">
      {items.map((i) => (
        <li key={i.label}>
          <span className="barlist-label">{i.label}</span>
          <span className="barlist-track"><span className={`barlist-bar s${i.slot ?? 1}`} style={{ width: `${(i.value / max) * 100}%` }} /></span>
          <span className="barlist-value">{format(i.value)}</span>
        </li>
      ))}
    </ul>
  );
}
