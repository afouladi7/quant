import { useEffect, useState } from "react";
import { http } from "../api/client";
import { useStream } from "../api/stream";
import type { MarketLabEvent } from "../api/types";
import { shortTime } from "../lib/format";
import { useViewMode } from "../state/viewMode";
import { ErrorNote, Panel } from "./ui";

/** Every backend event sharing one correlation ID: order → routing → fills → inventory → P&L → hedge. */
export function OrderTrace({ correlationId, onClose }: { correlationId: string; onClose: () => void }) {
  const [events, setEvents] = useState<MarketLabEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { mode } = useViewMode();
  const { events: live } = useStream();
  const lastRelated = live.filter((e) => e.correlation_id === correlationId).at(-1)?.seq;
  useEffect(() => {
    http
      .get<MarketLabEvent[]>(`/events?correlation_id=${encodeURIComponent(correlationId)}&limit=500`)
      .then(setEvents)
      .catch((e: Error) => setError(e.message));
  }, [correlationId, lastRelated]);
  return (
    <Panel
      title={<>Trace <code className="small">{correlationId}</code></>}
      id="trace"
      actions={<button type="button" className="btn" onClick={onClose}>Close</button>}
      className="trace"
    >
      <ErrorNote error={error} />
      {events && events.length === 0 && <p className="empty">No events recorded for this ID (history is bounded; older events may have been discarded).</p>}
      {events && (
        <ol className="trace-list">
          {events.map((e) => (
            <li key={e.seq}>
              <span className="mono small muted">{shortTime(e.ts)}</span>
              <span className="tag">{e.type}</span>
              <span>{e.message}</span>
              {mode === "technical" && <pre className="event-detail">{JSON.stringify({ seq: e.seq, id: e.id, entity_id: e.entity_id, mono_ns: e.mono_ns, data: e.data }, null, 2)}</pre>}
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
