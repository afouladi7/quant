// Display formatting only. Values arrive from the backend as exact decimal strings;
// we never do authoritative arithmetic on them here.

export type Num = string | number | null | undefined;

const toNum = (v: Num): number | null => (v === null || v === undefined || v === "" ? null : Number(v));

export function fmtNum(v: Num, digits = 0): string {
  const n = toNum(v);
  return n === null || Number.isNaN(n)
    ? "—"
    : n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtMoney(v: Num, digits = 2, ccy = "$"): string {
  const n = toNum(v);
  if (n === null || Number.isNaN(n)) return "—";
  const s = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${n < 0 ? "−" : ""}${ccy}${s}`;
}

export function fmtSignedMoney(v: Num, digits = 2, ccy = "$"): string {
  const n = toNum(v);
  if (n === null || Number.isNaN(n)) return "—";
  return `${n > 0 ? "+" : ""}${fmtMoney(v, digits, ccy)}`;
}

export function fmtPrice(v: Num, digits?: number): string {
  if (v === null || v === undefined) return "—";
  if (digits === undefined) return String(v);
  return fmtNum(v, digits);
}

export function fmtPct(v: Num, digits = 1): string {
  const n = toNum(v);
  return n === null || Number.isNaN(n) ? "—" : `${(n * 100).toFixed(digits)}%`;
}

export function fmtMs(v: Num, digits = 3): string {
  const n = toNum(v);
  return n === null || Number.isNaN(n) ? "—" : `${n.toFixed(digits)} ms`;
}

export function compact(v: Num): string {
  const n = toNum(v);
  if (n === null || Number.isNaN(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `${(n / 1e3).toFixed(1)}K`;
  return fmtNum(n);
}

export function signClass(v: Num): string {
  const n = toNum(v);
  return n === null || n === 0 ? "" : n > 0 ? "pos" : "neg";
}

export function shortTime(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour12: false });
}
