import { useCallback, useEffect, useRef, useState } from "react";
import { useStream } from "../api/stream";

/**
 * Fetch a backend snapshot and keep it fresh: refetch when new events arrive for
 * the given modules (throttled) and on an interval while the simulation runs.
 * The backend stays authoritative; this hook only mirrors it.
 */
export function useLive<T>(fetcher: () => Promise<T>, modules: string[], intervalMs = 1000) {
  const { events, status, connection } = useStream();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  const inflight = useRef(false);
  const pending = useRef(false);

  const refresh = useCallback(async () => {
    if (inflight.current) {
      pending.current = true;
      return;
    }
    inflight.current = true;
    try {
      setData(await fetchRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      inflight.current = false;
      setLoading(false);
      if (pending.current) {
        pending.current = false;
        void refresh();
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const key = modules.join(",");
  const lastSeq = events.filter((e) => modules.includes(e.module)).at(-1)?.seq ?? 0;
  useEffect(() => {
    if (!lastSeq) return;
    const t = setTimeout(() => void refresh(), 120);
    return () => clearTimeout(t);
  }, [lastSeq, key, refresh]);

  useEffect(() => {
    if (connection === "connected") void refresh();
  }, [connection, refresh]);

  const running = status?.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => void refresh(), intervalMs);
    return () => clearInterval(t);
  }, [running, intervalMs, refresh]);

  return { data, error, loading, refresh, setData };
}
