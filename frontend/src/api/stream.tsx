import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, streamUrl } from "./client";
import type { MarketLabEvent, SimulationStatus, StreamMessage } from "./types";

export type ConnectionState = "connecting" | "connected" | "disconnected";

interface StreamState {
  connection: ConnectionState;
  status: SimulationStatus | null;
  events: MarketLabEvent[];
  dropped: number;
  /** Apply an authoritative status returned by a REST command. */
  applyStatus: (s: SimulationStatus) => void;
}

const MAX_EVENTS = 300; // client-side bound; full history lives on the server
const StreamContext = createContext<StreamState | null>(null);

function mergeEvents(prev: MarketLabEvent[], incoming: MarketLabEvent[]): MarketLabEvent[] {
  const seen = new Set(prev.map((e) => e.seq));
  const merged = [...prev, ...incoming.filter((e) => !seen.has(e.seq))];
  merged.sort((a, b) => a.seq - b.seq);
  return merged.slice(-MAX_EVENTS);
}

export function StreamProvider({ children }: { children: ReactNode }) {
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [status, setStatus] = useState<SimulationStatus | null>(null);
  const [events, setEvents] = useState<MarketLabEvent[]>([]);
  const [dropped, setDropped] = useState(0);
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      setConnection("connecting");
      ws = new WebSocket(streamUrl());
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as StreamMessage;
        switch (msg.kind) {
          case "hello":
            retry.current = 0;
            setConnection("connected");
            setStatus(msg.status);
            // Backfill history so a reconnecting client sees what it missed.
            api.events({ limit: 100 }).then((h) => setEvents((p) => mergeEvents(p, h))).catch(() => undefined);
            break;
          case "status":
            setStatus(msg.status);
            break;
          case "event":
            setEvents((p) => mergeEvents(p, [msg.event]));
            break;
          case "dropped":
            setDropped((d) => d + msg.count);
            break;
        }
      };
      ws.onclose = () => {
        if (closed) return;
        setConnection("disconnected");
        const delay = Math.min(10_000, 500 * 2 ** retry.current++);
        timer = setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);

  const applyStatus = useCallback((s: SimulationStatus) => setStatus(s), []);
  const value = useMemo(
    () => ({ connection, status, events, dropped, applyStatus }),
    [connection, status, events, dropped, applyStatus],
  );
  return <StreamContext.Provider value={value}>{children}</StreamContext.Provider>;
}

export function useStream(): StreamState {
  const ctx = useContext(StreamContext);
  if (!ctx) throw new Error("useStream must be used inside <StreamProvider>");
  return ctx;
}
