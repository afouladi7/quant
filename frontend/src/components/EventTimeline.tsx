import { useState } from "react";
import { useStream } from "../api/stream";
import type { MarketLabEvent } from "../api/types";
import { useViewMode } from "../state/viewMode";

/** Shared timeline of actual backend events (never UI-only annotations). */
export function EventTimeline({ limit = 12, modules, title = "Event timeline" }: { limit?: number; modules?: string[]; title?: string }) {
  const { events, connection, dropped } = useStream();
  const { mode } = useViewMode();
  const [selected, setSelected] = useState<MarketLabEvent | null>(null);
  const recent = events.filter((e) => !modules || modules.includes(e.module)).slice(-limit).reverse();

  return (
    <section className="panel" aria-labelledby="timeline-title">
      <div className="panel-head">
        <h2 id="timeline-title">{title}</h2>
        <span className="muted small">Live from the backend</span>
      </div>
      {connection === "disconnected" && events.length === 0 ? (
        <p className="empty">The backend is unreachable, so there are no events to show yet.</p>
      ) : recent.length === 0 ? (
        <p className="empty">No events yet. Press Start in the control bar to begin the simulation.</p>
      ) : (
        <ol className="timeline">
          {recent.map((e) => (
            <li key={e.seq}>
              <button
                type="button"
                className="timeline-item"
                aria-expanded={selected?.seq === e.seq}
                onClick={() => setSelected(selected?.seq === e.seq ? null : e)}
              >
                <time dateTime={e.ts}>{new Date(e.ts).toLocaleTimeString()}</time>
                <span className="tag">{e.module}</span>
                <span className="msg">{e.message}</span>
                {mode === "technical" && <code className="small">{e.type}</code>}
              </button>
              {selected?.seq === e.seq && (
                <pre className="event-detail" aria-label="Event technical details">
                  {JSON.stringify(e, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ol>
      )}
      {mode === "technical" && dropped > 0 && (
        <p className="muted small">{dropped} stream messages were dropped because this browser fell behind.</p>
      )}
    </section>
  );
}
