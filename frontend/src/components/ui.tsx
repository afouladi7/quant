import { useState, type ReactNode } from "react";
import type { Num } from "../lib/format";
import { HelpToggle } from "./learn";
import { signClass } from "../lib/format";
import { useViewMode } from "../state/viewMode";

export function Panel({ title, actions, children, className = "", id, help }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; id?: string; help?: ReactNode }) {
  return (
    <section className={`panel ${className}`} aria-labelledby={id}>
      {(title || actions || help) && (
        <div className="panel-head">
          {title && <h2 id={id}>{title}</h2>}
          <div className="panel-actions">
            {actions}
            {help && <HelpToggle>{help}</HelpToggle>}
          </div>
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint, tone, raw }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Num; raw?: Num }) {
  const { mode } = useViewMode();
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone !== undefined ? signClass(tone) : ""}`}>{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
      {mode === "technical" && raw !== undefined && raw !== null && <code className="stat-raw">{String(raw)}</code>}
    </div>
  );
}

const STATUS: Record<string, { icon: string; text: string }> = {
  open: { icon: "○", text: "Open" },
  partially_filled: { icon: "◐", text: "Partially filled" },
  filled: { icon: "●", text: "Filled" },
  canceled: { icon: "⊘", text: "Canceled" },
  rejected: { icon: "✕", text: "Rejected" },
  proposed: { icon: "○", text: "Proposed" },
  executed: { icon: "●", text: "Executed" },
  partially_executed: { icon: "◐", text: "Partially executed" },
  failed: { icon: "✕", text: "Failed" },
  completed: { icon: "●", text: "Completed" },
  running: { icon: "◌", text: "Running" },
  queued: { icon: "○", text: "Queued" },
  not_needed: { icon: "–", text: "Not needed" },
};

/** Status is conveyed by icon + text, never color alone. */
export function StatusBadge({ status, filled, quantity }: { status: string; filled?: number; quantity?: number }) {
  const s = STATUS[status] ?? { icon: "•", text: status };
  const partialCancel = status === "canceled" && filled && quantity && filled > 0 && filled < quantity;
  return (
    <span className={`status status-${status}`}>
      <span aria-hidden="true">{s.icon}</span> {partialCancel ? "Partial fill, rest canceled" : s.text}
    </span>
  );
}

export function Explain({ simple, technical }: { simple?: ReactNode; technical?: ReactNode }) {
  const { mode } = useViewMode();
  const body = mode === "technical" ? technical ?? simple : simple ?? technical;
  if (!body) return null;
  return <div className={`explain explain-${mode}`}>{body}</div>;
}

export function TechOnly({ children }: { children: ReactNode }) {
  const { mode } = useViewMode();
  return mode === "technical" ? <>{children}</> : null;
}

export function SimpleOnly({ children }: { children: ReactNode }) {
  const { mode } = useViewMode();
  return mode === "simple" ? <>{children}</> : null;
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void; label: string }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button key={t.id} type="button" role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null | undefined }) {
  if (!error) return null;
  return <p className="error-text" role="alert">{error}</p>;
}

export function Loading({ what }: { what: string }) {
  return <p className="empty" aria-busy="true">Loading {what}…</p>;
}

export function JsonBlock({ value, label = "Technical details" }: { value: unknown; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="json-block">
      <button type="button" className="link" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} {label}
      </button>
      {open && <pre className="event-detail">{JSON.stringify(value, null, 2)}</pre>}
    </div>
  );
}

/** Wrap an async action with busy + error state. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, setError };
}
